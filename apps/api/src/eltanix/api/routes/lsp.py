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

from eltanix.api.deps import AuthDep
from eltanix.api.tickets import TICKET_TTL_SECONDS, TicketStore
from eltanix.config import get_settings
from eltanix.extensions.manager import get_extensions_manager
from eltanix.logging_setup import get_logger
from eltanix.lsp import (
    LanguageServerProcess,
    LspError,
    extension_for_server,
    server_for_language,
    supported_languages,
)
from eltanix.workspace import projects as project_ops
from eltanix.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/lsp", tags=["lsp"], dependencies=[AuthDep])

# Mesmo motivo da rota do terminal: o browser não envia `Authorization` ao abrir
# um WebSocket. A autenticação desta rota é o ticket de uso único.
ws_router = APIRouter(prefix="/api/lsp", tags=["lsp"])


def _escopo(project: str, language: str) -> str:
    return f"lsp:{project}:{language}"


@router.get("/languages")
async def languages() -> dict[str, Any]:
    """Quais linguagens têm servidor instalado nesta imagem."""
    return {"languages": supported_languages()}


@router.get("/extensions")
async def extensions() -> dict[str, Any]:
    """Lista as extensões e suítes ativas na IDE agêntica através do ExtensionsManager."""
    return get_extensions_manager().get_catalog()


def _blocked_by_extension(spec_id: str) -> str | None:
    """`None` se o servidor pode subir; senão o id da extensão desligada que
    o está bloqueando (ver `lsp/extension_bridge.py`)."""
    ext_id = extension_for_server(spec_id)
    if ext_id is None:
        return None
    if get_extensions_manager().is_active(ext_id):
        return None
    return ext_id


@router.post("/ticket")
async def ticket(
    request: Request, project: str, language: str, server: str | None = None
) -> dict[str, Any]:
    spec = server_for_language(language, preferred_server=server)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"nenhum language server para '{language}'",
        )
    bloqueio = _blocked_by_extension(spec.id)
    if bloqueio is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"extensão '{bloqueio}' está desativada — "
                f"ligue-a no painel de Extensões para usar '{spec.id}'"
            ),
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

    # Sempre exigido, com ou sem ELTANIX_API_KEY: o ticket só é emitido por
    # `POST .../ticket`, atrás de `AuthDep` (`require_session`) — ver mesmo
    # ajuste em `workspace.py::terminal`.
    store: TicketStore | None = getattr(websocket.app.state, "tickets", None)
    bilhete = websocket.query_params.get("ticket", "")
    server_pref = websocket.query_params.get("server", None)
    if store is None or not await store.consume(bilhete, _escopo(project, language)):
        log.warning("lsp.rejected", project=project, language=language)
        await websocket.close(code=4401, reason="ticket inválido ou expirado")
        return

    spec = server_for_language(language, preferred_server=server_pref)
    if spec is None:
        await websocket.close(code=4404, reason=f"sem language server para {language}")
        return

    bloqueio = _blocked_by_extension(spec.id)
    if bloqueio is not None:
        await websocket.close(code=4403, reason=f"extensão '{bloqueio}' está desativada")
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
        await websocket.send_json({"jsonrpc": "2.0", "method": "eltanix/error", "params": str(exc)})
        await websocket.close(code=4503)
        return

    # `servidor.start()` já subiu o processo do language server (pyright,
    # tsserver — centenas de MB) neste ponto. Se `accept()` ou a criação da
    # task de bombeamento falharem agora (cliente desconectou bem nessa
    # janela, por exemplo), nada mais chamaria `servidor.stop()`: o `finally`
    # do laço de mensagens abaixo só existe DEPOIS destas duas linhas — sem
    # este try/except o processo vazava como zumbi até o restart da API.
    try:
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
    except Exception:
        await servidor.stop()
        raise

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
