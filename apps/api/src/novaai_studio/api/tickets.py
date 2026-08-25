"""Tickets de uso único para autenticar WebSockets.

O browser não pode enviar header customizado ao abrir um WebSocket, então a
credencial teria de ir na query string — e a query string aparece em log de
servidor, histórico e Referer. Mandar a chave principal por ali a exporia de
forma permanente.

Um ticket resolve: o front pede um pelo proxy autenticado (onde a chave fica no
servidor), recebe um token aleatório que vale uma única conexão e expira em
segundos. Vazar um ticket usado não dá acesso a nada.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

TICKET_TTL_SECONDS = 60
_PREFIX = "novaai_studio:ws-ticket"


@dataclass(slots=True)
class _MemoryTicket:
    scope: str
    expires_at: float


class TicketStore:
    """Redis quando disponível; memória do processo como alternativa.

    Em memória o ticket não sobrevive a um reload do uvicorn — aceitável, já
    que ele vive 60 segundos de qualquer forma.
    """

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis
        self._memory: dict[str, _MemoryTicket] = {}

    async def issue(self, scope: str) -> str:
        ticket = secrets.token_urlsafe(32)
        if self._redis is not None:
            try:
                await self._redis.set(f"{_PREFIX}:{ticket}", scope, ex=TICKET_TTL_SECONDS)
                return ticket
            except Exception as exc:
                log.warning("tickets.redis.unavailable", error=str(exc))

        self._prune()
        self._memory[ticket] = _MemoryTicket(
            scope=scope, expires_at=time.time() + TICKET_TTL_SECONDS
        )
        return ticket

    async def consume(self, ticket: str, expected_scope: str) -> bool:
        """Valida e invalida o ticket. Um ticket serve para uma conexão só."""
        if not ticket:
            return False

        if self._redis is not None:
            try:
                chave = f"{_PREFIX}:{ticket}"
                # `GETDEL` (não `GET` + `DELETE` separados) é obrigatório
                # aqui: as duas operações juntas não são atômicas, então duas
                # conexões WebSocket com o mesmo ticket chegando quase ao
                # mesmo tempo podiam ambas ler antes de qualquer uma apagar —
                # as duas passavam, quebrando a garantia de uso único que é a
                # mitigação central do ticket viajar na query string do WS.
                scope = await self._redis.getdel(chave)
                if scope is None:
                    return False
                return scope == expected_scope
            except Exception as exc:
                log.warning("tickets.redis.unavailable", error=str(exc))

        self._prune()
        registro = self._memory.pop(ticket, None)
        if registro is None or registro.expires_at < time.time():
            return False
        return registro.scope == expected_scope

    def _prune(self) -> None:
        agora = time.time()
        expirados = [t for t, r in self._memory.items() if r.expires_at < agora]
        for ticket in expirados:
            self._memory.pop(ticket, None)
