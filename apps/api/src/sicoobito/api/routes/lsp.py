"""Rotas do language server: capacidades, ticket e o túnel WebSocket.

O editor abre uma conexão por (projeto, linguagem) e fala LSP puro por ela. A
API não interpreta o protocolo — só autentica, resolve o projeto e traduz
caminhos (ver `lsp/bridge.py`). Manter a ponte burra é deliberado: quando o
`pyright` ganhar um recurso novo, ele funciona sem mudança aqui.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from sicoobito.api.deps import AuthDep
from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore
from sicoobito.config import get_settings
from sicoobito.logging_setup import get_logger
from sicoobito.lsp import LanguageServerProcess, LspError, server_for_language, supported_languages
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/lsp", tags=["lsp"], dependencies=[AuthDep])

# Mesmo motivo da rota do terminal: o browser não envia `Authorization` ao abrir
# um WebSocket. A autenticação desta rota é o ticket de uso único.
ws_router = APIRouter(prefix="/api/lsp", tags=["lsp"])


def _escopo(project: str, language: str) -> str:
    return f"lsp:{project}:{language}"


@router.get("/languages")
async def languages() -> dict[str, Any]:
    """Quais linguagens têm servidor instalado nesta imagem.

    O editor consulta antes de tentar conectar: sem isso ele abriria um
    WebSocket que morre no primeiro byte, para toda linguagem sem servidor.
    """
    return {"languages": supported_languages()}


@router.post("/ticket")
async def ticket(request: Request, project: str, language: str) -> dict[str, Any]:
    if server_for_language(language) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"nenhum language server para '{language}'",
        )

    store: TicketStore | None = getattr(request.app.state, "tickets", None)
    if store is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tickets indisponíveis."
        )
    emitido = await store.issue(_escopo(project, language))
    return {"ticket": emitido, "expires_in": TICKET_TTL_SECONDS}


@ws_router.websocket("/{project}/{language}")
async def lsp_socket(websocket: WebSocket, project: str, language: str) -> None:
    settings = get_settings()

    # Sempre exigido, com ou sem SICOOBITO_API_KEY: o ticket só é emitido por
    # `POST .../ticket`, atrás de `AuthDep` (`require_session`) — ver mesmo
    # ajuste em `workspace.py::terminal`.
    store: TicketStore | None = getattr(websocket.app.state, "tickets", None)
    bilhete = websocket.query_params.get("ticket", "")
    if store is None or not await store.consume(bilhete, _escopo(project, language)):
        log.warning("lsp.rejected", project=project, language=language)
        await websocket.close(code=4401, reason="ticket inválido ou expirado")
        return

    spec = server_for_language(language)
    if spec is None:
        await websocket.close(code=4404, reason=f"sem language server para {language}")
        return

    raiz_projetos = settings.effective_projects_root
    if raiz_projetos is None:
        await websocket.close(code=4400, reason="PROJECTS_ROOT não configurado")
        return

    try:
        raiz = project_ops.resolve(Path(raiz_projetos), project)
    except ProjectError as exc:
        await websocket.close(code=4400, reason=str(exc)[:120])
        return

    servidor = LanguageServerProcess(spec, raiz)
    try:
        await servidor.start()
    except LspError as exc:
        # Aceitar antes de fechar para que o motivo chegue ao editor: uma recusa
        # no handshake vira apenas "connection failed" no console do browser.
        await websocket.accept()
        await websocket.send_json(
            {"jsonrpc": "2.0", "method": "sicoobito/error", "params": str(exc)}
        )
        await websocket.close(code=4503)
        return

    await websocket.accept()
    log.info("lsp.attached", project=project, language=language, server=spec.id)

    async def do_servidor_para_o_editor() -> None:
        while True:
            mensagem = await servidor.receive()
            if mensagem is None:
                break
            await websocket.send_json(mensagem)
        # O processo morreu. Fechar aqui é o que informa o editor: sem isso, o
        # laço de leitura abaixo continuaria aceitando requisições que nunca
        # teriam resposta, e a UI ficaria eternamente "conectando".
        log.warning("lsp.server.exited", project=project, language=language, server=spec.id)
        await websocket.close(code=4503, reason="o language server encerrou")

    bombeador = asyncio.create_task(do_servidor_para_o_editor())
    try:
        while True:
            mensagem = await websocket.receive_json()
            if isinstance(mensagem, dict):
                await servidor.send(mensagem)
    except WebSocketDisconnect:
        log.debug("lsp.disconnected", project=project, language=language)
    except Exception as exc:
        log.warning("lsp.failed", project=project, language=language, error=str(exc))
    finally:
        bombeador.cancel()
        # O processo morre junto com a conexão. É o que garante que fechar o
        # editor não deixa um pyright de 1 GB residente até o próximo reboot.
        await servidor.stop()
