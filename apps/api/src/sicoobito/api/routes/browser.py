"""Rota de navegador manual — painel dedicado no IDE, fora do fluxo do agente.

Reaproveita o mesmo serviço isolado (`services/browser`) e `BrowserClient` que
a ferramenta `browser_action` do agente usa (`browser/client.py`), mas aqui a
sessão pertence ao painel que o usuário abriu no IDE, não a uma execução do
agente: sem `RiskClass`, sem aprovação humana no grafo — o usuário já está no
controle direto do navegador, o mesmo raciocínio por trás do Terminal do IDE
não pedir aprovação a cada comando digitado.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.browser.client import (
    BrowserClient,
    BrowserConfig,
    BrowserError,
    BrowserUnavailableError,
)

router = APIRouter(prefix="/api/browser", tags=["browser"], dependencies=[AuthDep])


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
