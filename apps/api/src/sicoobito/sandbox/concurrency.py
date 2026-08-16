"""Fila local de concorrência para criação de sandbox.

Horizonte 3 da auditoria arquitetural (`docs/proposals/plano-implementacao-
auditoria-arquitetural.md`): sem um teto, sessões demais criando container ao
mesmo tempo competem pela mesma CPU/memória do host e degradam todas juntas em
vez de enfileirar. Escopo deliberadamente reduzido (decisão do usuário) — fila
FIFO em processo, sem broker nem pool multi-host; o produto roda hoje
local-first numa única máquina, então isso é o que resolve o problema real.

Só a criação de um sandbox *novo* passa pela fila. Reaproveitar o sandbox já
ativo de uma sessão (reconexão após reload) não deve competir por vaga de novo
— ver `SandboxManager.acquire`/`ExecutorSandboxManager.acquire`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Waiter:
    session_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)


class SandboxConcurrencyGate:
    """No máximo `max_concurrent` sandboxes ativos ao mesmo tempo, FIFO."""

    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, max_concurrent)
        self._active: set[str] = set()
        self._waiters: list[_Waiter] = []
        self._lock = asyncio.Lock()

    async def acquire(self, session_id: str) -> None:
        """Bloqueia até haver vaga. Idempotente: sessão já ativa retorna na hora."""
        async with self._lock:
            if session_id in self._active:
                return
            if len(self._active) < self._max:
                self._active.add(session_id)
                return
            waiter = _Waiter(session_id)
            self._waiters.append(waiter)

        try:
            await waiter.event.wait()
        except asyncio.CancelledError:
            # Requisição cancelada (cliente caiu, timeout) enquanto esperava —
            # sem isso a vaga reservada vazaria e travaria a fila para sempre.
            async with self._lock:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                else:
                    # Já tinha sido promovido a ativo entre o cancelamento e o
                    # lock: devolve a vaga que acabou de ganhar.
                    self._active.discard(session_id)
                    self._promote_next()
            raise

    async def release(self, session_id: str) -> None:
        """Idempotente — seguro chamar mesmo sem `acquire` bem-sucedido antes."""
        async with self._lock:
            if session_id not in self._active:
                self._waiters = [w for w in self._waiters if w.session_id != session_id]
                return
            self._active.discard(session_id)
            self._promote_next()

    def _promote_next(self) -> None:
        """Chamado com `self._lock` já adquirido."""
        if self._waiters:
            proximo = self._waiters.pop(0)
            self._active.add(proximo.session_id)
            proximo.event.set()

    def snapshot(self) -> dict[str, Any]:
        return {
            "active": len(self._active),
            "max_concurrent": self._max,
            "waiting": [
                {"session_id": w.session_id, "position": i + 1}
                for i, w in enumerate(self._waiters)
            ],
        }
