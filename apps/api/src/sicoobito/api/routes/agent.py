"""Rotas do agente: criar sessão, executar, aprovar, encerrar."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sicoobito.agent import session_store
from sicoobito.agent.runner import AgentRunner, AgentSession
from sicoobito.agent.state import AgentMode
from sicoobito.agent.tools import registry
from sicoobito.api.deps import AuthDep, DbSessionDep, EngineDep, SettingsDep
from sicoobito.logging_setup import get_logger
from sicoobito.workspace import git as git_ops
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.fs import PathEscapeError
from sicoobito.workspace.git import GitError
from sicoobito.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[AuthDep])


def _runner(request: Request) -> AgentRunner:
    runner: AgentRunner | None = getattr(request.app.state, "agent_runner", None)
    if runner is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Agente não inicializado."
        )
    return runner


def _session(request: Request, session_id: str) -> AgentSession:
    sessao = _runner(request).get_session(session_id)
    if sessao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sessão desconhecida: {session_id}. Ela pode ter expirado com o reinício.",
        )
    return sessao


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """Catálogo de ferramentas e suas classes de risco."""
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "risk": str(tool.risk),
                "requires_approval": tool.risk.requires_approval,
            }
            for tool in registry.all()
        ]
    }


class CreateSessionRequest(BaseModel):
    task: str = Field(min_length=1, description="O que o agente deve fazer")
    project: str = Field(min_length=1, description="Nome do projeto em PROJECTS_ROOT")
    mode: AgentMode = "agent"
    # Perfil de roteamento (config/routes.yaml). None mantém a escolha
    # implícita por modo — não é Literal porque os perfis são definidos em
    # YAML, e um Literal fixo aqui ficaria defasado sozinho.
    profile: str | None = None
    focus_files: list[str] = Field(
        default_factory=list, description="Lista de arquivos para focar/editar"
    )
    focus_folder: str | None = Field(default=None, description="Pasta do projeto para focar")


@router.post("/sessions")
async def create_session(
    payload: CreateSessionRequest, request: Request, settings: SettingsDep, engine: EngineDep
) -> dict[str, Any]:
    raiz = settings.effective_projects_root
    if raiz is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Defina PROJECTS_ROOT para criar sessões de agente.",
        )
    if payload.profile is not None:
        # `embedding` existe no catálogo mas não é perfil de chat/codificação.
        if payload.profile == "embedding" or (
            payload.profile not in engine.catalog.profiles
            and payload.profile not in engine.catalog.models
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Perfil desconhecido: {payload.profile}",
            )
    try:
        # Só nome de projeto, nunca caminho: é o que impede o agente de ser
        # apontado para qualquer diretório da máquina.
        root = project_ops.resolve(Path(raiz), payload.project)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    sessao = await _runner(request).create_session(
        task=payload.task,
        workspace_root=root,
        mode=payload.mode,
        profile=payload.profile,
        focus_files=payload.focus_files,
        focus_folder=payload.focus_folder,
    )
    return _session_view(sessao)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    db: DbSessionDep,
    project: str | None = None,
    status_filtro: Literal["open", "closed", "all"] = "all",
    parent_session_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Histórico persistido, para a lista de sessões do painel sobreviver a um restart."""
    runner = _runner(request)
    registros = await session_store.list_sessions(
        db,
        project=project,
        status=None if status_filtro == "all" else status_filtro,
        parent_session_id=parent_session_id,
        limit=limit,
    )
    return {
        "sessions": [
            {
                "session_id": r.session_id,
                "project": r.project,
                "task": r.task,
                "mode": r.mode,
                "profile": r.profile,
                "branch": r.branch,
                "status": r.status,
                # Preenchido só pra sessões criadas via `spawn_agent`
                # (orquestração multiagente, ver ADR 0004) — `None` pra
                # qualquer sessão raiz.
                "parent_session_id": r.parent_session_id,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                # Único jeito confiável de saber se ainda está rodando neste
                # processo: `status` só reflete close_session() explícito, e
                # uma aba fechada sem isso fica "open" pra sempre no banco.
                "live": runner.get_session(r.session_id) is not None,
            }
            for r in registros
        ]
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict[str, Any]:
    return _session_view(_session(request, session_id))


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


class RunRequest(BaseModel):
    # Mapa de `tool_call_id` para a decisão. Presente apenas ao retomar uma
    # sessão parada em aprovação.
    approvals: dict[str, ApprovalDecision] | None = None
    # Mensagem de acompanhamento enviada pelo usuário para continuar a mesma sessão
    message: str | None = None


@router.post("/sessions/{session_id}/run")
async def run_session(session_id: str, payload: RunRequest, request: Request):
    """Executa (ou retoma) a sessão, transmitindo eventos por SSE."""
    sessao = _session(request, session_id)
    runner = _runner(request)

    resume = (
        {call_id: decisao.model_dump() for call_id, decisao in payload.approvals.items()}
        if payload.approvals
        else None
    )

    async def eventos() -> AsyncIterator[str]:
        try:
            async for evento in runner.stream_run(sessao, resume=resume, message=payload.message):
                yield f"data: {json.dumps(evento, default=str, ensure_ascii=False)}\n\n"
        except Exception as exc:
            log.error("agent.run.failed", session=session_id, error=str(exc))
            erro = {"node": "error", "update": {"message": str(exc)}}
            yield f"data: {json.dumps(erro, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request) -> dict[str, Any]:
    """Transcript persistido no checkpoint — permite ao Agent Manager reabrir
    uma sessão e mostrar a conversa real, não só repreencher o campo de tarefa."""
    sessao = _session(request, session_id)
    mensagens = await _runner(request).get_messages(sessao)
    return {"session_id": session_id, "branch": sessao.branch, "messages": mensagens}


@router.get("/sessions/{session_id}/diff")
async def session_diff(session_id: str, request: Request) -> dict[str, Any]:
    """Diff acumulado no worktree da sessão — o que o humano vai revisar."""
    sessao = _session(request, session_id)
    try:
        estado = git_ops.status(sessao.worktree_path)
        diff = git_ops.diff(sessao.worktree_path)
    except GitError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "branch": estado.branch,
        "dirty": estado.dirty,
        "files": [{"path": f.path, "status": f.status} for f in estado.files],
        "diff": diff,
    }


class RevertFileRequest(BaseModel):
    path: str = Field(min_length=1)
    # O conteúdo anterior já está no card de diff no frontend (a ferramenta
    # devolveu `before`/`existed` em `ToolResult.data`) — reenviá-lo aqui
    # evita depender de git para reverter. Muitos projetos abertos no IDE nem
    # são repositório Git (a sessão ainda funciona para ler/editar sem isso,
    # ver `AgentRunner.create_session`), e a versão anterior desta rota
    # (`git checkout HEAD --`) simplesmente não tinha para onde reverter
    # nesse caso — o clique em "Rejeitar" falhava sempre.
    before: str = ""
    existed: bool = True


@router.post("/sessions/{session_id}/files/revert")
async def revert_file(
    session_id: str, payload: RevertFileRequest, request: Request
) -> dict[str, Any]:
    """Rejeita uma edição do agente: devolve o arquivo ao conteúdo anterior no
    worktree da sessão (ou remove, se a ferramenta o criou). É o lado
    'Rejeitar' do card de diff — aceitar não precisa de rota nenhuma, a
    mudança já está gravada."""
    sessao = _session(request, session_id)
    try:
        # Mesma fronteira de path-escape usada pelas ferramentas do agente:
        # o path vem de um card do frontend, mas confiar cegamente nele
        # abriria a mesma classe de furo que os tools de arquivo já fecham.
        sessao.context.fs.resolve(payload.path)
    except PathEscapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        if payload.existed:
            sessao.context.fs.write(payload.path, payload.before)
        else:
            sessao.context.fs.delete(payload.path)
    except (PathEscapeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"path": payload.path, "reverted": True}


class CloseRequest(BaseModel):
    # Por padrão o branch fica: descartar o trabalho do agente deve ser uma
    # escolha explícita, não o efeito de fechar uma aba.
    keep_branch: bool = True


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str, payload: CloseRequest, request: Request) -> dict[str, Any]:
    _session(request, session_id)
    await _runner(request).close_session(session_id, keep_branch=payload.keep_branch)
    return {"session_id": session_id, "closed": True, "branch_kept": payload.keep_branch}


def _session_view(sessao: AgentSession) -> dict[str, Any]:
    return {
        "session_id": sessao.session_id,
        "mode": sessao.mode,
        "profile": sessao.profile,
        "model": sessao.profile or ("coding" if sessao.mode == "agent" else "auto"),
        "task": sessao.task,
        "workspace_root": str(sessao.workspace_root),
        "worktree_path": str(sessao.worktree_path),
        "branch": sessao.branch,
        "base_branch": sessao.base_branch,
        "sandbox_available": sessao.sandbox_available,
        "sandbox_error": sessao.sandbox_error,
        "github_available": sessao.context.github is not None,
        "warnings": sessao.warnings,
    }
