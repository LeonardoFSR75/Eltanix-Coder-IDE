"""Rotas do workspace: projetos, árvore, arquivos, busca e terminal.

Tudo é escopado por projeto. `PROJECTS_ROOT` é a fronteira externa e o
`WorkspaceFS` é a interna — o mesmo usado pelo agente, porque a fronteira de
caminho não pode ter duas implementações.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore
from sicoobito.config import Settings, get_settings
from sicoobito.context.languages import detect_language
from sicoobito.logging_setup import get_logger
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace import search as search_ops
from sicoobito.workspace.fs import FileTooLargeError, PathEscapeError, WorkspaceFS
from sicoobito.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"], dependencies=[AuthDep])
projects_router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[AuthDep])

# O WebSocket vive num router **sem** a dependência de autenticação por header:
# o browser não consegue enviar `Authorization` ao abrir um WebSocket, e a
# dependência rejeitaria toda conexão antes de o ticket ser avaliado. A
# autenticação desta rota é o ticket de uso único.
ws_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

MAX_TREE_ENTRIES = 2000

_CACHE_PREFIX = "sicoobito:files"
# Curto de propósito: arquivos criados fora do IDE aparecem em até um minuto,
# e quem cria por dentro força a atualização com `refresh=true`.
_CACHE_TTL_SECONDS = 60


def _projects_root(settings: Settings) -> Path:
    raiz = settings.effective_projects_root
    if raiz is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Defina PROJECTS_ROOT para usar o editor.",
        )
    return Path(raiz)


def project_fs(settings: SettingsDep, project: str = Query(min_length=1)) -> WorkspaceFS:
    """Resolve o projeto e devolve o acesso a arquivos já delimitado."""
    try:
        caminho = project_ops.resolve(_projects_root(settings), project)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WorkspaceFS(caminho)


FsDep = Annotated[WorkspaceFS, Depends(project_fs)]


def _fs_from_body(settings: Settings, project: str) -> WorkspaceFS:
    try:
        return WorkspaceFS(project_ops.resolve(_projects_root(settings), project))
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _erro_de_caminho(exc: Exception) -> HTTPException:
    if isinstance(exc, PathEscapeError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


class CreateProjectPayload(BaseModel):
    name: str = Field(min_length=1, description="Nome da pasta do projeto")
    git_init: bool = Field(default=False, description="Inicializar repositório Git local")


@projects_router.get("")
async def list_projects(settings: SettingsDep) -> dict[str, Any]:
    raiz = _projects_root(settings)
    projetos = await asyncio.to_thread(project_ops.list_projects, raiz)
    return {
        "root": str(raiz),
        "projects": [
            {"name": p.name, "path": str(p.path), "is_git": p.is_git, "branch": p.branch}
            for p in projetos
        ],
    }


@projects_router.post("")
async def create_project(payload: CreateProjectPayload, settings: SettingsDep) -> dict[str, Any]:
    raiz = _projects_root(settings)
    nome_limpo = project_ops.validate_name(payload.name)
    pasta_destino = raiz / nome_limpo

    try:
        pasta_destino.mkdir(parents=True, exist_ok=True)
        if payload.git_init and not (pasta_destino / ".git").exists():
            import subprocess

            subprocess.run(["git", "init", str(pasta_destino)], check=False, capture_output=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao criar/vincular pasta de projeto: {exc}",
        ) from exc

    eh_git = (pasta_destino / ".git").exists()
    branch = project_ops._branch_of(pasta_destino) if eh_git else None

    return {
        "name": nome_limpo,
        "path": str(pasta_destino),
        "is_git": eh_git,
        "branch": branch,
        "created": True,
    }


class OpenPathPayload(BaseModel):
    path: str = Field(min_length=1, description="Caminho absoluto de qualquer pasta do sistema operacional")


@projects_router.post("/open-path")
async def open_absolute_path(payload: OpenPathPayload) -> dict[str, Any]:
    """Abre e autoriza qualquer pasta do SO como um projeto navegável e inspecionado."""
    from sicoobito.workspace.inspector import ProjectInspector
    from sicoobito.workspace.path_guard import default_path_guard

    alvo = Path(payload.path).resolve()
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )

    # Registra no PathGuard
    default_path_guard.allow(alvo)

    # Inspeciona projeto em <500ms
    inspector = ProjectInspector()
    sig = inspector.inspect(alvo)

    return {
        "name": sig.name,
        "path": sig.path,
        "primary_language": sig.primary_language,
        "frameworks": sig.frameworks,
        "build_system": sig.build_system,
        "has_docker": sig.has_docker,
        "has_git": sig.has_git,
        "has_ci_cd": sig.has_ci_cd,
        "summary": sig.executive_summary,
    }



# ── Árvore e arquivos ───────────────────────────────────────────────────────


@router.get("/tree")
async def tree(fs: FsDep, subpath: str = ".") -> dict[str, Any]:
    """Um nível da árvore. O front expande sob demanda."""
    try:
        entries = await asyncio.to_thread(fs.list_dir, subpath)
    except (PathEscapeError, NotADirectoryError, FileNotFoundError) as exc:
        raise _erro_de_caminho(exc) from exc

    return {
        "subpath": subpath,
        "entries": [
            {
                "path": e.path,
                "name": e.path.rsplit("/", 1)[-1],
                "is_dir": e.is_dir,
                "size_bytes": e.size_bytes,
                "language": None if e.is_dir else detect_language(e.path),
            }
            for e in entries[:MAX_TREE_ENTRIES]
        ],
        "truncated": len(entries) > MAX_TREE_ENTRIES,
    }


@router.get("/files")
async def all_files(fs: FsDep, request: Request, refresh: bool = False) -> dict[str, Any]:
    """Lista plana para o quick open. O casamento fuzzy é feito no cliente.

    O resultado é cacheado porque o custo não está no nosso código: sobre um
    bind mount de Windows para container Linux, cada `stat` cruza a fronteira
    do filesystem e um projeto de mil arquivos leva dezenas de segundos. Um
    quick open que demora meio minuto não é usável; com cache, só a primeira
    abertura paga.
    """
    chave = f"{_CACHE_PREFIX}:{fs.root.as_posix()}"
    redis = getattr(request.app.state, "redis", None)

    if redis is not None and not refresh:
        try:
            bruto = await redis.get(chave)
            if bruto:
                arquivos = json.loads(bruto)
                return {"files": arquivos, "count": len(arquivos), "cached": True}
        except Exception as exc:
            log.warning("workspace.files.cache_unavailable", error=str(exc))

    arquivos = await asyncio.to_thread(search_ops.list_all_files, fs.root)

    if redis is not None:
        try:
            await redis.set(chave, json.dumps(arquivos), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            log.warning("workspace.files.cache_unavailable", error=str(exc))

    return {"files": arquivos, "count": len(arquivos), "cached": False}


@router.get("/file")
async def read_file(fs: FsDep, filepath: str = Query(alias="path")) -> dict[str, Any]:
    try:
        content = await asyncio.to_thread(fs.read, filepath)
    except (PathEscapeError, FileNotFoundError, FileTooLargeError, ValueError) as exc:
        raise _erro_de_caminho(exc) from exc

    return {
        "path": filepath,
        "content": content,
        "language": detect_language(filepath),
        "lines": content.count("\n") + 1,
    }


class WriteFileRequest(BaseModel):
    project: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str


@router.put("/file")
async def write_file(payload: WriteFileRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        written = await asyncio.to_thread(fs.write, payload.path, payload.content)
    except (PathEscapeError, OSError) as exc:
        raise _erro_de_caminho(exc) from exc
    return {"path": payload.path, "bytes": written}


class CreateRequest(BaseModel):
    project: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str = ""
    is_dir: bool = False


@router.post("/file")
async def create_entry(payload: CreateRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        caminho = await asyncio.to_thread(
            fs.create, payload.path, content=payload.content, is_dir=payload.is_dir
        )
    except (PathEscapeError, FileExistsError, OSError) as exc:
        raise _erro_de_caminho(exc) from exc
    return {"path": caminho, "is_dir": payload.is_dir}


class MoveRequest(BaseModel):
    project: str = Field(min_length=1)
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)


@router.post("/move")
async def move_entry(payload: MoveRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        destino = await asyncio.to_thread(fs.move, payload.source, payload.destination)
    except (PathEscapeError, FileNotFoundError, FileExistsError, ValueError, OSError) as exc:
        raise _erro_de_caminho(exc) from exc
    return {"source": payload.source, "destination": destino}


@router.delete("/file")
async def delete_entry(
    fs: FsDep, filepath: str = Query(alias="path"), recursive: bool = False
) -> dict[str, Any]:
    try:
        await asyncio.to_thread(fs.delete, filepath, recursive=recursive)
    except (PathEscapeError, IsADirectoryError, ValueError, OSError) as exc:
        raise _erro_de_caminho(exc) from exc
    return {"path": filepath, "deleted": True}


# ── Busca ───────────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    project: str = Field(min_length=1)
    query: str = Field(min_length=1)
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    path_glob: str | None = None
    max_matches: int = Field(default=search_ops.MAX_MATCHES, ge=1, le=2000)


@router.post("/search")
async def search_text(payload: SearchRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        resultado = await asyncio.to_thread(
            search_ops.search,
            fs.root,
            payload.query,
            regex=payload.regex,
            case_sensitive=payload.case_sensitive,
            whole_word=payload.whole_word,
            path_glob=payload.path_glob,
            max_matches=payload.max_matches,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "matches": [
            {
                "path": m.path,
                "line": m.line,
                "column": m.column,
                "text": m.text,
                "preview": m.preview,
            }
            for m in resultado.matches
        ],
        "files_searched": resultado.files_searched,
        "files_with_matches": resultado.files_with_matches,
        "truncated": resultado.truncated,
    }


class ReplaceRequest(SearchRequest):
    replacement: str
    # Fluxo seguro do editor: o usuário vê os resultados, desmarca o que não
    # quer e confirma. Vazio significa "em todo o projeto".
    only_paths: list[str] | None = None


@router.post("/replace")
async def replace_text(payload: ReplaceRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        resultado = await asyncio.to_thread(
            search_ops.replace_all,
            fs.root,
            payload.query,
            payload.replacement,
            regex=payload.regex,
            case_sensitive=payload.case_sensitive,
            whole_word=payload.whole_word,
            path_glob=payload.path_glob,
            only_paths=payload.only_paths,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "files_changed": resultado.files_changed,
        "replacements": resultado.replacements,
        "changed_paths": resultado.changed_paths,
    }


# ── Terminal ────────────────────────────────────────────────────────────────


@router.post("/terminal/{session_id}/ticket")
async def terminal_ticket(session_id: str, request: Request) -> dict[str, Any]:
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

    Não é um PTY interativo: cada mensagem é um comando completo e a resposta
    volta inteira. Um PTY de verdade exigiria multiplexar o stream do Docker e
    tratar sequências de escape.
    """
    settings = get_settings()

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
                "message": sessao.sandbox_error or "Sandbox indisponível — o executor está no ar?",
            }
        )
        await websocket.close(code=4503)
        return

    await websocket.send_json({"type": "ready", "session_id": session_id, "cwd": "/workspace"})

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
