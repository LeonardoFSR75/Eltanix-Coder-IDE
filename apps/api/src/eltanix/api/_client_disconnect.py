"""`await_or_abandon_on_disconnect` — aguarda uma corrotina mas a cancela se o
cliente HTTP fechar a conexão no meio.

Usado pelos endpoints que chamam `engine.complete()` fora do grafo do agente
(edição inline / Cmd+K e autocompletar inline): sem isto, uma chamada de LLM
abandonada pelo editor (Esc enquanto "gerando…", ou a próxima tecla cancelando
o ghost text anterior) seguiria correndo até o fim, gastando tokens por um
resultado que ninguém vai ler. O adaptador de provedor é httpx por baixo, que
aborta a request HTTP quando a task é cancelada.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import suppress

from fastapi import Request

from eltanix.logging_setup import get_logger

log = get_logger(__name__)


async def await_or_abandon_on_disconnect[T](request: Request, coro: Awaitable[T]) -> T:
    task: asyncio.Task[T] = asyncio.ensure_future(coro)

    async def _watch() -> None:
        try:
            while not task.done():
                if await request.is_disconnected():
                    task.cancel()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # um watcher com problema nunca derruba a request
            log.warning("api.disconnect_watch_failed", error=str(exc)[:200])

    watcher = asyncio.ensure_future(_watch())
    try:
        return await task
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
