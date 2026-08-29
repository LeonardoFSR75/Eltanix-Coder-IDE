"""Sessões do agente: montagem, execução e retomada.

Uma sessão amarra quatro coisas de tempos de vida diferentes: o worktree Git
(sobrevive ao processo), o container do sandbox (sobrevive a um reload), o
checkpoint do grafo (no Postgres) e o contexto de ferramentas (em memória).
Ao retomar uma sessão, os três primeiros são reaproveitados e o quarto é
remontado.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from eltanix.audit.service import AuditService
    from eltanix.documents.service import DocumentService
    from eltanix.firecrawl.service import FirecrawlService
    from eltanix.notes.service import NoteService
    from eltanix.skills.service import SkillService
    from eltanix.telemetry.tracer import TraceRecorder

import httpx
import structlog
from redis.asyncio import Redis

from eltanix.agent import session_store
from eltanix.agent.approval_policy_config import load_approval_policy
from eltanix.agent.context_rules import build_context_rules_prompt, match_context_rules
from eltanix.agent.context_rules_config import load_context_rules
from eltanix.agent.coordinator import AgentCoordinator
from eltanix.agent.custom_modes import CustomModeService
from eltanix.agent.graph import DEFAULT_MAX_ITERATIONS, build_graph
from eltanix.agent.headless import run_headless_burst
from eltanix.agent.prompts import build_task_prompt
from eltanix.agent.slash_commands import resolve_slash_command
from eltanix.agent.snapshot_store import SnapshotService
from eltanix.agent.state import BUILTIN_MODES, AgentMode
from eltanix.agent.tools import ToolContext
from eltanix.browser.client import BrowserClient, BrowserConfig
from eltanix.browser.replay import mark_replay_expired, store_replay
from eltanix.config import Settings
from eltanix.context.indexer import ContextIndexer
from eltanix.context.repomap import build_repo_map
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine
from eltanix.sandbox.container import SandboxManager, SandboxUnavailableError
from eltanix.sandbox.executor import ExecutorSandboxManager
from eltanix.security.service import SecureBertService
from eltanix.storage.blob import BlobStore
from eltanix.workspace import git as git_ops
from eltanix.workspace import projects as project_ops
from eltanix.workspace.fs import WorkspaceFS
from eltanix.workspace.git import GitError
from eltanix.workspace.github import GitHubClient, GitHubError, parse_remote, resolve_token
from eltanix.workspace.projects import ProjectError

log = get_logger(__name__)

_T = TypeVar("_T")


class SessionAlreadyRunningError(RuntimeError):
    """`stream_run` já está avançando esta sessão em outra chamada.

    Subclasse dedicada (em vez de `RuntimeError` puro) para que
    `run_headless_burst` (`agent/headless.py`) consiga distinguir esta
    condição benigna — outra chamada já está dirigindo a sessão, nada
    quebrou — de uma falha real do grafo, sem depender de casar a mensagem.
    """


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
        entries = sorted(p.name for p in workspace_root.iterdir())  # noqa: ASYNC240
    except OSError as exc:
        return {
            "project_ok": False,
            "reason": f"não foi possível listar o projeto: {exc}",
            "files": [],
            "ecosystem": "unknown",
            "manifest_name": None,
            "git_ready": False,
        }

    from eltanix.api.routes.packages import detect_ecosystem, get_manifest_name

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
    """Lê `.eltanix/instructions.md` do projeto (não do worktree da sessão)
    — best-effort: arquivo ausente ou erro de leitura não deve impedir a
    sessão de começar, mesmo espírito de degradação graciosa do resto do
    projeto (serviço opcional fora do ar não derruba o essencial)."""
    caminho = workspace_root / ".eltanix" / "instructions.md"
    try:
        texto = caminho.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("agent.custom_instructions.read_failed", error=str(exc)[:200])
        return None
    return texto or None


def _load_context_rules_prompt(
    workspace_root: Path, *, focus_files: list[str] | None, focus_folder: str | None
) -> str | None:
    """Lê `.eltanix/context_rules.yaml` do projeto e devolve a seção de prompt
    já renderizada para as regras que casarem com `focus_files`/`focus_folder`
    (Fase 4 do upgrade do agente, estilo `.cursor/rules`). `load_context_rules`
    já degrada para uma config vazia em qualquer falha de leitura/parse/validação
    — aqui só resta combinar leitura + match + renderização."""
    config = load_context_rules(workspace_root)
    casadas = match_context_rules(config, focus_files=focus_files, focus_folder=focus_folder)
    return build_context_rules_prompt(casadas)


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
    sandbox_error: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Perfil de roteamento escolhido explicitamente pelo usuário; None mantém a
    # escolha implícita por modo em `_initial_state`.
    profile: str | None = None
    focus_files: list[str] = field(default_factory=list)
    focus_folder: str | None = None
    images: list[str] = field(default_factory=list)
    is_web_app: bool = False
    web_prewarmed: bool = False

    @property
    def sandbox_available(self) -> bool:
        """Derivado de `context.sandbox`, nunca um booleano espelhado à mão —
        `prewarm_web_app` só precisa atribuir `context.sandbox`, sem também
        lembrar de manter este campo em sincronia."""
        return self.context.sandbox is not None


def _detect_web_app(workspace_path: Path) -> bool:
    """Detecta se o projeto possui características de aplicação web para auto-aquecimento."""
    indicadores_arquivos = {
        "app.py",
        "server.py",
        "main.py",
        "index.html",
        "package.json",
        "requirements.txt",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts",
    }
    indicadores_pastas = {"templates", "static", "pages", "src/pages", "src/app", "public"}
    try:
        if not workspace_path.exists():
            return False
        nomes = {p.name.lower() for p in workspace_path.iterdir() if not p.name.startswith(".")}
        if any(ind in nomes for ind in indicadores_arquivos):
            req = workspace_path / "requirements.txt"
            if req.exists():
                conteudo = req.read_text("utf-8", "ignore").lower()
                if any(
                    w in conteudo
                    for w in (
                        "flask",
                        "fastapi",
                        "django",
                        "tornado",
                        "bottle",
                        "uvicorn",
                        "gunicorn",
                        "streamlit",
                        "gradio",
                    )
                ):
                    return True
            pkg = workspace_path / "package.json"
            if pkg.exists():
                conteudo = pkg.read_text("utf-8", "ignore").lower()
                if any(
                    w in conteudo
                    for w in (
                        "express",
                        "next",
                        "vite",
                        "react",
                        "vue",
                        "svelte",
                        "fastify",
                        "koa",
                        "hono",
                    )
                ):
                    return True
            if (workspace_path / "app.py").exists() or (workspace_path / "index.html").exists():
                return True
        for pasta in indicadores_pastas:
            if (workspace_path / pasta).exists():
                return True
    except Exception:
        pass
    return False


def _session_summary(
    session: AgentSession, *, pending_count: int = 0, failed_count: int = 0
) -> str:
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


class AgentRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: RouterEngine,
        indexer: ContextIndexer,
        sandboxes: SandboxManager | ExecutorSandboxManager,
        browser_config: BrowserConfig | None = None,
        documents: DocumentService | None = None,
        notes: NoteService | None = None,
        skills: SkillService | None = None,
        custom_modes: CustomModeService | None = None,
        snapshots: SnapshotService | None = None,
        audit: AuditService | None = None,
        firecrawl: FirecrawlService | None = None,
        extensions_manager: Any | None = None,  # ExtensionsManager
        trace_recorder: TraceRecorder | None = None,
        coordinator: AgentCoordinator | None = None,
        blob: BlobStore | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.indexer = indexer
        self.sandboxes = sandboxes
        self.browser_config = browser_config
        self.documents = documents
        self.notes = notes
        self.skills = skills
        self.custom_modes = custom_modes
        self.snapshots = snapshots
        self.audit = audit
        self.firecrawl = firecrawl
        self.extensions_manager = extensions_manager
        self.trace_recorder = trace_recorder
        # Replay de sessão do navegador (Fase 4b) — `None` em qualquer um dos
        # dois é normal (MinIO/Redis fora do ar): `close_session` só perde o
        # replay, não falha o encerramento da sessão.
        self.blob = blob
        self.redis = redis
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
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._checkpointer: Any | None = None
        # Grafo compilado por sessão (LangGraph `StateGraph.compile()`) —
        # sem isto, `_compiled_graph` reconstruía o grafo inteiro (montagem
        # do system prompt + registro de nós/arestas + compile) a cada
        # chamada, mesmo em `get_messages`/`list_checkpoints`/`rewind_to`
        # (leitura pura de checkpoint) e a cada novo `stream_run` da mesma
        # sessão — o que também zerava o cache de schemas por `(mode,
        # has_plan)` de `build_graph` a cada retomada. Limpo em
        # `close_session`.
        self._compiled_graphs: dict[str, Any] = {}
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
            if self._checkpointer is not None:
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

    # ── Roteamento automático de skills (Fase 1 do upgrade do agente) ──────
    # Defaults; `settings.agent_skill_routing_*` (env) sobrescreve por
    # deployment. Resolvidos em `_skill_routing_params()` para tolerar um
    # `settings` mock nos testes.
    _SKILLS_TOP_K = 2
    _SKILLS_MIN_SCORE = 0.72

    def _skill_routing_params(self) -> tuple[int, float]:
        """`(top_k, min_score)` efetivos — do `settings` quando forem números
        de verdade, senão os defaults de classe (o caso dos testes com
        `settings` mockado, onde os atributos viram `MagicMock`)."""
        top_k = getattr(self.settings, "agent_skill_routing_top_k", None)
        min_score = getattr(self.settings, "agent_skill_routing_min_score", None)
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            top_k = self._SKILLS_TOP_K
        if isinstance(min_score, bool) or not isinstance(min_score, int | float):
            min_score = self._SKILLS_MIN_SCORE
        return top_k, float(min_score)

    async def _timed_prompt_phase(self, *, session_id: str, name: str, coro: Awaitable[_T]) -> _T:
        """Cronometra e grava no `TraceRecorder` cada etapa da montagem do
        prompt aditivo da sessão (roteamento de skills, regras de contexto,
        resolução de modo customizado) — antes disso essas três só apareciam
        em log solto, nunca no mesmo buffer de spans que as ferramentas e o
        RAG, então não dava para ver o custo delas no painel de telemetria.

        Usa `kind="rag"` de propósito: são todas recuperação/resolução no
        bootstrap da sessão, e reaproveitar o kind existente evita alargar o
        Literal `TraceKind`, o schema de `ToolSpan.kind` e o mapeamento OTLP
        só para três nomes novos. O prefixo `skill_routing`/`context_rules`/
        `custom_mode` no `name` já os separa na leitura."""
        if self.trace_recorder is None:
            return await coro
        inicio = time.perf_counter()
        status: str = "ok"
        try:
            return await coro
        except Exception:
            status = "error"
            raise
        finally:
            self.trace_recorder.record(
                kind="rag",
                name=name,
                latency_ms=(time.perf_counter() - inicio) * 1000,
                status=cast(Any, status),
                session_id=session_id,
            )

    # Fase 3 do upgrade do agente (estilo Antigravity): "Modo Planejar" sempre
    # segue o processo estruturado destas duas skills vendorizadas
    # (`.agents/agent-skills/skills/`), independente de slash command ou
    # similaridade — o modo em si já é a intenção "planejar antes de agir".
    _PLAN_MODE_FORCED_SKILLS = ("spec-driven-development", "planning-and-task-breakdown")

    async def _route_skills(self, task: str, mode: str = "agent") -> str | None:
        """Monta a seção de skills ativas para esta tarefa, combinando três
        fontes independentes (nunca duplicando uma skill presente em mais de
        uma):

        1. **Forçada por slash command** (Fase 2): se `task` começa com um
           comando reconhecido (`/spec`, `/test`, `/fix`...), a skill que ele
           mapeia (`agent/slash_commands.py`) é buscada por nome exato — sem
           depender de embedding, determinística.
        2. **Forçada pelo modo `plan`** (Fase 3): sempre injeta
           `_PLAN_MODE_FORCED_SKILLS`, também por nome exato — o "Modo
           Planejar" da UI não depende do usuário lembrar de digitar `/spec`.
        3. **Roteada por similaridade** (Fase 1): embeda `task` inteiro
           (incluindo o prefixo do comando, se houver — ruído desprezível
           para o embedding) e busca as skills mais próximas de
           `description` via `SkillService.find_relevant`.

        Best-effort em cada fonte: falha na busca por nome ou no embedding
        não derruba a outra fonte nem a sessão — cada uma degrada para "não
        contribuiu nada" independentemente. Chamado uma única vez, na
        criação da sessão, para preservar o prefixo estável do system prompt
        (ver docstring de `SYSTEM_PROMPT` em `prompts.py`)."""
        if self.skills is None:
            return None

        secoes: list[str] = []
        nomes_vistos: set[str] = set()

        _, comando = resolve_slash_command(task)
        if comando is not None and comando.skill_name is not None:
            try:
                skill_forcada = await self.skills.get_by_name(comando.skill_name)
            except Exception as exc:
                log.debug("agent.skill_routing.command_lookup_failed", error=str(exc)[:200])
                skill_forcada = None
            if skill_forcada is not None:
                secoes.append(
                    f"### {skill_forcada.name} (ativada por `{comando.command}`)\n\n"
                    f"{skill_forcada.system_prompt}"
                )
                nomes_vistos.add(skill_forcada.name)

        if mode == "plan":
            for nome_skill in self._PLAN_MODE_FORCED_SKILLS:
                if nome_skill in nomes_vistos:
                    continue
                try:
                    skill_do_modo = await self.skills.get_by_name(nome_skill)
                except Exception as exc:
                    log.debug("agent.skill_routing.plan_mode_lookup_failed", error=str(exc)[:200])
                    skill_do_modo = None
                if skill_do_modo is not None:
                    secoes.append(
                        f"### {skill_do_modo.name} (padrão do Modo Planejar)\n\n"
                        f"{skill_do_modo.system_prompt}"
                    )
                    nomes_vistos.add(skill_do_modo.name)

        if task.strip():
            try:
                resultado = await self.engine.embed(
                    requested_model=self.settings.embedding_profile,
                    inputs=[task],
                    source="agent.skill_routing",
                )
                dados = resultado.payload.get("data") or []
                vetor = dados[0].get("embedding") if dados else None
                if vetor:
                    top_k, min_score = self._skill_routing_params()
                    relevantes = await self.skills.find_relevant(
                        vetor, top_k=top_k, min_score=min_score
                    )
                    for skill in relevantes:
                        if skill.name in nomes_vistos:
                            continue
                        secoes.append(
                            f"### {skill.name} (roteada automaticamente por similaridade)\n\n"
                            f"{skill.system_prompt}"
                        )
                        nomes_vistos.add(skill.name)
            except Exception as exc:
                log.debug("agent.skill_routing.failed", error=str(exc)[:200])

        if not secoes:
            return None

        return (
            "## Habilidades relevantes para esta tarefa\n\n"
            "Siga o processo descrito abaixo quando ele for aplicável ao que você está "
            "fazendo agora.\n\n" + "\n\n".join(secoes)
        )

    # ── Modos customizáveis pelo usuário (Fase 6 do upgrade do agente) ─────

    async def _resolve_custom_mode(self, mode: str) -> tuple[list[str] | None, str | None]:
        """Resolve `mode` como id de modo customizado, uma única vez na
        criação da sessão — nunca a cada turno, mesmo motivo de todo o resto
        do prompt aditivo (`_route_skills`, `_load_context_rules_prompt`):
        preservar o prefixo estável do system prompt (ver docstring de
        `SYSTEM_PROMPT` em `prompts.py`).

        Devolve `(None, None)` sempre que `mode` já é um dos 7 modos
        embutidos, quando não há `CustomModeService` configurado, quando
        `mode` não é um UUID válido, ou quando nenhum modo customizado bate
        com esse id — em todos os casos, `agent/graph.py::_tool_schemas`
        degrada para somente leitura, nunca falha aberto para WRITE/EXEC.
        """
        if mode in BUILTIN_MODES or self.custom_modes is None:
            return None, None
        try:
            mode_id = uuid.UUID(mode)
        except ValueError:
            log.debug("agent.custom_mode.invalid_id", mode=mode[:80])
            return None, None
        try:
            modo = await self.custom_modes.get(mode_id)
        except Exception as exc:
            log.warning("agent.custom_mode.lookup_failed", error=str(exc)[:200])
            return None, None
        if modo is None:
            return None, None
        return list(modo.allowed_tools or []), modo.prompt_block or None

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
        images: list[str] | None = None,
        parent_session_id: str | None = None,
        specialization_prompt: str | None = None,
    ) -> AgentSession:
        session_id = session_id or self.sandboxes.new_session_id()
        workspace_root = workspace_root.resolve()  # noqa: ASYNC240
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise ValueError(f"Projeto não existe em PROJECTS_ROOT: {workspace_root}")

        runtime_validation = await validate_project_runtime(workspace_root)
        if not runtime_validation["project_ok"]:
            raise ValueError(runtime_validation["reason"])

        # Garante o ambiente de pacotes (.venv, node_modules, etc) no projeto raiz
        # antes de criar o worktree
        try:
            from eltanix.api.routes.packages import ensure_project_env

            await ensure_project_env(workspace_root)
        except Exception as exc:
            log.warning(
                "runner.ensure_project_env.failed", project=workspace_root.name, error=str(exc)
            )

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
                    ".eltanix/",
                    ".eltanix\\",
                )
                repo_status = git_ops.status(workspace_root)
                nao_rastreados = sorted(
                    f.path
                    for f in repo_status.files
                    if f.status == "untracked"
                    and not any(
                        f.path.startswith(ign) or f.path == ign.rstrip("/\\")
                        for ign in ignored_prefixes
                    )
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

        async def _spawn_child_agent(
            *, task: str, display_name: str, specialization_prompt: str | None = None
        ) -> str:
            assert self.coordinator is not None
            filho = await self.create_session(
                task=task,
                workspace_root=workspace_root,
                mode="agent",
                parent_session_id=session_id,
                specialization_prompt=specialization_prompt,
            )
            burst = asyncio.get_running_loop().create_task(
                run_headless_burst(self, self.coordinator, filho)
            )
            self._background_tasks.add(burst)
            burst.add_done_callback(self._background_tasks.discard)
            return filho.session_id

        async def _wake_agent(target_session_id: str) -> bool:
            assert self.coordinator is not None
            if self.is_being_driven(target_session_id):
                # Já tem alguém (humano via SSE, ou outro burst) avançando
                # essa sessão — ela vai drenar a própria caixa de mensagens
                # sozinha no próximo `wait_for_agents`/turno, sem precisar de
                # um burst concorrente que ia esbarrar no mesmo lock.
                return False
            alvo = self._sessions.get(target_session_id)
            if alvo is None:
                return False
            if await self.coordinator.is_stopped(target_session_id):
                return False
            burst = asyncio.get_running_loop().create_task(
                run_headless_burst(self, self.coordinator, alvo)
            )
            self._background_tasks.add(burst)
            burst.add_done_callback(self._background_tasks.discard)
            return True

        async def _context_rules_phase() -> str | None:
            return _load_context_rules_prompt(
                workspace_root, focus_files=focus_files, focus_folder=focus_folder
            )

        routed_skills_prompt = (
            await self._timed_prompt_phase(
                session_id=session_id,
                name="skill_routing",
                coro=self._route_skills(task, mode),
            )
            if self.skills is not None
            else None
        )
        context_rules_prompt = await self._timed_prompt_phase(
            session_id=session_id, name="context_rules", coro=_context_rules_phase()
        )
        custom_mode_allowed_tools, custom_mode_prompt_block = await self._timed_prompt_phase(
            session_id=session_id,
            name="custom_mode_resolve",
            coro=self._resolve_custom_mode(mode),
        )

        contexto = ToolContext(
            session_id=session_id,
            workspace_root=worktree_path,
            fs=WorkspaceFS(worktree_path),
            project_slug=workspace_root.name,
            project_root=workspace_root,
            projects_root=self.settings.effective_projects_root,
            sandbox=sandbox,
            sandboxes=self.sandboxes,
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
            firecrawl=self.firecrawl,
            extensions_manager=self.extensions_manager,
            security=SecureBertService(),
            trace_recorder=self.trace_recorder,
            snapshots=self.snapshots,
            engine=self.engine,
            custom_instructions=_load_custom_instructions(workspace_root),
            specialization_prompt=specialization_prompt,
            routed_skills_prompt=routed_skills_prompt,
            context_rules_prompt=context_rules_prompt,
            custom_mode_allowed_tools=custom_mode_allowed_tools,
            custom_mode_prompt_block=custom_mode_prompt_block,
            mode=mode,
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
        contexto.session_state.workspace_listed = bool(runtime_validation.get("files"))
        # NÃO pré-satisfazer aqui: packages_checked só deve virar True quando
        # `manage_packages(action="list")` de fato rodar e inspecionar as
        # dependências (ver agent/tools/packages.py) — detectar o ecossistema
        # em validate_project_runtime() não é o mesmo que checar os pacotes.
        contexto.session_state.git_ready = bool(runtime_validation.get("git_ready", True))

        # `_detect_web_app` faz vários `Path.exists()`/`.iterdir()`/
        # `.read_text()` — I/O bloqueante que, sem `to_thread`, prendia o
        # event loop inteiro a cada `create_session` (item 11 do plano de
        # robustez do navegador interno). Ao contrário do I/O pontual deste
        # arquivo silenciado com um comentário de lint ao lado (linhas 86 e
        # 511), esta função varre o projeto inteiro e roda em todo
        # `create_session`, então o custo real justifica a correção completa.
        is_web = await asyncio.to_thread(_detect_web_app, workspace_root)
        sessao = AgentSession(
            session_id=session_id,
            workspace_root=workspace_root,
            worktree_path=worktree_path,
            branch=branch,
            base_branch=base,
            mode=mode,
            task=task,
            context=contexto,
            sandbox_error=sandbox_error,
            warnings=avisos,
            profile=profile,
            focus_files=focus_files or [],
            focus_folder=focus_folder,
            images=images or [],
            is_web_app=is_web,
            web_prewarmed=False,
        )
        self._sessions[session_id] = sessao

        # Se for detectado como Web App, dispara o pré-aquecimento em background sem bloquear
        if is_web:
            prewarm_task = asyncio.get_running_loop().create_task(self.prewarm_web_app(session_id))
            self._background_tasks.add(prewarm_task)
            prewarm_task.add_done_callback(self._background_tasks.discard)

        if self.coordinator is not None:
            # Registrada mesmo sendo raiz (parent_id=None, depth=0) — assim
            # `view_agent_graph`/tetos de profundidade funcionam uniformemente
            # desde a primeira sessão, não só a partir do primeiro spawn.
            registrado = await self.coordinator.register(
                session_id=session_id,
                display_name=task[:80],
                parent_id=parent_session_id,
                depth=depth,
            )
            # Fail closed só para filhos: sem o registro, o coordenador não
            # tem como rastrear pai/filho (children_of/view_agent_graph/
            # tetos de profundidade), então a sessão filha não pode seguir
            # como se tivesse sido criada com sucesso.
            if parent_session_id is not None and not registrado:
                self._sessions.pop(session_id, None)
                raise RuntimeError(
                    f"Falha ao registrar o agente filho '{session_id}' no "
                    "coordenador (Redis indisponível) — sessão descartada."
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
            is_web_app=is_web,
        )
        return sessao

    async def prewarm_web_app(self, session_id: str, *, force: bool = False) -> bool:
        """Pré-aquece o sandbox e o browser Playwright em background para a sessão."""
        sessao = self._sessions.get(session_id)
        if sessao is None:
            return False
        if not force and not sessao.is_web_app:
            return False

        sessao.is_web_app = True
        try:
            # 1. Pré-aquecimento do sandbox container no executor
            if self.sandboxes is not None:
                sb = await self.sandboxes.acquire(session_id, sessao.workspace_root)
                sessao.context.sandbox = sb
            # 2. Pré-aquecimento da página Playwright no browser service
            if sessao.context.browser is not None:
                await sessao.context.browser.create_session()
            sessao.web_prewarmed = True
            log.info("agent.web_app.prewarmed", session=session_id)
            return True
        except Exception as exc:
            log.warning("agent.web_app.prewarm_failed", session=session_id, error=str(exc))
            return False

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

        try:
            sessao = await self.create_session(
                task=registro.task,
                workspace_root=workspace_root,
                mode=cast("AgentMode", registro.mode),
                session_id=session_id,
                profile=registro.profile,
                parent_session_id=registro.parent_session_id,
            )
        except RuntimeError as exc:
            # Mesmo fail-closed do coordenador que `_spawn_child_agent` trata
            # como falha — aqui, na reconexão, degrada pro 404 já existente
            # em vez de deixar a exceção subir como 500.
            log.warning(
                "agent.session.reconnect.coordinator_failed",
                session=session_id,
                error=str(exc)[:200],
            )
            return None
        log.info("agent.session.reconnected", session=session_id)
        return sessao

    async def close_session(self, session_id: str, *, keep_branch: bool = True) -> None:
        sessao = self._sessions.pop(session_id, None)
        self._compiled_graphs.pop(session_id, None)
        if sessao is None:
            return
        resumo_final = "Sessão encerrada"
        if sessao.branch:
            resumo_final = f"Sessão encerrada em {sessao.branch}"
        await self.sandboxes.release(session_id)
        if sessao.context.browser is not None:
            replay_payload = await sessao.context.browser.stop()
            with suppress(Exception):
                replay = await store_replay(
                    blob=self.blob,
                    redis=self.redis,
                    session_id=session_id,
                    project=sessao.workspace_root.name,
                    payload=replay_payload,
                )
                if not replay and replay_payload and replay_payload.get("expired_by_ttl"):
                    # Mesmo sinal do painel manual (ver `api/routes/browser.py`
                    # ::close_browser_session`) — o serviço de navegador já
                    # descartou a sessão por TTL antes deste `stop()` chegar.
                    await mark_replay_expired(self.redis, session_id)
        if sessao.branch:
            try:
                git_ops.remove_worktree(
                    sessao.workspace_root, session_id, delete_branch=not keep_branch
                )
            except GitError as exc:
                log.warning("agent.session.worktree_cleanup", session=session_id, error=str(exc))
        try:
            async with session_scope() as db:
                await session_store.mark_closed(db, session_id=session_id, summary=resumo_final)
        except Exception as exc:
            log.warning(
                "agent.session.persist_close_failed", session=session_id, error=str(exc)[:200]
            )
        log.info("agent.session.closed", session=session_id)

    # ── Execução ────────────────────────────────────────────────────────────

    async def _compiled_graph(self, session: AgentSession):
        cacheado = self._compiled_graphs.get(session.session_id)
        if cacheado is not None:
            return cacheado
        grafo = build_graph(self.engine, session.context)
        checkpointer = await self.checkpointer()
        compilado = grafo.compile(checkpointer=checkpointer) if checkpointer else grafo.compile()
        if checkpointer:
            # Só cacheia com checkpointer de verdade — sem ele a sessão já
            # não é durável, e cachear aqui perderia a chance de pegar um
            # checkpointer que volte a ficar disponível numa chamada
            # seguinte (`checkpointer()` tenta de novo a cada vez que está
            # `None`, mesmo espírito de degradação do resto do módulo).
            self._compiled_graphs[session.session_id] = compilado
        return compilado

    async def _initial_state(self, session: AgentSession) -> dict[str, Any]:
        mapa = None
        try:
            resultado = await build_repo_map(
                self.indexer.workspace_key(session.workspace_root), token_budget=1500
            )
            mapa = str(resultado.get("text")) if resultado.get("text") else None
        except Exception as exc:
            log.debug("agent.repomap.unavailable", error=str(exc)[:200])

        prompt_text = build_task_prompt(
            session.task,
            repo_map=mapa,
            mode=session.mode,
            focus_files=session.focus_files,
            focus_folder=session.focus_folder,
            custom_mode_prompt_block=session.context.custom_mode_prompt_block,
        )

        if session.images:
            partes_conteudo: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
            for img in session.images:
                partes_conteudo.append({"type": "image_url", "image_url": {"url": img}})
            primeira_mensagem = {"role": "user", "content": partes_conteudo}
        else:
            primeira_mensagem = {"role": "user", "content": prompt_text}

        return {
            "messages": [primeira_mensagem],
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

    # ── Checkpoints / rewind (Fase 8 do upgrade do agente) ────────────────────

    @staticmethod
    async def _iteration_checkpoints(compilado: Any, config: Any) -> list[Any]:
        """Um checkpoint representante por valor distinto de `AgentState
        ["iterations"]`, em ordem cronológica — não um checkpoint por nó do
        grafo (think/approve/act geram um cada, vários por iteração).

        `aget_state_history` devolve o mais novo primeiro; junta tudo (o
        histórico de uma sessão é limitado por `max_iterations`, cabe em
        memória sem problema) e agrupa por corridas contíguas do mesmo valor
        de `iterations` andando em ordem cronológica.

        Dentro de cada grupo, prefere o checkpoint cuja última mensagem NÃO é
        de `role="user"`. Isso importa porque continuar uma sessão já
        finalizada (`stream_run` com `message=...`) funde a nova mensagem do
        usuário como uma atualização de entrada ANTES do próximo `think()`
        rodar — essa fusão não muda `iterations` (só `think()` muda), então
        ela vira só mais um checkpoint dentro da MESMA corrida contígua do
        último valor do turno anterior, mais novo que o checkpoint que de
        fato terminou aquele turno. Sem este filtro, tanto `list_checkpoints`
        quanto `rewind_to` pegariam esse checkpoint "turno anterior já
        terminado, mas com a próxima mensagem já colada" em vez do estado
        limpo de fim de turno — fazendo um rewind para aquele valor de
        iteração não desfazer a mensagem seguinte. Um checkpoint pós-`act()`/
        pós-`think()` legítimo nunca termina com `role="user"` por último (a
        última mensagem é sempre do `act()` — resultado de ferramenta — ou do
        `think()` — resposta do assistente); só o estado inicial da sessão e
        essas fusões de entrada terminam assim, então o filtro nunca descarta
        um checkpoint que devesse ser o representante.
        """
        historico = [snap async for snap in compilado.aget_state_history(config)]
        historico.reverse()  # cronológico: mais antigo primeiro

        grupos: list[list[Any]] = []
        for snap in historico:
            iteracao = (snap.values or {}).get("iterations")
            if iteracao is None:
                continue
            if grupos and (grupos[-1][0].values or {}).get("iterations") == iteracao:
                grupos[-1].append(snap)
            else:
                grupos.append([snap])

        representantes: list[Any] = []
        for grupo in grupos:
            candidato = next(
                (
                    s
                    for s in reversed(grupo)
                    if ((s.values or {}).get("messages") or [{}])[-1].get("role") != "user"
                ),
                grupo[-1],
            )
            representantes.append(candidato)
        return representantes

    async def list_checkpoints(self, session: AgentSession) -> list[dict[str, Any]]:
        """`[]` sem checkpointer (Postgres indisponível) — mesmo fail-soft de
        `AgentRunner.session_diff`/histórico de mensagens."""
        compilado = await self._compiled_graph(session)
        if not compilado.checkpointer:
            return []
        config: Any = {"configurable": {"thread_id": session.session_id}}

        pontos: list[dict[str, Any]] = []
        for snap in await self._iteration_checkpoints(compilado, config):
            valores = snap.values or {}
            mensagens = valores.get("messages") or []
            ultima_assistant = next(
                (
                    m
                    for m in reversed(mensagens)
                    if m.get("role") == "assistant" and m.get("content")
                ),
                None,
            )
            resumo = (ultima_assistant or {}).get("content") or ""
            ultima_mensagem = mensagens[-1] if mensagens else {}
            finalizado = bool(
                ultima_mensagem.get("role") == "assistant"
                and ultima_mensagem.get("content")
                and not ultima_mensagem.get("tool_calls")
            )
            pontos.append(
                {
                    "iteration": valores.get("iterations"),
                    "created_at": snap.created_at,
                    "summary": resumo[:160],
                    "finished": finalizado,
                }
            )
        return pontos

    async def rewind_to(self, session: AgentSession, *, iteration: int) -> dict[str, Any]:
        """Restaura a sessão para o fim da iteração `iteration`: trunca
        `messages`/`todos`/etc. do checkpointer até esse ponto (forka um novo
        checkpoint a partir do antigo — `aupdate_state` é o "time travel"
        nativo do LangGraph, não apaga nada) e reverte todo arquivo escrito
        depois dela, usando `SnapshotService.restore_targets` (Fase 8).

        Levanta `RuntimeError`/`ValueError` em vez de degradar: ao contrário
        de quase tudo nesta classe, isto é uma ação explícita e destrutiva do
        usuário — se não pode ser feita direito, a rota precisa saber e
        devolver um erro, não fingir sucesso.
        """
        compilado = await self._compiled_graph(session)
        if not compilado.checkpointer:
            raise RuntimeError("checkpointer indisponível — sem histórico para restaurar")
        config: Any = {"configurable": {"thread_id": session.session_id}}

        alvo_config = next(
            (
                snap.config
                for snap in await self._iteration_checkpoints(compilado, config)
                if (snap.values or {}).get("iterations") == iteration
            ),
            None,
        )
        if alvo_config is None:
            raise ValueError(f"iteração {iteration} não encontrada no histórico desta sessão")

        await compilado.aupdate_state(alvo_config, values=None)

        arquivos_restaurados: list[str] = []
        if self.snapshots is not None:
            alvos = await self.snapshots.restore_targets(
                session_id=session.session_id, after_iteration=iteration
            )
            for alvo in alvos:
                try:
                    await asyncio.to_thread(
                        session.context.fs.write, alvo.path, alvo.content_before
                    )
                    arquivos_restaurados.append(alvo.path)
                except Exception as exc:
                    log.warning(
                        "agent.rewind.file_restore_failed",
                        session=session.session_id,
                        path=alvo.path,
                        error=str(exc)[:200],
                    )

        log.info(
            "agent.rewind.done",
            session=session.session_id,
            iteration=iteration,
            files_restored=len(arquivos_restaurados),
        )
        return {"iteration": iteration, "files_restored": arquivos_restaurados}

    async def run_zombie_session_reaper(self, interval_seconds: int = 3600) -> None:
        """Laço de limpeza periódica, mesmo padrão de `SandboxManager.run_reaper`
        e `AuthService.run_session_purge_reaper`.

        Uma aba fechada sem `close_session` explícito deixa `AgentSessionRecord.
        status` em `"open"` para sempre (comentário do próprio modelo, `db/
        models.py`) — sem esta varredura, a listagem de "sessões ativas" acumula
        ruído indefinidamente. Marca como `"abandoned"`, nunca deleta: o
        histórico continua auditável, só sai do filtro padrão de "ativas"."""
        from datetime import UTC, datetime, timedelta

        while True:
            try:
                await asyncio.sleep(interval_seconds)
                limite = datetime.now(UTC) - timedelta(
                    hours=self.settings.agent_session_abandon_after_hours
                )
                async with session_scope() as session:
                    marcadas = await session_store.mark_abandoned(session, older_than=limite)
                if marcadas:
                    log.info("agent.sessions.abandoned_reaped", count=marcadas)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("agent.sessions.abandon_reaper_iteration_failed", error=str(exc)[:200])

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
        self,
        session: AgentSession,
        *,
        resume: Any = None,
        message: str | None = None,
        images: list[str] | None = None,
    ):
        """Executa o grafo emitindo eventos. Cede o controle na aprovação."""
        lock = self._session_locks.setdefault(session.session_id, asyncio.Lock())
        if lock.locked():
            raise SessionAlreadyRunningError(
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
                config: Any = {"configurable": {"thread_id": session.session_id}}

                from eltanix.telemetry.langfuse_tracer import get_langfuse_callback

                langfuse_handler = get_langfuse_callback(
                    session_id=session.session_id,
                    trace_name=f"agent-run:{session.mode}",
                    tags=["eltanix", session.mode],
                    settings=self.settings,
                )
                if langfuse_handler is not None:
                    config["callbacks"] = [langfuse_handler]

                if resume is not None:
                    from langgraph.types import Command

                    entrada: Any = Command(resume=resume)
                elif images or message:
                    if images:
                        partes_msg: list[dict[str, Any]] = [
                            {"type": "text", "text": message or "Analise a imagem anexada."}
                        ]
                        for img in images:
                            partes_msg.append({"type": "image_url", "image_url": {"url": img}})
                        user_content: Any = partes_msg
                    else:
                        user_content = message
                    entrada = {
                        "messages": [{"role": "user", "content": user_content}],
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

                activity_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

                async def _on_activity(act_evt: dict[str, Any]) -> None:
                    await activity_queue.put(act_evt)

                session.context.on_activity = _on_activity

                event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

                async def _run_graph() -> None:
                    try:
                        async for evento in compilado.astream(
                            entrada, config=config, stream_mode="updates"
                        ):
                            for no, atualizacao in evento.items():
                                await event_queue.put(
                                    {"node": no, "update": _serializable(atualizacao)}
                                )
                    except Exception as exc:
                        await event_queue.put({"node": "error", "update": {"message": str(exc)}})
                    finally:
                        await event_queue.put(None)

                graph_task = asyncio.create_task(_run_graph())

                try:
                    graph_done = False
                    while not graph_done or not activity_queue.empty():
                        # Drena micro-atividades pendentes
                        while not activity_queue.empty():
                            act_item = activity_queue.get_nowait()
                            if act_item is not None:
                                yield {"node": "activity", "update": act_item}

                        if graph_done:
                            break

                        get_graph_coro = asyncio.create_task(event_queue.get())
                        get_act_coro = asyncio.create_task(activity_queue.get())

                        done, pending = await asyncio.wait(
                            [get_graph_coro, get_act_coro],
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        for pending_t in pending:
                            pending_t.cancel()

                        for done_t in done:
                            item = done_t.result()
                            if item is None and done_t is get_graph_coro:
                                graph_done = True
                            elif item is not None:
                                if done_t is get_act_coro:
                                    yield {"node": "activity", "update": item}
                                else:
                                    yield item
                                    no = item.get("node")
                                    atualizacao = item.get("update") or {}
                                    if no == "approve":
                                        pendentes = atualizacao.get("pending") or []
                                        await self.update_session_summary(
                                            session.session_id,
                                            pending_count=len(pendentes),
                                            failed_count=max(
                                                0,
                                                int(atualizacao.get("last_failed_call_count") or 0),
                                            ),
                                        )
                                    elif no == "act":
                                        await self.update_session_summary(
                                            session.session_id,
                                            pending_count=0,
                                            failed_count=max(
                                                0,
                                                int(atualizacao.get("last_failed_call_count") or 0),
                                            ),
                                        )
                finally:
                    session.context.on_activity = None
                    if not graph_task.done():
                        graph_task.cancel()
                        # Espera o cancelamento realmente aterrissar antes do
                        # `async with lock:` liberar — sem isto, um cliente
                        # que desconecta e reconecta na hora pode iniciar um
                        # segundo `stream_run()` no mesmo `thread_id` enquanto
                        # esta task ainda está desfazendo a chamada de
                        # ferramenta WRITE/EXEC já aprovada.
                        with suppress(asyncio.CancelledError):
                            await graph_task

                estado = await compilado.aget_state(config) if compilado.checkpointer else None
                if estado is not None:
                    # `estado.tasks[*].interrupts` carrega o payload real passado a
                    # `interrupt()` em `approve()` — já com `diff`/`review` anexados por
                    # `_attach_diffs`/`_attach_review_notes`. `estado.values["pending"]`
                    # é só o que `think()` gravou *antes* de `approve()` rodar (sem
                    # diff/review), porque o checkpoint desse campo é escrito no fim do
                    # nó `think`, e a mutação em `approve()` nunca é persistida de volta
                    # nele. Preferir sempre a versão via `tasks` quando existir.
                    interrupcoes = [
                        interrupcao
                        for tarefa in estado.tasks
                        for interrupcao in getattr(tarefa, "interrupts", []) or []
                    ]
                    if interrupcoes:
                        # Sem isto, o único código que persiste `pending_count`
                        # é o ramo `no == "approve"` acima — mas `approve()`
                        # só emite esse evento quando `pending` já está vazio
                        # (interrupções de verdade não chegam a retornar dali,
                        # ficam paradas em `interrupt()`) — a listagem de
                        # sessões (`GET /api/agent/sessions`) nunca mostrava
                        # quantas ações estavam realmente pendentes.
                        await self.update_session_summary(
                            session.session_id, pending_count=len(interrupcoes)
                        )
                        for interrupcao in interrupcoes:
                            yield {
                                "node": "interrupt",
                                "update": _serializable(interrupcao.value),
                            }
                    else:
                        pendentes_no_estado = estado.values.get("pending") or []
                        if pendentes_no_estado and not estado.values.get("finished", False):
                            await self.update_session_summary(
                                session.session_id, pending_count=len(pendentes_no_estado)
                            )
                            yield {
                                "node": "interrupt",
                                "update": _serializable(
                                    {
                                        "type": "approval_required",
                                        "session_id": session.session_id,
                                        "actions": pendentes_no_estado,
                                        "auto_approved": [],
                                    }
                                ),
                            }
            finally:
                session.context.on_activity = None
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
        config: Any = {"configurable": {"thread_id": session.session_id}}
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
