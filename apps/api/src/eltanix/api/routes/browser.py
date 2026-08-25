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
import os
import time
from typing import Any, Literal

import websockets
import websockets.exceptions
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from eltanix.api.deps import AuthDep
from eltanix.api.tickets import TICKET_TTL_SECONDS, TicketStore
from eltanix.browser.client import (
    BrowserClient,
    BrowserConfig,
    BrowserError,
    BrowserUnavailableError,
)
from eltanix.browser.replay import (
    get_replay,
    list_recent_replays,
    mark_replay_expired,
    store_replay,
    was_replay_expired,
)
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser"], dependencies=[AuthDep])

# Mesmo motivo de `lsp.py`/`workspace.py`: o browser não envia `Authorization`
# ao abrir um WebSocket, então esta rota (o stream ao vivo) fica de fora do
# `AuthDep` do router acima e se autentica só pelo ticket de uso único.
ws_router = APIRouter(prefix="/api/browser", tags=["browser"])


def _escopo_stream(session_id: str) -> str:
    return f"browser-stream:{session_id}"


# Um painel aberto e nunca fechado explicitamente (usuário só fecha a aba do
# navegador, sem clicar em "fechar") deixava a entrada em
# `browser_panel_clients` (abaixo) para sempre — item 11 do plano de robustez
# do navegador interno. `services/browser` já expira a sessão de verdade
# sozinho (`SESSION_TTL_SECONDS`, default 1800s, ver `_reap_loop` naquele
# serviço); esta margem é bem maior de propósito, só para nunca competir com
# um painel ainda em uso enquanto o TTL do lado de lá não bate.
PANEL_CLIENT_IDLE_TTL_SECONDS = int(os.getenv("BROWSER_PANEL_CLIENT_IDLE_TTL_SECONDS", "3600"))


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
    last_used: dict[str, float] | None = getattr(
        request.app.state, "browser_panel_client_last_used", None
    )
    if last_used is None:
        last_used = {}
        request.app.state.browser_panel_client_last_used = last_used
    key = f"panel-{session_id}"
    client = clients.get(key)
    if client is None:
        client = BrowserClient(key, config, request.app.state.browser_http)
        clients[key] = client
    last_used[key] = time.time()
    return client


async def purge_idle_panel_clients(app_state: Any) -> int:
    """Remove do cache instâncias de `BrowserClient` ociosas há mais de
    `PANEL_CLIENT_IDLE_TTL_SECONDS` — ver comentário acima de
    `PANEL_CLIENT_IDLE_TTL_SECONDS`. Retorna quantas foram removidas."""
    clients: dict[str, BrowserClient] = getattr(app_state, "browser_panel_clients", {})
    last_used: dict[str, float] = getattr(app_state, "browser_panel_client_last_used", {})
    agora = time.time()
    ociosos = [
        key
        for key in list(clients)
        if agora - last_used.get(key, agora) > PANEL_CLIENT_IDLE_TTL_SECONDS
    ]
    for key in ociosos:
        clients.pop(key, None)
        last_used.pop(key, None)
    return len(ociosos)


async def run_panel_client_purge_reaper(app_state: Any, *, interval_seconds: int = 900) -> None:
    """Laço de limpeza periódica, mesmo padrão de
    `AuthService.run_session_purge_reaper`."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removidos = await purge_idle_panel_clients(app_state)
            if removidos:
                log.info("browser.panel_clients.purge_completed", removed=removidos)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("browser.panel_clients.purge_reaper_iteration_failed", error=str(exc)[:200])


class BrowserActionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    action: Literal["navigate", "click", "type", "screenshot", "content"]
    url: str | None = None
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None
    engine: Literal["auto", "lightpanda", "chromium"] = "auto"


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
                "engine": payload.engine,
                # Painel manual: um humano está olhando, ao contrário do
                # agente (que navega em sequência sem precisar de imagem a
                # cada passo, ver `capture_screenshot` em `ActionRequest` no
                # serviço) — sempre captura em `navigate` (ignorado pelas
                # outras ações).
                "capture_screenshot": payload.action == "navigate",
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
async def close_browser_session(session_id: str, request: Request) -> dict[str, Any]:
    clients: dict[str, BrowserClient] = request.app.state.browser_panel_clients
    client = clients.pop(f"panel-{session_id}", None)
    getattr(request.app.state, "browser_panel_client_last_used", {}).pop(
        f"panel-{session_id}", None
    )
    if client is None:
        # Nenhuma ação foi feita nesta sessão — nada existe do lado do
        # serviço para fechar, então nem vale o DELETE.
        return {"closed": False}
    payload = await client.stop()
    redis = getattr(request.app.state, "redis", None)
    replay = await store_replay(
        blob=getattr(request.app.state, "blob", None),
        redis=redis,
        session_id=session_id,
        project=None,
        payload=payload,
    )
    resultado: dict[str, Any] = {"closed": True, "replay": bool(replay)}
    if not replay and payload and payload.get("expired_by_ttl"):
        # `services/browser` já descartou a sessão por TTL antes deste DELETE
        # chegar (ver `expired_by_ttl` em `close_session`, `services/browser/
        # app.py`) — sem este marcador, `GET /replays/{id}` devolveria um 404
        # indistinguível de "nunca houve replay nesta sessão".
        resultado["replay_lost"] = True
        await mark_replay_expired(redis, session_id)
    return resultado


@router.get("/replays")
async def list_browser_replays(request: Request) -> dict[str, Any]:
    redis = getattr(request.app.state, "redis", None)
    return {"replays": await list_recent_replays(redis)}


@router.get("/replays/{session_id}")
async def get_browser_replay(session_id: str, request: Request) -> dict[str, Any]:
    redis = getattr(request.app.state, "redis", None)
    blob = getattr(request.app.state, "blob", None)
    entrada = await get_replay(redis, session_id)
    if entrada is None:
        if await was_replay_expired(redis, session_id):
            raise HTTPException(
                status.HTTP_410_GONE,
                "sessão expirou por inatividade (30min) antes de ser fechada — replay perdido",
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "replay não encontrado ou expirado")
    if blob is not None:
        if entrada.get("video_key"):
            entrada["video_url"] = await blob.presigned_get_url(entrada["video_key"])
        if entrada.get("trace_key"):
            entrada["trace_url"] = await blob.presigned_get_url(entrada["trace_key"])
    return entrada
