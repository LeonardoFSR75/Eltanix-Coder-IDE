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

import httpx
import structlog

from sicoobito.agent import session_store
from sicoobito.agent.graph import DEFAULT_MAX_ITERATIONS, build_graph
from sicoobito.agent.prompts import build_task_prompt
from sicoobito.agent.state import AgentMode
from sicoobito.agent.tools import ToolContext
from sicoobito.browser.client import BrowserClient, BrowserConfig
from sicoobito.config import Settings
from sicoobito.context.indexer import ContextIndexer
from sicoobito.context.repomap import build_repo_map
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger
from sicoobito.router.engine import RouterEngine
from sicoobito.sandbox.container import SandboxManager, SandboxUnavailableError
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.fs import WorkspaceFS
from sicoobito.workspace.git import GitError
from sicoobito.workspace.github import GitHubClient, GitHubError, parse_remote, resolve_token

log = get_logger(__name__)


def _load_custom_instructions(workspace_root: Path) -> str | None:
    """Lê `.sicoobito/instructions.md` do projeto (não do worktree da sessão)
    — best-effort: arquivo ausente ou erro de leitura não deve impedir a
    sessão de começar, mesmo espírito de degradação graciosa do resto do
    projeto (serviço opcional fora do ar não derruba o essencial)."""
    caminho = workspace_root / ".sicoobito" / "instructions.md"
    try:
        texto = caminho.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("agent.custom_instructions.read_failed", error=str(exc)[:200])
        return None
    return texto or None


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
    # Perfil de roteamento escolhido explicitamente pelo usuário; None mantém a
    # escolha implícita por modo em `_initial_state`.
    profile: str | None = None
    focus_files: list[str] = field(default_factory=list)
    focus_folder: str | None = None


class AgentRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: RouterEngine,
        indexer: ContextIndexer,
        sandboxes: SandboxManager,
        browser_config: BrowserConfig | None = None,
        documents: Any | None = None,  # DocumentService
        notes: Any | None = None,  # NoteService
        skills: Any | None = None,  # SkillService
        audit: Any | None = None,  # AuditService
        trace_recorder: Any | None = None,  # TraceRecorder
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.indexer = indexer
        self.sandboxes = sandboxes
        self.browser_config = browser_config
        self.documents = documents
        self.notes = notes
        self.skills = skills
        self.audit = audit
        self.trace_recorder = trace_recorder
        self._browser_http: httpx.AsyncClient | None = None
        self._sessions: dict[str, AgentSession] = {}
        self._checkpointer: Any | None = None
        # `AsyncPostgresSaver.from_conn_string` é um @asynccontextmanager: a
        # conexão só existe dentro do `async with` que ele abre internamente.
        # `__aenter__()` devolve o saver, mas o gerenciador de contexto em si
        # (o gerador assíncrono) precisa continuar referenciado — sem isto, o
        # GC o finaliza, o que lança `GeneratorExit` no ponto do `yield` e
        # fecha a conexão por baixo, tipicamente no primeiro uso real do
        # checkpointer, com o sintoma "the connection is closed".
        self._checkpointer_cm: Any | None = None

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
            self._checkpointer_cm = AsyncPostgresSaver.from_conn_string(dsn)
            self._checkpointer = await self._checkpointer_cm.__aenter__()
            await self._checkpointer.setup()
            log.info("agent.checkpointer.ready")
        except Exception as exc:
            log.warning("agent.checkpointer.unavailable", error=str(exc)[:200])
            self._checkpointer = None
        return self._checkpointer

    # ── Navegador (Fase 7) ──────────────────────────────────────────────────

    def _get_browser_http(self) -> httpx.AsyncClient:
        if self._browser_http is None or self._browser_http.is_closed:
            self._browser_http = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=30)
            )
        return self._browser_http

    # ── Sessão ──────────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        task: str,
        workspace_root: Path,
        mode: AgentMode = "agent",
        session_id: str | None = None,
        profile: str | None = None,
        focus_files: list[str] | None = None,
        focus_folder: str | None = None,
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
                    log.debug("agent.github.unavailable", error=str(exc))

        # 4. Navegador: opcional, só necessário para a ferramenta de
        # verificação visual. Não testamos a conexão aqui — igual ao sandbox,
        # falha (se falhar) só quando a ferramenta for de fato chamada.
        browser = None
        if self.browser_config is not None:
            browser = BrowserClient(session_id, self.browser_config, self._get_browser_http())

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
            browser=browser,
            documents=self.documents,
            notes=self.notes,
            skills=self.skills,
            audit=self.audit,
            trace_recorder=self.trace_recorder,
            engine=self.engine,
            custom_instructions=_load_custom_instructions(workspace_root),
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
            profile=profile,
            focus_files=focus_files or [],
            focus_folder=focus_folder,
        )
        self._sessions[session_id] = sessao

        # Não-fatal de propósito, mesmo espírito do checkpointer e do sandbox
        # acima: um soluço no banco não pode impedir a criação da sessão, só
        # faz o histórico ficar incompleto para ela.
        try:
            async with session_scope() as db:
                await session_store.create(
                    db,
                    session_id=session_id,
                    project=workspace_root.name,
                    task=task,
                    mode=mode,
                    profile=profile,
                    branch=branch or None,
                    base_branch=base,
                )
        except Exception as exc:
            log.warning("agent.session.persist_failed", session=session_id, error=str(exc)[:200])

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
        if sessao.context.browser is not None:
            await sessao.context.browser.stop()
        if sessao.branch:
            try:
                git_ops.remove_worktree(
                    sessao.workspace_root, session_id, delete_branch=not keep_branch
                )
            except GitError as exc:
                log.warning("agent.session.worktree_cleanup", session=session_id, error=str(exc))
        try:
            async with session_scope() as db:
                await session_store.mark_closed(db, session_id=session_id)
        except Exception as exc:
            log.warning("agent.session.persist_close_failed", session=session_id, error=str(exc)[:200])
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

        prompt_text = build_task_prompt(
            session.task,
            mapa,
            session.mode,
            focus_files=session.focus_files,
            focus_folder=session.focus_folder,
        )

        return {
            "messages": [{"role": "user", "content": prompt_text}],
            "session_id": session.session_id,
            "task": session.task,
            "mode": session.mode,
            # Um perfil escolhido explicitamente sobrescreve a escolha
            # implícita por modo; sem ele, comportamento idêntico ao de antes.
            "model": session.profile or ("coding" if session.mode == "agent" else "auto"),
            "iterations": 0,
            "max_iterations": DEFAULT_MAX_ITERATIONS,
            "finished": False,
            "files_changed": [],
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

    async def aclose(self) -> None:
        """Fecha o cliente HTTP compartilhado do navegador, no desligamento do processo."""
        if self._browser_http is not None and not self._browser_http.is_closed:
            await self._browser_http.aclose()

    async def stream_run(self, session: AgentSession, *, resume: Any = None):
        """Executa o grafo emitindo eventos. Cede o controle na aprovação."""
        # Amarra `session_id` a todo log emitido durante o streaming — uma
        # sessão pode gerar dezenas de spans de ferramentas, e sem isto não
        # há como filtrar só os logs dela sem grep por timestamp aproximado.
        # unbind no finally evita que o valor vaze para outra requisição caso
        # a task ASGI seja reaproveitada ou o generator seja abandonado
        # (cliente desconectou) antes do stream terminar. unbind em vez de
        # clear_contextvars(): esta função roda dentro do contexto já aberto
        # pelo CorrelationIdMiddleware (request_id), que não deve ser apagado
        # daqui.
        structlog.contextvars.bind_contextvars(session_id=session.session_id)
        try:
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
        finally:
            structlog.contextvars.unbind_contextvars("session_id")

    async def get_messages(self, session: AgentSession) -> list[dict[str, Any]]:
        """Mensagens acumuladas no checkpoint — reabre o transcript real de uma
        sessão, em vez de só repetir o texto da tarefa original.

        Sem checkpointer (Postgres indisponível), não há o que devolver: o
        estado do grafo nunca saiu da memória do processo que rodou a sessão.
        """
        compilado = await self._compiled_graph(session)
        if not compilado.checkpointer:
            return []
        config = {"configurable": {"thread_id": session.session_id}}
        estado = await compilado.aget_state(config)
        if estado is None:
            return []
        return _serializable(estado.values.get("messages", []))


def _serializable(valor: Any) -> Any:
    """Torna a atualização segura para JSON, sem quebrar em objeto exótico."""
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)
