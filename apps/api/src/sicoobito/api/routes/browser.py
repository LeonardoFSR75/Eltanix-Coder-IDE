"""Rota de navegador manual — painel dedicado no IDE, fora do fluxo do agente.

Reaproveita o mesmo serviço isolado (`services/browser`) e `BrowserClient` que
a ferramenta `browser_action` do agente usa (`browser/client.py`), mas aqui a
sessão pertence ao painel que o usuário abriu no IDE, não a uma execução do
agente: sem `RiskClass`, sem aprovação humana no grafo — o usuário já está no
controle direto do navegador, o mesmo raciocínio por trás do Terminal do IDE
não pedir aprovação a cada comando digitado.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Literal

import websockets
import websockets.exceptions
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore
from sicoobito.browser.client import (
    BrowserClient,
    BrowserConfig,
    BrowserError,
    BrowserUnavailableError,
)
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser"], dependencies=[AuthDep])

# Mesmo motivo de `lsp.py`/`workspace.py`: o browser não envia `Authorization`
# ao abrir um WebSocket, então esta rota (o stream ao vivo) fica de fora do
# `AuthDep` do router acima e se autentica só pelo ticket de uso único.
ws_router = APIRouter(prefix="/api/browser", tags=["browser"])


def _escopo_stream(session_id: str) -> str:
    return f"browser-stream:{session_id}"


def _client(request: Request, session_id: str) -> BrowserClient:
    """Uma instância por sessão, cacheada em `app.state.browser_panel_clients`.

    Antes, cada requisição HTTP criava uma instância nova — `_started` nascia
    sempre `False`, e todo clique/digitação do painel pagava um `POST
    /sessions` extra (idempotente do lado do serviço, mas um round-trip
    inteiro) antes da própria ação. Cacheando por sessão, `_started` passa a
    refletir de verdade se esta sessão já chamou `start()`, no mesmo padrão
    que o `AgentRunner` já usa para o navegador do agente.
    """
    config: BrowserConfig | None = getattr(request.app.state, "browser_config", None)
    if config is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Serviço de navegador não configurado (BROWSER_URL vazio nesta instância).",
        )
    clients: dict[str, BrowserClient] = request.app.state.browser_panel_clients
    key = f"panel-{session_id}"
    client = clients.get(key)
    if client is None:
        client = BrowserClient(key, config, request.app.state.browser_http)
        clients[key] = client
    return client


class BrowserActionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    action: Literal["navigate", "click", "type", "screenshot", "content"]
    url: str | None = None
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None


@router.post("/action")
async def browser_action(payload: BrowserActionRequest, request: Request) -> dict[str, Any]:
    if payload.action == "navigate" and not (payload.url or "").startswith(("http://", "https://")):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "`navigate` exige `url` começando com http:// ou https://."
        )
    if payload.action == "click" and not payload.selector and payload.x is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "`click` exige `selector` ou `x`/`y`.")
    if payload.action == "type" and (not payload.selector or payload.text is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "`type` exige `selector` e `text`.")

    client = _client(request, payload.session_id)
    try:
        return await client.action(
            {
                "action": payload.action,
                "url": payload.url,
                "selector": payload.selector,
                "x": payload.x,
                "y": payload.y,
                "text": payload.text,
            }
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/sessions/{session_id}/network")
async def browser_network_log(session_id: str, request: Request) -> dict[str, Any]:
    client = _client(request, session_id)
    try:
        return {"requests": await client.network_log()}
    except BrowserUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/sessions/{session_id}/stream-ticket")
async def browser_stream_ticket(session_id: str, request: Request) -> dict[str, Any]:
    config: BrowserConfig | None = getattr(request.app.state, "browser_config", None)
    if config is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Serviço de navegador não configurado (BROWSER_URL vazio nesta instância).",
        )
    store: TicketStore | None = getattr(request.app.state, "tickets", None)
    if store is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Tickets indisponíveis.")
    emitido = await store.issue(_escopo_stream(session_id))
    return {"ticket": emitido, "expires_in": TICKET_TTL_SECONDS}


@ws_router.websocket("/sessions/{session_id}/stream")
async def browser_stream_socket(websocket: WebSocket, session_id: str) -> None:
    """Ponte burra entre o WS do frontend e o WS de screencast do
    `services/browser` (`stream_screencast` em `services/browser/app.py`).

    Diferente do salto browser→API (ticket, porque é o browser do usuário que
    abre a conexão e não pode mandar header customizado), o salto API→serviço
    de navegador aqui é originado pelo servidor: pode mandar `Authorization`
    de verdade, reaproveitando o mesmo `BROWSER_TOKEN` que as rotas REST já usam.
    """
    store: TicketStore | None = getattr(websocket.app.state, "tickets", None)
    bilhete = websocket.query_params.get("ticket", "")
    if store is None or not await store.consume(bilhete, _escopo_stream(session_id)):
        log.warning("browser.stream.rejected", session=session_id)
        await websocket.close(code=4401, reason="ticket inválido ou expirado")
        return

    config: BrowserConfig | None = getattr(websocket.app.state, "browser_config", None)
    if config is None:
        await websocket.close(code=4503, reason="serviço de navegador não configurado")
        return

    ws_base = config.base_url.replace("https://", "wss://").replace("http://", "ws://")
    upstream_url = f"{ws_base}/sessions/{session_id}/stream"
    headers = {"Authorization": f"Bearer {config.token}"} if config.token else {}

    await websocket.accept()
    try:
        async with websockets.connect(
            upstream_url, additional_headers=headers, max_size=None
        ) as upstream:

            async def do_upstream_para_o_editor() -> None:
                async for mensagem in upstream:
                    await websocket.send_text(
                        mensagem if isinstance(mensagem, str) else mensagem.decode("utf-8")
                    )

            bombeador = asyncio.create_task(do_upstream_para_o_editor())
            try:
                while True:
                    # O frontend não manda nada de volta além de eventuais pings —
                    # a conexão existe só para receber frames; qualquer mensagem
                    # (inclusive desconexão) apenas mantém o laço vivo ou o encerra.
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                bombeador.cancel()
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        log.warning("browser.stream.upstream_failed", session=session_id, error=str(exc)[:200])
        with contextlib.suppress(Exception):
            erro = json.dumps({"type": "error", "message": "stream indisponível"})
            await websocket.send_text(erro)
        await websocket.close(code=4502)


@router.delete("/sessions/{session_id}")
async def close_browser_session(session_id: str, request: Request) -> dict[str, bool]:
    clients: dict[str, BrowserClient] = request.app.state.browser_panel_clients
    client = clients.pop(f"panel-{session_id}", None)
    if client is None:
        # Nenhuma ação foi feita nesta sessão — nada existe do lado do
        # serviço para fechar, então nem vale o DELETE.
        return {"closed": False}
    await client.stop()
    return {"closed": True}
