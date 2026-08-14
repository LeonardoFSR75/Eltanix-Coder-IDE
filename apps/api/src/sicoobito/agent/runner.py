"""Sessões do agente: montagem, execução e retomada.

Uma sessão amarra quatro coisas de tempos de vida diferentes: o worktree Git
(sobrevive ao processo), o container do sandbox (sobrevive a um reload), o
checkpoint do grafo (no Postgres) e o contexto de ferramentas (em memória).
Ao retomar uma sessão, os três primeiros são reaproveitados e o quarto é
remontado.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sicoobito.audit.service import AuditService
    from sicoobito.documents.service import DocumentService
    from sicoobito.notes.service import NoteService
    from sicoobito.skills.service import SkillService
    from sicoobito.telemetry.tracer import TraceRecorder

import httpx
import structlog

from sicoobito.agent import session_store
from sicoobito.agent.approval_policy_config import load_approval_policy
from sicoobito.agent.coordinator import AgentCoordinator
from sicoobito.agent.graph import DEFAULT_MAX_ITERATIONS, build_graph


def _session_summary(session: AgentSession, *, pending_count: int = 0, failed_count: int = 0) -> str:
    """Resumo leve da sessão usado na UI e no histórico.

    Mantém o texto curto e legível — o objetivo é informar rapidamente se a
    execução está aguardando aprovação, se houve falha recorrente ou se a
    sessão está em progresso, sem exigir abrir o transcript completo.
    """
    if pending_count > 0:
        base = f"Aguardando aprovação de {pending_count} ação(ões)"
    elif failed_count > 0:
        base = f"Falha recorrente em {failed_count} chamada(s)"
    else:
        base = "Executando"

    if session.branch:
        return f"{base} em {session.branch}"
    return base
from sicoobito.agent.headless import run_headless_burst
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
from sicoobito.security.service import SecureBertService
from sicoobito.sandbox.container import SandboxManager, SandboxUnavailableError
from sicoobito.workspace import git as git_ops
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.fs import WorkspaceFS
from sicoobito.workspace.git import GitError
from sicoobito.workspace.github import GitHubClient, GitHubError, parse_remote, resolve_token
from sicoobito.workspace.projects import ProjectError

log = get_logger(__name__)


async def validate_project_runtime(workspace_root: Path) -> dict[str, Any]:
    """Valida o projeto antes do início da sessão do agente.

    A sessão só pode começar depois de confirmar que o diretório do projeto foi
    conectado, que a árvore de arquivos foi listada, que o ecossistema/deps do
    projeto foi detectado e que um repositório Git válido existe. Quando o
    projeto ainda não foi inicializado como Git, o runtime o cria antes de
    permitir a sessão avançar.
    """
    try:
        git_ops.ensure_repo(workspace_root)
    except GitError as exc:
        return {
            "project_ok": False,
            "reason": f"não foi possível garantir o Git do projeto: {exc}",
            "files": [],
            "ecosystem": "unknown",
            "manifest_name": None,
        }

    try:
        entries = sorted(p.name for p in workspace_root.iterdir())
    except OSError as exc:
        return {
            "project_ok": False,
            "reason": f"não foi possível listar o projeto: {exc}",
            "files": [],
            "ecosystem": "unknown",
            "manifest_name": None,
            "git_ready": False,
        }

    from sicoobito.api.routes.packages import detect_ecosystem, get_manifest_name

    eco = detect_ecosystem(workspace_root)
    manifest_name = get_manifest_name(eco)

    return {
        "project_ok": True,
        "reason": None,
        "files": entries,
        "ecosystem": eco,
        "manifest_name": manifest_name,
        "git_ready": True,
    }


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
        documents: DocumentService | None = None,
        notes: NoteService | None = None,
        skills: SkillService | None = None,
        audit: AuditService | None = None,
        trace_recorder: TraceRecorder | None = None,
        coordinator: AgentCoordinator | None = None,
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
        # None quando o Redis não está configurado — orquestração multiagente
        # fica indisponível (`spawn_agent` falha fechado), mas sessões normais
        # seguem intactas (ver ADR 0004).
        self.coordinator = coordinator
        self._browser_http: httpx.AsyncClient | None = None
        self._sessions: dict[str, AgentSession] = {}
        # Um lock por sessão evita que duas chamadas concorrentes a
        # `stream_run` (retry de rede, duplo clique, aba duplicada) retomem o
        # mesmo checkpoint em paralelo e executem a mesma ferramenta
        # WRITE/EXEC já aprovada duas vezes. `is_being_driven()` reaproveita
        # esse mesmo lock como sinal de "alguém já está avançando esta sessão"
        # — ver `send_message_to_agent` em `agent/tools/agents_graph.py`.
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Bursts headless disparados por `spawn_agent`/mensagens que acordam
        # um filho parado — precisam de referência viva (senão o GC cancela a
        # task no meio) e de rastreamento pra `aclose()` conseguir esperar/
        # cancelar no shutdown. Mesmo idioma de `telemetry/tracer.py::TraceRecorder`.
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._checkpointer: Any | None = None
        # `AsyncPostgresSaver.from_conn_string` é um @asynccontextmanager: a
        # conexão só existe dentro do `async with` que ele abre internamente.
        # `__aenter__()` devolve o saver, mas o gerenciador de contexto em si
        # (o gerador assíncrono) precisa continuar referenciado — sem isto, o
        # GC o finaliza, o que lança `GeneratorExit` no ponto do `yield` e
        # fecha a conexão por baixo, tipicamente no primeiro uso real do
        # checkpointer, com o sintoma "the connection is closed".
        self._checkpointer_cm: Any | None = None

    def is_being_driven(self, session_id: str) -> bool:
        """True se algum `stream_run()` (humano via SSE, ou um burst headless)
        já está avançando esta sessão agora. `send_message_to_agent` usa isto
        pra decidir se precisa disparar um burst novo pra acordar o alvo, ou
        se quem já está dirigindo a sessão vai naturalmente drenar a inbox."""
        lock = self._session_locks.get(session_id)
        return lock is not None and lock.locked()

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
        parent_session_id: str | None = None,
    ) -> AgentSession:
        session_id = session_id or self.sandboxes.new_session_id()
        workspace_root = workspace_root.resolve()  # noqa: ASYNC240
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise ValueError(f"Projeto não existe em PROJECTS_ROOT: {workspace_root}")

        runtime_validation = await validate_project_runtime(workspace_root)
        if not runtime_validation["project_ok"]:
            raise ValueError(runtime_validation["reason"])

        # Garante o ambiente de pacotes (.venv, node_modules, etc) no projeto raiz antes de criar o worktree
        try:
            from sicoobito.api.routes.packages import ensure_project_env

            await ensure_project_env(workspace_root)
        except Exception as exc:
            log.warning("runner.ensure_project_env.failed", project=workspace_root.name, error=str(exc))

        avisos: list[str] = [
            (
                f"Projeto conectado: {len(runtime_validation['files'])} item(ns) no workspace. "
                f"Ecossistema detectado: {runtime_validation['ecosystem']}"
            )
        ]

        # 1. Worktree: o agente nunca trabalha na árvore que você está editando.
        try:
            worktree = git_ops.create_worktree(workspace_root, session_id)
            worktree_path, branch, base = worktree.path, worktree.branch, worktree.base_branch
        except GitError as exc:
            # Sem Git, o agente ainda serve para ler e editar — perde só o
            # isolamento e a possibilidade de PR.
            avisos.append(f"sem worktree Git: {exc}")
            worktree_path, branch, base = workspace_root, "", "main"

        # 1b. Aviso de arquivos não commitados: o worktree acima só materializa
        # o que está commitado na branch — um arquivo untracked no checkout do
        # usuário fica invisível pro agente, sem nenhum sinal na UI (achado real
        # de teste: import quebrado em silêncio porque o módulo nunca tinha sido
        # commitado). Melhor esforço — falha aqui não impede a sessão.
        if branch:
            try:
                ignored_prefixes = (
                    ".venv/",
                    ".venv\\",
                    "node_modules/",
                    "node_modules\\",
                    "vendor/",
                    "vendor\\",
                    "__pycache__/",
                    "__pycache__\\",
                    ".sicoobito/",
                    ".sicoobito\\",
                )
                repo_status = git_ops.status(workspace_root)
                nao_rastreados = sorted(
                    f.path
                    for f in repo_status.files
                    if f.status == "untracked"
                    and not any(f.path.startswith(ign) or f.path == ign.rstrip("/\\") for ign in ignored_prefixes)
                )
                if nao_rastreados:
                    listagem = ", ".join(nao_rastreados[:8])
                    if len(nao_rastreados) > 8:
                        listagem += f" e mais {len(nao_rastreados) - 8}"
                    avisos.append(
                        f"{len(nao_rastreados)} arquivo(s) com alterações locais/untracked "
                        f"foram sincronizados no worktree da sessão: {listagem}."
                    )
            except GitError:
                pass

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
        token = await resolve_token(self.settings.github_token)
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

        # 5. Orquestração multiagente: profundidade herdada do pai (0 pra
        # sessão raiz), e o fechamento que `spawn_agent` chama pra criar um
        # filho — capturando `self` (este AgentRunner) e `session_id` (o
        # futuro pai) em vez de expor o AgentRunner inteiro pra ferramenta.
        depth = 0
        if parent_session_id is not None and self.coordinator is not None:
            depth = await self.coordinator.depth_of(parent_session_id) + 1

        async def _spawn_child_agent(*, task: str, display_name: str) -> str:
            filho = await self.create_session(
                task=task,
                workspace_root=workspace_root,
                mode="agent",
                parent_session_id=session_id,
            )
            burst = asyncio.get_running_loop().create_task(
                run_headless_burst(self, self.coordinator, filho)
            )
            self._background_tasks.add(burst)
            burst.add_done_callback(self._background_tasks.discard)
            return filho.session_id

        async def _wake_agent(target_session_id: str) -> bool:
            if self.is_being_driven(target_session_id):
                # Já tem alguém (humano via SSE, ou outro burst) avançando
                # essa sessão — ela vai drenar a própria caixa de mensagens
                # sozinha no próximo `wait_for_agents`/turno, sem precisar de
                # um burst concorrente que ia esbarrar no mesmo lock.
                return False
            alvo = self._sessions.get(target_session_id)
            if alvo is None:
                return False
            if self.coordinator is not None and await self.coordinator.is_stopped(
                target_session_id
            ):
                return False
            burst = asyncio.get_running_loop().create_task(
                run_headless_burst(self, self.coordinator, alvo)
            )
            self._background_tasks.add(burst)
            burst.add_done_callback(self._background_tasks.discard)
            return True

        contexto = ToolContext(
            session_id=session_id,
            workspace_root=worktree_path,
            fs=WorkspaceFS(worktree_path),
            project_slug=workspace_root.name,
            project_root=workspace_root,
            projects_root=self.settings.effective_projects_root,
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
            security=SecureBertService(),
            trace_recorder=self.trace_recorder,
            engine=self.engine,
            custom_instructions=_load_custom_instructions(workspace_root),
            approval_policy=load_approval_policy(workspace_root),
            coordinator=self.coordinator,
            spawn_child_agent=_spawn_child_agent if self.coordinator is not None else None,
            wake_agent=_wake_agent if self.coordinator is not None else None,
            parent_session_id=parent_session_id,
            max_wait_seconds=self.settings.agent_wait_max_seconds,
            max_spawn_depth=self.settings.agent_max_spawn_depth,
            max_children_per_agent=self.settings.agent_max_children_per_agent,
        )
        contexto.session_state.project_verified = bool(runtime_validation["project_ok"])
        contexto.session_state.git_ready = bool(runtime_validation.get("git_ready", True))

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

        if self.coordinator is not None:
            # Registrada mesmo sendo raiz (parent_id=None, depth=0) — assim
            # `view_agent_graph`/tetos de profundidade funcionam uniformemente
            # desde a primeira sessão, não só a partir do primeiro spawn.
            await self.coordinator.register(
                session_id=session_id,
                display_name=task[:80],
                parent_id=parent_session_id,
                depth=depth,
            )

        # Não-fatal de propósito, mesmo espírito do checkpointer e do sandbox
        # acima: um soluço no banco não pode impedir a criação da sessão, só
        # faz o histórico ficar incompleto para ela. `get` antes de `create`
        # porque `reconnect_session` chama este mesmo método passando um
        # `session_id` que já tem linha em `agent_session` (chave primária) —
        # sem a checagem, a segunda inserção quebraria com violação de PK.
        try:
            async with session_scope() as db:
                if await session_store.get(db, session_id=session_id) is None:
                    await session_store.create(
                        db,
                        session_id=session_id,
                        project=workspace_root.name,
                        task=task,
                        mode=mode,
                        profile=profile,
                        branch=branch or None,
                        base_branch=base,
                        parent_session_id=parent_session_id,
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

    async def update_session_summary(
        self,
        session_id: str,
        *,
        pending_count: int = 0,
        failed_count: int = 0,
        total_cost_usd: float | None = None,
        total_tokens: int | None = None,
        iterations: int | None = None,
    ) -> None:
        sessao = self._sessions.get(session_id)
        if sessao is None:
            return
        resumo = _session_summary(sessao, pending_count=pending_count, failed_count=failed_count)
        try:
            async with session_scope() as db:
                await session_store.update_metrics(
                    db,
                    session_id=session_id,
                    summary=resumo,
                    total_cost_usd=total_cost_usd,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    pending_approvals=pending_count,
                    last_failed_call_count=failed_count,
                )
        except Exception as exc:
            log.warning(
                "agent.session.summary.persist_failed",
                session=session_id,
                error=str(exc)[:200],
            )
        sessao.context.session_state.current_todos = sessao.context.current_todos

    def get_session(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    async def reconnect_session(self, session_id: str) -> AgentSession | None:
        """Reidrata uma sessão cujo runtime (sandbox, `ToolContext`) morreu —
        por exemplo depois de um restart do Docker — mas cujo registro em
        `agent_session` (Postgres) ainda mostra `status="open"`.

        Antes disto, uma sessão sobrevivente a um restart ficava presa: a
        listagem (`GET /api/agent/sessions`) continuava mostrando ela como
        `open`/`live=False`, mas qualquer rota que dependesse do runtime em
        memória devolvia 404 — a única saída era começar sessão nova, jogando
        fora o vínculo com a conversa/branch anteriores. Reaproveita o mesmo
        `session_id`: o worktree Git e o sandbox já sabem recriar/reaproveitar
        por conta própria a partir dele (`create_worktree`/
        `SandboxManager.acquire`), então basta chamar `create_session` de
        novo — não cria branch nova nem duplica a linha em `agent_session`.
        """
        existente = self._sessions.get(session_id)
        if existente is not None:
            return existente

        try:
            async with session_scope() as db:
                registro = await session_store.get(db, session_id=session_id)
        except Exception as exc:
            log.warning(
                "agent.session.reconnect.lookup_failed",
                session=session_id,
                error=str(exc)[:200],
            )
            return None

        if registro is None or registro.status not in {"open", "closed"}:
            return None

        raiz = self.settings.effective_projects_root
        if raiz is None:
            return None
        try:
            workspace_root = project_ops.resolve(Path(raiz), registro.project)
        except ProjectError as exc:
            log.warning(
                "agent.session.reconnect.project_missing",
                session=session_id,
                project=registro.project,
                error=str(exc),
            )
            return None

        sessao = await self.create_session(
            task=registro.task,
            workspace_root=workspace_root,
            mode=cast("AgentMode", registro.mode),
            session_id=session_id,
            profile=registro.profile,
            parent_session_id=registro.parent_session_id,
        )
        log.info("agent.session.reconnected", session=session_id)
        return sessao

    async def close_session(self, session_id: str, *, keep_branch: bool = True) -> None:
        sessao = self._sessions.pop(session_id, None)
        if sessao is None:
            return
        resumo_final = "Sessão encerrada"
        if sessao.branch:
            resumo_final = f"Sessão encerrada em {sessao.branch}"
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
                await session_store.mark_closed(
                    db, session_id=session_id, summary=resumo_final
                )
        except Exception as exc:
            log.warning(
                "agent.session.persist_close_failed", session=session_id, error=str(exc)[:200]
            )
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
            # pyrefly: ignore [bad-argument-type]
            repo_map=mapa,
            mode=session.mode,
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
        """Fecha o cliente HTTP compartilhado do navegador e espera/cancela
        bursts headless pendentes, no desligamento do processo."""
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        if self._browser_http is not None and not self._browser_http.is_closed:
            await self._browser_http.aclose()

    async def stream_run(
        self, session: AgentSession, *, resume: Any = None, message: str | None = None
    ):
        """Executa o grafo emitindo eventos. Cede o controle na aprovação."""
        lock = self._session_locks.setdefault(session.session_id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError(
                f"Sessão {session.session_id} já está em execução — aguarde terminar "
                "antes de reenviar (evita executar a mesma aprovação duas vezes)."
            )
        async with lock:
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
                config: dict[str, Any] = {"configurable": {"thread_id": session.session_id}}

                from sicoobito.telemetry.langfuse_tracer import get_langfuse_callback
                langfuse_handler = get_langfuse_callback(
                    session_id=session.session_id,
                    trace_name=f"agent-run:{session.mode}",
                    tags=["sicoobito", session.mode],
                    settings=self.settings,
                )
                if langfuse_handler is not None:
                    config["callbacks"] = [langfuse_handler]

                if resume is not None:
                    from langgraph.types import Command

                    entrada: Any = Command(resume=resume)
                elif message:
                    entrada = {
                        "messages": [{"role": "user", "content": message}],
                        "finished": False,
                    }
                else:
                    estado_existente = (
                        await compilado.aget_state(config) if compilado.checkpointer else None
                    )
                    if estado_existente and estado_existente.values:
                        entrada = None
                    else:
                        entrada = await self._initial_state(session)

                async for evento in compilado.astream(
                    entrada, config=config, stream_mode="updates"
                ):
                    for no, atualizacao in evento.items():
                        yield {"node": no, "update": _serializable(atualizacao)}
                        if no == "approve":
                            pendentes = atualizacao.get("pending") or []
                            await self.update_session_summary(
                                session.session_id,
                                pending_count=len(pendentes),
                                failed_count=max(0, int((atualizacao.get("last_failed_call_count") or 0))),
                            )
                        elif no == "act":
                            await self.update_session_summary(
                                session.session_id,
                                pending_count=0,
                                failed_count=max(0, int((atualizacao.get("last_failed_call_count") or 0))),
                            )

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
