"""Rotas do workspace: árvore de arquivos, leitura, gravação e terminal.

Todas usam o mesmo `WorkspaceFS` do agente. A fronteira de caminho não pode ter
duas implementações — uma delas acabaria ficando para trás.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore
from sicoobito.config import Settings, get_settings
from sicoobito.context.languages import detect_language
from sicoobito.context.scanner import ALWAYS_IGNORED
from sicoobito.logging_setup import get_logger
from sicoobito.workspace.fs import FileTooLargeError, PathEscapeError, WorkspaceFS

log = get_logger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"], dependencies=[AuthDep])

# O WebSocket vive num router **sem** a dependência de autenticação por header.
# `require_api_key` lê `Authorization`, que o browser não consegue enviar ao
# abrir um WebSocket: a dependência rejeitaria toda conexão antes de o ticket
# ser avaliado, e o handshake morreria sem resposta HTTP válida. A autenticação
# desta rota é o ticket de uso único, verificado dentro do próprio handler.
ws_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# Profundidade máxima da árvore numa única resposta. Repositório grande tem
# dezenas de milhares de arquivos; mandar tudo travaria o browser.
MAX_TREE_ENTRIES = 2000


def _root(settings: Settings, requested: str | None = None) -> Path:
    configured = settings.workspace_root
    if requested is None:
        if configured is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Defina WORKSPACE_ROOT para usar o editor.",
            )
        return Path(configured).resolve()

    candidate = Path(requested).expanduser().resolve()
    if configured is not None and not candidate.is_relative_to(Path(configured).resolve()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Caminho fora de WORKSPACE_ROOT."
        )
    return candidate


@router.get("/tree")
async def tree(
    settings: SettingsDep, path: str | None = None, subpath: str = "."
) -> dict[str, Any]:
    """Lista um nível da árvore. O front expande sob demanda."""
    fs = WorkspaceFS(_root(settings, path))
    try:
        entries = await asyncio.to_thread(fs.list_dir, subpath)
    except (PathEscapeError, NotADirectoryError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "root": str(fs.root),
        "subpath": subpath,
        "entries": [
            {
                "path": entry.path,
                "name": entry.path.rsplit("/", 1)[-1],
                "is_dir": entry.is_dir,
                "size_bytes": entry.size_bytes,
                "language": None if entry.is_dir else detect_language(entry.path),
            }
            for entry in entries[:MAX_TREE_ENTRIES]
        ],
        "truncated": len(entries) > MAX_TREE_ENTRIES,
        "ignored_dirs": sorted(ALWAYS_IGNORED),
    }


@router.get("/file")
async def read_file(
    settings: SettingsDep, filepath: str = Query(alias="path"), root: str | None = None
) -> dict[str, Any]:
    fs = WorkspaceFS(_root(settings, root))
    try:
        content = await asyncio.to_thread(fs.read, filepath)
    except PathEscapeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (FileTooLargeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "path": filepath,
        "content": content,
        "language": detect_language(filepath),
        "lines": content.count("\n") + 1,
    }


class WriteFileRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str
    root: str | None = None


@router.put("/file")
async def write_file(payload: WriteFileRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = WorkspaceFS(_root(settings, payload.root))
    try:
        written = await asyncio.to_thread(fs.write, payload.path, payload.content)
    except PathEscapeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"path": payload.path, "bytes": written}


@router.post("/terminal/{session_id}/ticket")
async def terminal_ticket(session_id: str, request: Request) -> dict[str, Any]:
    """Emite um ticket de uso único para abrir o WebSocket do terminal."""
    store: TicketStore | None = getattr(request.app.state, "tickets", None)
    if store is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tickets indisponíveis."
        )
    ticket = await store.issue(f"terminal:{session_id}")
    return {"ticket": ticket, "expires_in": TICKET_TTL_SECONDS}


@ws_router.websocket("/terminal/{session_id}")
async def terminal(websocket: WebSocket, session_id: str) -> None:
    """Terminal ligado ao sandbox da sessão.

    Não é um PTY interativo: cada mensagem é um comando completo, e a resposta
    volta inteira. Um PTY de verdade exigiria multiplexar o stream do Docker e
    tratar sequências de escape — trabalho que só se paga se o usuário for
    realmente digitar comandos longos aqui, em vez de deixar o agente executar.
    """
    settings = get_settings()

    # O browser não permite header customizado ao abrir um WebSocket, então a
    # credencial iria na query string — que aparece em log, histórico e Referer.
    # Por isso vai um ticket de uso único, não a chave principal.
    if settings.api_key:
        store: TicketStore | None = getattr(websocket.app.state, "tickets", None)
        ticket = websocket.query_params.get("ticket", "")
        if store is None or not await store.consume(ticket, f"terminal:{session_id}"):
            log.warning("workspace.terminal.rejected", session=session_id)
            await websocket.close(code=4401, reason="ticket inválido ou expirado")
            return

    await websocket.accept()

    runner = getattr(websocket.app.state, "agent_runner", None)
    sessao = runner.get_session(session_id) if runner else None
    if sessao is None:
        await websocket.send_json({"type": "error", "message": f"sessão {session_id} não existe"})
        await websocket.close(code=4404)
        return

    sandbox = sessao.context.sandbox
    if sandbox is None:
        await websocket.send_json(
            {
                "type": "error",
                "message": sessao.sandbox_error or "Sandbox indisponível — o Docker está rodando?",
            }
        )
        await websocket.close(code=4503)
        return

    await websocket.send_json(
        {"type": "ready", "session_id": session_id, "cwd": "/workspace"}
    )

    try:
        while True:
            mensagem = await websocket.receive_json()
            comando = (mensagem or {}).get("command", "").strip()
            if not comando:
                continue

            await websocket.send_json({"type": "started", "command": comando})
            resultado = await sandbox.exec(comando)
            await websocket.send_json(
                {
                    "type": "output",
                    "command": comando,
                    "stdout": resultado.stdout,
                    "stderr": resultado.stderr,
                    "exit_code": resultado.exit_code,
                    "duration_ms": resultado.duration_ms,
                    "timed_out": resultado.timed_out,
                }
            )
    except WebSocketDisconnect:
        log.debug("workspace.terminal.disconnected", session=session_id)
    except Exception as exc:
        log.warning("workspace.terminal.failed", session=session_id, error=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
