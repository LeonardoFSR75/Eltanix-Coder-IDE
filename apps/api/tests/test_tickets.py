"""Tickets de WebSocket.

O browser não pode mandar header ao abrir um WebSocket, então a credencial iria
na query string — que aparece em log, histórico e Referer. Estes testes travam
as propriedades que tornam um ticket aceitável ali: uso único, escopo e prazo.
"""

from __future__ import annotations

import time

from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore


async def test_issued_ticket_is_accepted_once():
    store = TicketStore(None)
    ticket = await store.issue("terminal:abc")

    assert await store.consume(ticket, "terminal:abc") is True
    # Uso único: o segundo uso não vale, então vazar um ticket já usado não dá
    # acesso a nada.
    assert await store.consume(ticket, "terminal:abc") is False


async def test_ticket_is_bound_to_its_scope():
    store = TicketStore(None)
    ticket = await store.issue("terminal:sessao-a")

    # Um ticket da sessão A não abre o terminal da sessão B.
    assert await store.consume(ticket, "terminal:sessao-b") is False


async def test_unknown_ticket_is_rejected():
    store = TicketStore(None)
    assert await store.consume("inventado", "terminal:x") is False
    assert await store.consume("", "terminal:x") is False


async def test_expired_ticket_is_rejected(monkeypatch):
    store = TicketStore(None)
    ticket = await store.issue("terminal:abc")

    # Avança o relógio além do TTL, a partir do agora real.
    futuro = time.time() + TICKET_TTL_SECONDS + 1
    monkeypatch.setattr(time, "time", lambda: futuro)
    assert await store.consume(ticket, "terminal:abc") is False


async def test_tickets_are_unguessable():
    store = TicketStore(None)
    emitidos = {await store.issue("terminal:x") for _ in range(50)}

    assert len(emitidos) == 50, "tickets precisam ser únicos"
    assert all(len(t) >= 32 for t in emitidos), "entropia insuficiente"


async def test_broken_redis_falls_back_to_memory():
    class BrokenRedis:
        async def set(self, *_a, **_kw):
            raise ConnectionError("redis caiu")

        async def get(self, *_a, **_kw):
            raise ConnectionError("redis caiu")

    store = TicketStore(BrokenRedis())  # type: ignore[arg-type]
    ticket = await store.issue("terminal:abc")
    assert await store.consume(ticket, "terminal:abc") is True
