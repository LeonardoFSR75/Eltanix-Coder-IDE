"""Circuit breaker e estatísticas de saúde por modelo, com estado no Redis.

Por que Redis e não memória: o estado sobrevive a reload do uvicorn (comum em
desenvolvimento) e serve mais de um worker. Se o Redis cair, o módulo degrada
para "tudo disponível" em vez de derrubar o gateway — perder o breaker é ruim,
perder o gateway inteiro é pior.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from redis.asyncio import Redis

from novaai_studio.logging_setup import get_logger
from novaai_studio.router.catalog import Resilience

log = get_logger(__name__)

_PREFIX = "novaai_studio:health"
_LATENCY_SAMPLES = 50


@dataclass(slots=True)
class ModelHealth:
    model_id: str
    available: bool = True
    open_until: float | None = None
    consecutive_fails: int = 0
    trips: int = 0
    successes: int = 0
    failures: int = 0
    latency_p50_ms: int | None = None
    latency_p95_ms: int | None = None
    recent_latencies: list[int] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return 1.0 if total == 0 else self.successes / total

    @property
    def cooldown_remaining_s(self) -> int:
        if self.open_until is None:
            return 0
        return max(0, int(self.open_until - time.time()))


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * pct))
    return ordered[index]


class HealthTracker:
    def __init__(self, redis: Redis | None, resilience: Resilience) -> None:
        self._redis = redis
        self._res = resilience

    def _key(self, model_id: str, field_name: str) -> str:
        return f"{_PREFIX}:{model_id}:{field_name}"

    # ── Consulta ────────────────────────────────────────────────────────────

    async def is_available(self, model_id: str) -> bool:
        # Sem Redis não há estado de breaker: tudo é considerado disponível.
        if self._redis is None:
            return True
        try:
            open_until = await self._redis.get(self._key(model_id, "open_until"))
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))
            return True
        if not open_until:
            return True
        return time.time() >= float(open_until)

    async def snapshot(self, model_id: str) -> ModelHealth:
        if self._redis is None:
            return ModelHealth(model_id=model_id)

        try:
            pipe = self._redis.pipeline()
            pipe.get(self._key(model_id, "open_until"))
            pipe.get(self._key(model_id, "fails"))
            pipe.get(self._key(model_id, "trips"))
            pipe.get(self._key(model_id, "ok_count"))
            pipe.get(self._key(model_id, "err_count"))
            pipe.lrange(self._key(model_id, "latency"), 0, _LATENCY_SAMPLES)
            open_until, fails, trips, ok_count, err_count, latencies = await pipe.execute()
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))
            return ModelHealth(model_id=model_id)

        samples = [int(v) for v in (latencies or [])]
        open_at = float(open_until) if open_until else None
        return ModelHealth(
            model_id=model_id,
            available=open_at is None or time.time() >= open_at,
            open_until=open_at,
            consecutive_fails=int(fails or 0),
            trips=int(trips or 0),
            successes=int(ok_count or 0),
            failures=int(err_count or 0),
            latency_p50_ms=_percentile(samples, 0.50),
            latency_p95_ms=_percentile(samples, 0.95),
            recent_latencies=samples,
        )

    async def latency_p95(self, model_id: str) -> int | None:
        if self._redis is None:
            return None
        try:
            values = await self._redis.lrange(self._key(model_id, "latency"), 0, _LATENCY_SAMPLES)
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))
            return None
        return _percentile([int(v) for v in (values or [])], 0.95)

    # ── Registro ────────────────────────────────────────────────────────────

    async def record_success(self, model_id: str, latency_ms: int) -> None:
        if self._redis is None:
            return
        try:
            pipe = self._redis.pipeline()
            # Sucesso zera o contador de falhas e o de trips: o provedor voltou,
            # e o próximo cooldown deve recomeçar curto.
            pipe.delete(self._key(model_id, "fails"))
            pipe.delete(self._key(model_id, "trips"))
            pipe.delete(self._key(model_id, "open_until"))
            pipe.incr(self._key(model_id, "ok_count"))
            pipe.lpush(self._key(model_id, "latency"), latency_ms)
            pipe.ltrim(self._key(model_id, "latency"), 0, _LATENCY_SAMPLES - 1)
            await pipe.execute()
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))

    async def record_failure(self, model_id: str, *, reason: str) -> bool:
        """Registra a falha e devolve True se o circuito abriu agora."""
        if self._redis is None:
            return False
        try:
            pipe = self._redis.pipeline()
            pipe.incr(self._key(model_id, "fails"))
            pipe.incr(self._key(model_id, "err_count"))
            fails, _ = await pipe.execute()

            if int(fails) < self._res.allowed_fails:
                return False

            trips = int(await self._redis.incr(self._key(model_id, "trips")))
            # Backoff exponencial no número de aberturas seguidas, com teto.
            cooldown = min(
                self._res.cooldown_seconds * (2 ** (trips - 1)),
                self._res.cooldown_max_seconds,
            )
            await self._redis.set(
                self._key(model_id, "open_until"),
                str(time.time() + cooldown),
                ex=cooldown + 60,
            )
            await self._redis.delete(self._key(model_id, "fails"))
            log.warning(
                "health.circuit.open",
                model=model_id,
                cooldown_s=cooldown,
                trips=trips,
                reason=reason,
            )
            return True
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))
            return False

    async def reset(self, model_id: str) -> None:
        """Fecha o circuito manualmente (usado pelo botão de teste no dashboard)."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(
                self._key(model_id, "fails"),
                self._key(model_id, "trips"),
                self._key(model_id, "open_until"),
            )
        except Exception as exc:
            log.warning("health.redis.unavailable", error=str(exc))
