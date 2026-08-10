"""Controle de orçamento derivado do `request_log`.

Não há tabela de saldo: o gasto é sempre somado do log. Um agregado mantido à
parte poderia divergir do fato, e o volume local não justifica o risco.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from sicoobito.config import Settings
from sicoobito.db.models import RequestLog
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Estimativa conservadora de custo por chamada em voo, usada só para fechar a
# janela de corrida entre `check()` passar e o custo real ser persistido em
# `request_log` (que só acontece bem depois, quando a chamada ao provedor
# termina). Não precisa ser exata — só grande o bastante para que N chamadas
# concorrentes não vejam todas o mesmo total "dentro do limite" ao mesmo
# tempo; o valor real do banco corrige a conta assim que é gravado.
_RESERVATION_ESTIMATE_USD = Decimal("0.05")
_RESERVATION_TTL_SECONDS = 120.0


class BudgetExceededError(RuntimeError):
    def __init__(self, period: str, spent: Decimal, limit: float) -> None:
        super().__init__(
            f"Orçamento {period} estourado: ${spent:.4f} de ${limit:.2f}. "
            "Ajuste BUDGET_*_USD ou desligue BUDGET_HARD_STOP."
        )
        self.period = period
        self.spent = spent
        self.limit = limit


@dataclass(slots=True)
class BudgetStatus:
    daily_spent: Decimal
    monthly_spent: Decimal
    daily_limit: float
    monthly_limit: float
    hard_stop: bool

    @property
    def daily_exceeded(self) -> bool:
        return self.daily_limit > 0 and self.daily_spent >= Decimal(str(self.daily_limit))

    @property
    def monthly_exceeded(self) -> bool:
        return self.monthly_limit > 0 and self.monthly_spent >= Decimal(str(self.monthly_limit))


class BudgetGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()
        # (timestamp monotônico, estimativa) de checagens recentes que
        # passaram — somado ao gasto lido do banco em `check()`.
        self._reservations: list[tuple[float, Decimal]] = []

    @property
    def active(self) -> bool:
        return self.settings.budget_daily_usd > 0 or self.settings.budget_monthly_usd > 0

    async def status(self) -> BudgetStatus:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        async with session_scope() as session:
            daily = await session.scalar(
                select(func.coalesce(func.sum(RequestLog.cost_usd), 0)).where(
                    RequestLog.created_at >= day_start
                )
            )
            monthly = await session.scalar(
                select(func.coalesce(func.sum(RequestLog.cost_usd), 0)).where(
                    RequestLog.created_at >= month_start
                )
            )

        return BudgetStatus(
            daily_spent=Decimal(str(daily or 0)),
            monthly_spent=Decimal(str(monthly or 0)),
            daily_limit=self.settings.budget_daily_usd,
            monthly_limit=self.settings.budget_monthly_usd,
            hard_stop=self.settings.budget_hard_stop,
        )

    async def check(self) -> None:
        """Avisa sempre; bloqueia só com BUDGET_HARD_STOP ligado.

        Checar e reservar uma estimativa acontecem sob o mesmo lock —
        sem isso, chamadas concorrentes leriam o mesmo total "ainda dentro
        do limite" antes de qualquer uma delas ter seu custo real persistido
        (o que só ocorre bem depois, quando a chamada ao provedor termina),
        permitindo todas passarem e o hard stop nunca realmente parar nada.
        """
        if not self.active:
            return
        async with self._lock:
            try:
                status = await self.status()
            except Exception as exc:
                log.warning("budget.check.failed", error=str(exc))
                return

            now = time.monotonic()
            self._reservations = [
                (t, c) for t, c in self._reservations if now - t < _RESERVATION_TTL_SECONDS
            ]
            reserved = sum((c for _, c in self._reservations), Decimal(0))

            daily_spent = status.daily_spent + reserved
            monthly_spent = status.monthly_spent + reserved

            for period, exceeded, spent, limit in (
                (
                    "diário",
                    status.daily_limit > 0 and daily_spent >= Decimal(str(status.daily_limit)),
                    daily_spent,
                    status.daily_limit,
                ),
                (
                    "mensal",
                    status.monthly_limit > 0
                    and monthly_spent >= Decimal(str(status.monthly_limit)),
                    monthly_spent,
                    status.monthly_limit,
                ),
            ):
                if not exceeded:
                    continue
                log.warning("budget.exceeded", period=period, spent=float(spent), limit=limit)
                if status.hard_stop:
                    raise BudgetExceededError(period, spent, limit)

            self._reservations.append((now, _RESERVATION_ESTIMATE_USD))


# Tempo de retenção sugerido para relatórios longos; usado pelas métricas.
DEFAULT_WINDOW = timedelta(days=30)
