"""Sessões do agente: montagem, execução e retomada.

Uma sessão amarra quatro coisas de tempos de vida diferentes: o worktree Git
(sobrevive ao processo), o container do sandbox (sobrevive a um reload), o
checkpoint do grafo (no Postgres) e o contexto de ferramentas (em memória).
Ao retomar uma sessão, os três primeiros são reaproveitados e o quarto é
remontado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sicoobito.agent.graph import DEFAULT_MAX_ITERATIONS, build_graph
from sicoobito.agent.prompts import build_task_prompt
from sicoobito.agent.state import AgentMode
from sicoobito.agent.tools import ToolContext
from sicoobito.config import Settings
from sicoobito.context.indexer import ContextIndexer
from sicoobito.context.repomap import build_repo_map
from sicoobito.logging_setup import get_logger
from sicoobito.router.engine import RouterEngine
from sicoobito.sandbox.container import SandboxManager, SandboxUnavailableError
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.fs import WorkspaceFS
from sicoobito.workspace.git import GitError
from sicoobito.workspace.github import GitHubClient, GitHubError, parse_remote, resolve_token

log = get_logger(__name__)


@dataclass(slots=True)
class AgentSession:
    session_id: str
    workspace_root: Path
    worktree_path: Path
    branch: str
    base_branch: str
    mode: AgentMode
    task: str
    context: ToolContext
    sandbox_available: bool = False
    sandbox_error: str | None = None
    warnings: list[str] = field(default_factory=list)


class AgentRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: RouterEngine,
        indexer: ContextIndexer,
        sandboxes: SandboxManager,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.indexer = indexer
        self.sandboxes = sandboxes
        self._sessions: dict[str, AgentSession] = {}
        self._checkpointer: Any | None = None

    # ── Checkpointer ────────────────────────────────────────────────────────

    async def checkpointer(self):
        """Checkpointer no Postgres, criado sob demanda.

        Sem ele o grafo ainda roda, mas a sessão não sobrevive a um reload e a
        aprovação humana teria de acontecer na mesma requisição.
        """
        if self._checkpointer is not None:
            return self._checkpointer
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # O checkpointer fala psycopg; a URL do SQLAlchemy usa asyncpg.
            dsn = self.settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            saver = AsyncPostgresSaver.from_conn_string(dsn)
            self._checkpointer = await saver.__aenter__()
            await self._checkpointer.setup()
            log.info("agent.checkpointer.ready")
        except Exception as exc:
            log.warning("agent.checkpointer.unavailable", error=str(exc)[:200])
            self._checkpointer = None
        return self._checkpointer

    # ── Sessão ──────────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        task: str,
        workspace_root: Path,
        mode: AgentMode = "agent",
        session_id: str | None = None,
    ) -> AgentSession:
        session_id = session_id or self.sandboxes.new_session_id()
        # Syscall única na criação da sessão; o trabalho pesado de disco desta
        # função (worktree, sandbox) já roda fora do event loop.
        workspace_root = workspace_root.resolve()  # noqa: ASYNC240
        avisos: list[str] = []

        # 1. Worktree: o agente nunca trabalha na árvore que você está editando.
        try:
            worktree = git_ops.create_worktree(workspace_root, session_id)
            worktree_path, branch, base = worktree.path, worktree.branch, worktree.base_branch
        except GitError as exc:
            # Sem Git, o agente ainda serve para ler e editar — perde só o
            # isolamento e a possibilidade de PR.
            avisos.append(f"sem worktree Git: {exc}")
            worktree_path, branch, base = workspace_root, "", "main"

        # 2. Sandbox: sem ele, ferramentas de execução se recusam a rodar.
        sandbox = None
        sandbox_error: str | None = None
        try:
            sandbox = await self.sandboxes.acquire(session_id, worktree_path)
        except SandboxUnavailableError as exc:
            sandbox_error = str(exc)
            avisos.append(sandbox_error)

        # 3. GitHub: opcional, só necessário para abrir PR e ler issue.
        github = None
        repo_ref = None
        token = resolve_token(self.settings.github_token)
        if token:
            url = git_ops.remote_url(workspace_root) if branch else None
            repo_ref = parse_remote(url) if url else None
            if repo_ref is not None:
                try:
                    github = GitHubClient(token)
                except GitHubError as exc:
                    avisos.append(str(exc))

        contexto = ToolContext(
            session_id=session_id,
            workspace_root=worktree_path,
            fs=WorkspaceFS(worktree_path),
            sandbox=sandbox,
            indexer=self.indexer,
            github=github,
            repo_ref=repo_ref,
            base_branch=base,
            branch=branch,
        )

        sessao = AgentSession(
            session_id=session_id,
            workspace_root=workspace_root,
            worktree_path=worktree_path,
            branch=branch,
            base_branch=base,
            mode=mode,
            task=task,
            context=contexto,
            sandbox_available=sandbox is not None,
            sandbox_error=sandbox_error,
            warnings=avisos,
        )
        self._sessions[session_id] = sessao

        log.info(
            "agent.session.created",
            session=session_id,
            mode=mode,
            branch=branch or "(sem branch)",
            sandbox=sessao.sandbox_available,
            github=github is not None,
        )
        return sessao

    def get_session(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str, *, keep_branch: bool = True) -> None:
        sessao = self._sessions.pop(session_id, None)
        if sessao is None:
            return
        await self.sandboxes.release(session_id)
        if sessao.branch:
            try:
                git_ops.remove_worktree(
                    sessao.workspace_root, session_id, delete_branch=not keep_branch
                )
            except GitError as exc:
                log.warning("agent.session.worktree_cleanup", session=session_id, error=str(exc))
        log.info("agent.session.closed", session=session_id)

    # ── Execução ────────────────────────────────────────────────────────────

    async def _compiled_graph(self, session: AgentSession):
        grafo = build_graph(self.engine, session.context)
        checkpointer = await self.checkpointer()
        return grafo.compile(checkpointer=checkpointer) if checkpointer else grafo.compile()

    async def _initial_state(self, session: AgentSession) -> dict[str, Any]:
        mapa = None
        try:
            resultado = await build_repo_map(
                self.indexer.workspace_key(session.workspace_root), token_budget=1500
            )
            mapa = resultado.get("text") or None
        except Exception as exc:
            log.debug("agent.repomap.unavailable", error=str(exc)[:200])

        return {
            "messages": [{"role": "user", "content": build_task_prompt(session.task, mapa)}],
            "session_id": session.session_id,
            "task": session.task,
            "mode": session.mode,
            "model": "coding" if session.mode == "agent" else "auto",
            "iterations": 0,
            "max_iterations": DEFAULT_MAX_ITERATIONS,
            "finished": False,
            "files_changed": [],
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

    async def stream_run(self, session: AgentSession, *, resume: Any = None):
        """Executa o grafo emitindo eventos. Cede o controle na aprovação."""
        compilado = await self._compiled_graph(session)
        config = {"configurable": {"thread_id": session.session_id}}

        if resume is not None:
            from langgraph.types import Command

            entrada: Any = Command(resume=resume)
        else:
            entrada = await self._initial_state(session)

        async for evento in compilado.astream(entrada, config=config, stream_mode="updates"):
            for no, atualizacao in evento.items():
                yield {"node": no, "update": _serializable(atualizacao)}

        estado = await compilado.aget_state(config) if compilado.checkpointer else None
        if estado is not None and estado.tasks:
            # Grafo parado numa interrupção: há aprovação pendente.
            for tarefa in estado.tasks:
                for interrupcao in getattr(tarefa, "interrupts", []) or []:
                    yield {"node": "interrupt", "update": _serializable(interrupcao.value)}


def _serializable(valor: Any) -> Any:
    """Torna a atualização segura para JSON, sem quebrar em objeto exótico."""
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)
