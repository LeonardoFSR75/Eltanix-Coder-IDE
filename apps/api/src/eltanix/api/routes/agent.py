"""Rotas do agente: criar sessão, executar, aprovar, encerrar."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from eltanix.agent import session_store
from eltanix.agent.approval_policy import evaluate_policy
from eltanix.agent.approval_policy_config import load_approval_policy
from eltanix.agent.prompts import compose_system_prompt
from eltanix.agent.runner import AgentRunner, AgentSession
from eltanix.agent.slash_commands import SLASH_COMMANDS
from eltanix.agent.state import AgentMode, PendingApproval
from eltanix.agent.tools import registry
from eltanix.agent.tools.base import ToolContext
from eltanix.agent.tools.diffing import compute_proposed_diff
from eltanix.api.deps import AuthDep, DbSessionDep, EngineDep, SettingsDep
from eltanix.api.sse import SSE_DONE, sse_event
from eltanix.auth.rbac import require_role_by_slug
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.telemetry import flight_recorder
from eltanix.workspace import git as git_ops
from eltanix.workspace import projects as project_ops
from eltanix.workspace.fs import FileTooLargeError, PathEscapeError, WorkspaceFS
from eltanix.workspace.git import GitError
from eltanix.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[AuthDep])


async def _await_or_abandon_on_disconnect[T](request: Request, coro: Awaitable[T]) -> T:
    """Aguarda `coro`, mas cancela se o cliente fechar a conexão no meio.

    A edição inline chama `engine.complete()` fora do grafo — sem isto, um
    Cmd+K cancelado no editor (Esc enquanto "gerando…") deixava a chamada de
    LLM correndo até o fim, gastando tokens por um resultado que ninguém ia
    ler. O adaptador de provedor é httpx por baixo, que aborta a request HTTP
    quando a task é cancelada."""
    task: asyncio.Task[T] = asyncio.ensure_future(coro)

    async def _watch() -> None:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.ensure_future(_watch())
    try:
        return await task
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


def _runner(request: Request) -> AgentRunner:
    runner: AgentRunner | None = getattr(request.app.state, "agent_runner", None)
    if runner is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Agente não inicializado."
        )
    return runner


async def _session(request: Request, session_id: str) -> AgentSession:
    runner = _runner(request)
    sessao = runner.get_session(session_id)
    if sessao is None:
        # Tenta reidratar antes de desistir — cobre o caso comum de sessão
        # que sobreviveu no Postgres a um restart do Docker mas perdeu o
        # runtime em memória (ver `AgentRunner.reconnect_session`).
        sessao = await runner.reconnect_session(session_id)
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


@router.get("/slash-commands")
async def list_slash_commands(response: Response) -> dict[str, Any]:
    """Catálogo de slash commands reconhecidos (Fase 2 do upgrade do agente) —
    fonte única do lado do servidor, consumida pelo autocomplete de
    `AgentChatInput.tsx` (mesmo espírito de `modes.ts` ser fonte única no
    frontend para os 7 modos).

    O catálogo é estático por deploy (uma constante Python), então o
    autocomplete pode cachear por alguns minutos em vez de rebuscar a cada
    tecla `/`."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "commands": [
            {
                "command": c.command,
                "skill_name": c.skill_name,
                "suggested_mode": c.suggested_mode,
                "description": c.description,
            }
            for c in SLASH_COMMANDS.values()
        ]
    }


_INLINE_EDIT_SYSTEM_PROMPT = """Você é um editor de código cirúrgico, chamado a partir de um \
atalho de edição inline (estilo Cmd+K) no editor de um desenvolvedor. Vai receber um trecho de \
código selecionado, o contexto imediatamente antes/depois dele no arquivo, e uma instrução do \
que mudar.

Devolva **apenas** o texto substituto para o trecho selecionado — sem markdown, sem crases \
(```), sem explicação, sem comentário sobre a mudança em si. Preserve a indentação e o estilo \
do trecho original. O texto devolvido substitui exatamente o trecho selecionado, então precisa \
continuar sintaticamente válido encaixado no contexto ao redor."""

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\r?\n(?P<body>.*)\r?\n```\s*$", re.DOTALL)

# Teto de chamadas de `POST /api/agent/inline-edit` por ator por minuto. O
# endpoint chama `engine.complete()` direto, fora do grafo — então não tem o
# teto de iterações do agente, e um loop de Ctrl+K (script, tecla presa,
# retry agressivo do cliente) gastaria LLM sem limite. 20/min dá folga larga
# para uso interativo real e ainda corta uma rajada descontrolada.
_INLINE_EDIT_MAX_PER_MINUTE = 20


async def _guard_inline_edit_rate(request: Request) -> None:
    """`INCR`+`expire` numa janela de 60s por ator (mesmo padrão de
    `AuthService.check_and_register_attempt`). Redis fora do ar → não limita
    (degrada, não derruba — mesma filosofia do resto da plataforma)."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    ator = getattr(request.state, "actor", "unknown")
    try:
        pipe = redis.pipeline()
        pipe.incr(f"agent:inline_edit:ratelimit:{ator}")
        pipe.expire(f"agent:inline_edit:ratelimit:{ator}", 60)
        count, _ = await pipe.execute()
    except Exception as exc:  # degradação intencional: Redis fora não pode barrar a edição
        log.warning("agent.inline_edit.ratelimit_redis_failed", error=str(exc)[:200])
        return
    if int(count) > _INLINE_EDIT_MAX_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Muitas edições inline seguidas (limite {_INLINE_EDIT_MAX_PER_MINUTE}/min). "
            "Aguarde alguns segundos.",
        )


def _strip_fence(texto: str) -> str:
    """Modelos às vezes envolvem a resposta em crases mesmo quando instruídos a
    não fazer isso — melhor tolerar do que devolver a substituição com lixo.

    Ao contrário de `skills/promotion.py::_strip_fence` (que despe JSON e pode
    usar `.strip()` sem dó), o conteúdo aqui é código que vai substituir a
    seleção ao pé da letra: um `.strip()` cego destruiria a indentação inicial
    de uma resposta sem fence (o caso comum), então só o fence em si é
    removido — o corpo entre as crases sai intocado."""
    match = _FENCE_RE.match(texto.strip("\n"))
    return match.group("body") if match else texto


class InlineEditRequest(BaseModel):
    project: str = Field(min_length=1)
    path: str = Field(min_length=1)
    selected_text: str = Field(min_length=1, max_length=20_000)
    instruction: str = Field(min_length=1, max_length=2000)
    context_before: str = Field(default="", max_length=4000)
    context_after: str = Field(default="", max_length=4000)


@router.post("/inline-edit")
async def inline_edit(
    payload: InlineEditRequest, request: Request, settings: SettingsDep, engine: EngineDep
) -> dict[str, Any]:
    """Edição inline (Fase 7 do upgrade do agente, estilo Cmd+K) — fora do
    grafo do LangGraph de propósito: uma seleção pontual não precisa de
    sessão/checkpoint completo, só de uma chamada de LLM isolada (mesmo
    padrão de `agent/review_common.py`) sobre o trecho selecionado.

    Reaproveita `ApprovalPolicy`/`evaluate_policy` já existentes: se o
    caminho editado bate numa regra de auto-aprovação, escreve direto;
    senão, nunca escreve — devolve o diff para o frontend mostrar a barra de
    aceitar/rejeitar (mesmo componente `InlineDiffApprovalBar` já usado para
    revisar o diff de uma sessão do agente).
    """
    await _guard_inline_edit_rate(request)

    raiz = settings.effective_projects_root
    if raiz is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Defina PROJECTS_ROOT para editar arquivos.",
        )
    try:
        root = project_ops.resolve(Path(raiz), payload.project)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    async with session_scope() as session:
        await require_role_by_slug(
            session, request, project_slug=payload.project, min_role="editor"
        )

    fs = WorkspaceFS(root)
    try:
        atual = fs.read(payload.path)
    except (PathEscapeError, FileNotFoundError, FileTooLargeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    atual_norm = atual.replace("\r\n", "\n")
    selecao_norm = payload.selected_text.replace("\r\n", "\n")
    if atual_norm.count(selecao_norm) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A seleção não aparece de forma inequívoca no arquivo atual — "
                "o arquivo pode ter mudado. Recarregue e tente de novo."
            ),
        )

    try:
        resultado = await _await_or_abandon_on_disconnect(
            request,
            engine.complete(
                requested_model="coding",
                params={
                    "messages": [
                        {"role": "system", "content": _INLINE_EDIT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Arquivo: {payload.path}\n\n"
                                f"Contexto antes:\n{payload.context_before}\n\n"
                                f"Trecho selecionado:\n{payload.selected_text}\n\n"
                                f"Contexto depois:\n{payload.context_after}\n\n"
                                f"Instrução: {payload.instruction}"
                            ),
                        },
                    ],
                    "temperature": 0,
                },
                source="ide:inline_edit",
            ),
        )
    except asyncio.CancelledError:
        # Cliente desistiu — nada a devolver, a resposta nem vai ser lida.
        log.info("agent.inline_edit.abandoned", path=payload.path)
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao chamar o modelo: {exc}"
        ) from exc

    escolha = (resultado.payload.get("choices") or [{}])[0]
    novo_texto = _strip_fence((escolha.get("message") or {}).get("content") or "")
    if not novo_texto.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="O modelo não devolveu uma substituição válida.",
        )

    ctx = ToolContext(session_id="inline-edit", workspace_root=root, fs=fs)
    proposto = compute_proposed_diff(
        ctx,
        "edit_file",
        {"path": payload.path, "old_text": payload.selected_text, "new_text": novo_texto},
    )
    if proposto is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível calcular o diff da edição proposta.",
        )

    policy = load_approval_policy(root)
    pending: PendingApproval = {
        "tool_call_id": "inline-edit",
        "tool": "edit_file",
        "risk": "write",
        "arguments": {
            "path": payload.path,
            "old_text": payload.selected_text,
            "new_text": novo_texto,
        },
        "summary": payload.instruction[:200],
    }
    motivo_auto_aprovacao = evaluate_policy(policy, ctx, pending)

    aplicado = motivo_auto_aprovacao is not None
    if aplicado:
        fs.write(payload.path, proposto.after)

    return {
        "path": payload.path,
        "old_text": payload.selected_text,
        "new_text": novo_texto,
        "before": proposto.before,
        "after": proposto.after,
        "diff": proposto.diff,
        "changed_lines": proposto.changed_lines,
        "applied": aplicado,
        "auto_approved_reason": motivo_auto_aprovacao,
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
    images: list[str] = Field(
        default_factory=list, description="Lista de imagens em base64 ou URLs para visão multimodal"
    )


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

    # `payload.project` é nome de pasta em PROJECTS_ROOT, não necessariamente um
    # slug registrado em `ProjectRecord` — `require_role_by_slug` já não faz nada
    # quando o slug não bate com nenhum projeto (mesmo comportamento tolerante
    # usado em documents.py/notes.py para projeto ainda não registrado).
    async with session_scope() as session:
        await require_role_by_slug(
            session, request, project_slug=payload.project, min_role="editor"
        )

    sessao = await _runner(request).create_session(
        task=payload.task,
        workspace_root=root,
        mode=payload.mode,
        profile=payload.profile,
        focus_files=payload.focus_files,
        focus_folder=payload.focus_folder,
        images=payload.images,
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
                "summary": r.summary,
                "status": r.status,
                "total_cost_usd": r.total_cost_usd,
                "total_tokens": r.total_tokens,
                "iterations": r.iterations,
                "pending_approvals": r.pending_approvals,
                "last_failed_call_count": r.last_failed_call_count,
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
    return _session_view(await _session(request, session_id))


@router.get("/sessions/{session_id}/system-prompt")
async def get_session_system_prompt(session_id: str, request: Request) -> dict[str, Any]:
    """Prompt de sistema final da sessão, recomposto pela mesma
    `compose_system_prompt` que `agent/graph.py` usa a cada turno — expõe no
    painel de debug exatamente o que o modelo recebe (base + instruções do
    projeto + especialização + skills roteadas + regras de contexto), sem ter
    que garimpar o log de uma chamada de LLM. `blocks` diz quais adendos
    entraram; `custom_mode_prompt_block` fica de fora de propósito — ele vai no
    prompt da tarefa (`build_task_prompt`), não no de sistema."""
    ctx = (await _session(request, session_id)).context
    blocos = {
        "custom_instructions": ctx.custom_instructions,
        "specialization_prompt": ctx.specialization_prompt,
        "routed_skills_prompt": ctx.routed_skills_prompt,
        "context_rules_prompt": ctx.context_rules_prompt,
    }
    composto = compose_system_prompt(**blocos)
    return {
        "session_id": session_id,
        "system_prompt": composto,
        "length": len(composto),
        "blocks": {nome: bool(valor) for nome, valor in blocos.items()},
    }


@router.get("/sessions/{session_id}/graph")
async def get_session_graph(session_id: str, request: Request) -> dict[str, Any]:
    """Árvore de agentes a partir de `session_id` — mesmo dado que a tool
    `view_agent_graph` do agente vê, exposto como rota para o painel do IDE
    não depender de uma chamada de ferramenta para descobrir se um filho
    está esperando aprovação (ADR 0004: hoje isso só era visível abrindo
    `GET /api/agent/sessions` na mão e notando `parent_session_id`)."""
    coordinator = getattr(request.app.state, "agent_coordinator", None)
    if coordinator is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Orquestração multiagente não inicializada."
        )
    nos = await coordinator.graph_snapshot(session_id)
    return {
        "agents": [
            {
                "session_id": n.session_id,
                "display_name": n.display_name,
                "status": n.status,
                "parent_id": n.parent_id,
                "depth": n.depth,
            }
            for n in nos
        ]
    }


@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(session_id: str, db: DbSessionDep) -> dict[str, Any]:
    """Linha do tempo unificada da sessão — Agent Flight Recorder v1: mescla
    `tool_span` (ferramentas/RAG), `request_log` (chamadas de LLM) e
    `audit_log` (decisões de risco/aprovação) por `created_at`, sem exigir
    três consultas manuais separadas (`GET /api/telemetry/history`,
    `GET /api/metrics/recent`, `GET /api/audit`) para reconstruir "o que o
    agente fez" nesta sessão. Ver `telemetry/flight_recorder.py`."""
    eventos = await flight_recorder.session_timeline(db, session_id=session_id)
    return {
        "session_id": session_id,
        "events": [
            {
                "ts": e.ts.isoformat(),
                "kind": e.kind,
                "summary": e.summary,
                "status": e.status,
                "detail": e.detail,
            }
            for e in eventos
        ],
    }


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


class RunRequest(BaseModel):
    # Mapa de `tool_call_id` para a decisão. Presente apenas ao retomar uma
    # sessão parada em aprovação.
    approvals: dict[str, ApprovalDecision] | None = None
    # Mensagem de acompanhamento enviada pelo usuário para continuar a mesma sessão
    message: str | None = None
    images: list[str] = Field(
        default_factory=list, description="Lista de imagens em base64 ou URLs"
    )


@router.post("/sessions/{session_id}/run")
async def run_session(session_id: str, payload: RunRequest, request: Request):
    """Executa (ou retoma) a sessão, transmitindo eventos por SSE."""
    sessao = await _session(request, session_id)
    runner = _runner(request)

    resume = (
        {call_id: decisao.model_dump() for call_id, decisao in payload.approvals.items()}
        if payload.approvals
        else None
    )

    async def eventos() -> AsyncIterator[str]:
        try:
            async for evento in runner.stream_run(
                sessao, resume=resume, message=payload.message, images=payload.images
            ):
                yield sse_event(evento, default=str, ensure_ascii=False)
        except Exception as exc:
            log.error("agent.run.failed", session=session_id, error=str(exc))
            erro = {"node": "error", "update": {"message": str(exc)}}
            yield sse_event(erro, ensure_ascii=False)
        finally:
            yield SSE_DONE

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request) -> dict[str, Any]:
    """Transcript persistido no checkpoint — permite ao Agent Manager reabrir
    uma sessão e mostrar a conversa real, não só repreencher o campo de tarefa."""
    sessao = await _session(request, session_id)
    mensagens = await _runner(request).get_messages(sessao)
    return {"session_id": session_id, "branch": sessao.branch, "messages": mensagens}


@router.get("/sessions/{session_id}/diff")
async def session_diff(session_id: str, request: Request) -> dict[str, Any]:
    """Diff acumulado no worktree da sessão — o que o humano vai revisar."""
    sessao = await _session(request, session_id)
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


@router.get("/sessions/{session_id}/checkpoints")
async def list_checkpoints(session_id: str, request: Request) -> dict[str, Any]:
    """Pontos de restauração (Fase 8 do upgrade do agente) — um por chamada
    ao modelo (`AgentState["iterations"]`) já concluída nesta sessão."""
    sessao = await _session(request, session_id)
    pontos = await _runner(request).list_checkpoints(sessao)
    return {"checkpoints": pontos}


class RewindRequest(BaseModel):
    iteration: int = Field(ge=0)


@router.post("/sessions/{session_id}/rewind")
async def rewind_session(
    session_id: str, payload: RewindRequest, request: Request
) -> dict[str, Any]:
    """Restaura a sessão para o fim de uma iteração anterior — trunca o
    histórico do grafo e reverte no worktree todo arquivo escrito depois
    dela (Fase 8 do upgrade do agente). Ação explícita e destrutiva do
    usuário: mesmo nível de acesso de `revert_file`/`accept_file`, mas com
    RBAC (o mesmo `min_role="editor"` de `create_session`) porque, ao
    contrário daquelas duas, isto pode reverter várias escritas de uma vez."""
    sessao = await _session(request, session_id)

    async with session_scope() as db:
        await require_role_by_slug(
            db, request, project_slug=sessao.context.project_slug or None, min_role="editor"
        )

    try:
        resultado = await _runner(request).rewind_to(sessao, iteration=payload.iteration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return resultado


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
    sessao = await _session(request, session_id)
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


class AcceptFileRequest(BaseModel):
    path: str = Field(min_length=1)


@router.post("/sessions/{session_id}/files/accept")
async def accept_file(
    session_id: str, payload: AcceptFileRequest, request: Request
) -> dict[str, Any]:
    """Aceita uma edição do agente: copia o arquivo do worktree da sessão para o
    workspace principal do usuário."""
    sessao = await _session(request, session_id)
    try:
        sessao.context.fs.resolve(payload.path)
    except PathEscapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        content = sessao.context.fs.read(payload.path)
    except (PathEscapeError, FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arquivo não encontrado no worktree: {payload.path}",
        ) from exc

    try:
        from eltanix.workspace.fs import WorkspaceFS

        main_fs = WorkspaceFS(sessao.workspace_root)
        written = main_fs.write(payload.path, content)
    except (PathEscapeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"path": payload.path, "accepted": True, "bytes": written}


class CloseRequest(BaseModel):
    # Por padrão o branch fica: descartar o trabalho do agente deve ser uma
    # escolha explícita, não o efeito de fechar uma aba.
    keep_branch: bool = True


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str, payload: CloseRequest, request: Request) -> dict[str, Any]:
    await _session(request, session_id)
    await _runner(request).close_session(session_id, keep_branch=payload.keep_branch)
    return {"session_id": session_id, "closed": True, "branch_kept": payload.keep_branch}


@router.get("/sessions/{session_id}/sandbox/stats")
async def get_session_sandbox_stats(request: Request, session_id: str) -> dict[str, Any]:
    runner = _runner(request)
    if runner.sandboxes is None:
        return {"session_id": session_id, "status": "unavailable", "ports": [], "metrics": {}}
    return await runner.sandboxes.get_stats(session_id)


@router.get("/sessions/{session_id}/sandbox/logs")
async def get_session_sandbox_logs(
    request: Request, session_id: str, tail: int = 100
) -> dict[str, Any]:
    runner = _runner(request)
    if runner.sandboxes is None:
        return {"session_id": session_id, "logs": ""}
    return await runner.sandboxes.get_server_logs(session_id, tail=tail)


@router.get("/sandboxes/queue")
async def get_sandbox_queue_status(request: Request) -> dict[str, Any]:
    """Estado da fila de concorrência de sandbox (Horizonte 3 — ver
    sandbox/concurrency.py). Endpoint de polling: a UI usa isto para mostrar
    posição na fila em vez de a criação de sessão virar um fluxo assíncrono.
    """
    runner = _runner(request)
    if runner.sandboxes is None:
        return {"active": 0, "max_concurrent": 0, "waiting": []}
    return runner.sandboxes.queue_status()


class WebAppToggleRequest(BaseModel):
    enabled: bool = True


@router.post("/sessions/{session_id}/web-app")
async def toggle_session_web_app(
    request: Request, session_id: str, payload: WebAppToggleRequest
) -> dict[str, Any]:
    sessao = await _session(request, session_id)
    sessao.is_web_app = payload.enabled
    prewarmed = False
    if payload.enabled:
        prewarmed = await _runner(request).prewarm_web_app(session_id, force=True)
    else:
        sessao.web_prewarmed = False
    return {
        "session_id": session_id,
        "is_web_app": sessao.is_web_app,
        "web_prewarmed": prewarmed or sessao.web_prewarmed,
    }


def _session_view(sessao: AgentSession) -> dict[str, Any]:
    startup = sessao.context.session_state
    ready_for_search = (
        startup.project_verified
        and startup.workspace_listed
        and startup.packages_checked
        and startup.git_ready
    )
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
        "summary": (
            "Plano em execução"
            if sessao.context.session_state.current_todos
            else "Sessão em execução"
        ),
        "sandbox_available": sessao.sandbox_available,
        "sandbox_error": sessao.sandbox_error,
        "github_available": sessao.context.github is not None,
        "is_web_app": sessao.is_web_app,
        "web_prewarmed": sessao.web_prewarmed,
        "warnings": sessao.warnings,
        "startup_guard": {
            "project_verified": startup.project_verified,
            "workspace_listed": startup.workspace_listed,
            "packages_checked": startup.packages_checked,
            "git_ready": startup.git_ready,
            "ready_for_search": ready_for_search,
        },
    }
