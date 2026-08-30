"""Aplicação FastAPI: montagem e ciclo de vida."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from eltanix import __version__
from eltanix.agent.coordinator import AgentCoordinator
from eltanix.agent.custom_modes import CustomModeService
from eltanix.agent.runner import AgentRunner
from eltanix.agent.snapshot_store import SnapshotService, run_snapshot_prune_reaper
from eltanix.agent.tools import registry as tool_registry
from eltanix.analytics.worker import run_analytics_batch_reaper
from eltanix.api.errors import register_error_handlers
from eltanix.api.middleware import CorrelationIdMiddleware
from eltanix.api.routes import (
    agent_router,
    analytics_router,
    approval_policy_router,
    audit_router,
    auth_router,
    browser_router,
    browser_ws_router,
    containers_router,
    context_router,
    context_rules_router,
    custom_modes_router,
    documents_router,
    extensions_router,
    firecrawl_router,
    git_router,
    graphify_router,
    health_router,
    lsp_router,
    lsp_ws_router,
    mcp_router,
    metrics_router,
    notes_router,
    packages_router,
    projects_router,
    security_router,
    skills_router,
    telemetry_router,
    trello_router,
    workspace_router,
    workspace_ws_router,
)
from eltanix.api.routes.browser import run_panel_client_purge_reaper
from eltanix.api.tickets import TicketStore
from eltanix.api.v1 import router as openai_router
from eltanix.audit.service import AuditService
from eltanix.auth.service import AuthService
from eltanix.browser.client import BrowserConfig
from eltanix.browser.replay import run_replay_purge_reaper
from eltanix.config import get_settings
from eltanix.context.indexer import ContextIndexer
from eltanix.db.session import init_engine, session_scope, shutdown_engine
from eltanix.documents.service import DocumentService
from eltanix.extensions.manager import get_extensions_manager
from eltanix.firecrawl.service import FirecrawlService
from eltanix.logging_setup import get_logger, setup_logging
from eltanix.mcp.manager import MCPManager
from eltanix.notes.service import NoteService
from eltanix.optimizer.cache import ResponseCache
from eltanix.optimizer.semantic_cache import SemanticCache
from eltanix.router.budget import BudgetGuard
from eltanix.router.catalog import load_catalog
from eltanix.router.engine import RouterEngine
from eltanix.router.health import HealthTracker
from eltanix.router.pricing import PriceTable
from eltanix.sandbox.container import SandboxConfig, SandboxManager
from eltanix.sandbox.executor import ExecutorConfig, ExecutorSandboxManager
from eltanix.skills.seed import seed_agent_skills
from eltanix.skills.service import SkillService
from eltanix.storage.blob import BlobStore
from eltanix.telemetry.tracer import TraceRecorder

log = get_logger(__name__)


async def _connect_redis(url: str) -> Redis | None:
    """Redis é opcional: sem ele, o gateway perde cache e breaker, mas responde."""
    try:
        client = Redis.from_url(url, decode_responses=True)
        await client.ping()
        log.info("redis.connected", url=url.split("@")[-1])
        return client
    except Exception as exc:
        log.warning("redis.unavailable", error=str(exc), impact="sem cache nem circuit breaker")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    if not settings.api_key:
        log.info(
            "auth.no_service_key",
            detail="ELTANIX_API_KEY vazia — só login de usuário autentica a UI web.",
        )

    init_engine(settings.database_url)
    redis = await _connect_redis(settings.redis_url)

    catalog = load_catalog(settings.providers_file, settings.routes_file)
    prices = PriceTable.load(settings.pricing_file)
    health = HealthTracker(redis, catalog.resilience)
    cache = ResponseCache(
        redis,
        enabled=settings.cache_enabled,
        ttl_seconds=settings.cache_ttl_seconds,
        only_deterministic=settings.cache_only_deterministic,
    )
    # Construção em duas fases: `SemanticCache` precisa chamar
    # `RouterEngine.embed()`, mas é uma dependência do próprio `RouterEngine`
    # (usado dentro de `complete()`) — monta sem a função de embed, injeta
    # depois que `engine` existe.
    semantic_cache = SemanticCache(
        redis_cache=cache,
        enabled=settings.semantic_cache_enabled,
        embedding_profile=settings.embedding_profile,
        max_cosine_distance=settings.semantic_cache_max_cosine_distance,
        ttl_seconds=settings.semantic_cache_ttl_seconds,
        excluded_sources=settings.semantic_cache_excluded_sources,
    )

    engine = RouterEngine(
        settings=settings,
        catalog=catalog,
        prices=prices,
        health=health,
        cache=cache,
        budget=BudgetGuard(settings),
        semantic_cache=semantic_cache,
    )
    engine.build()
    semantic_cache.set_embed_fn(engine.embed)

    # Buffer de spans de tools/RAG, com persistência opcional em Redis se conectado.
    trace_recorder = TraceRecorder(redis=redis)

    # Coordenação de orquestração multiagente (ver ADR 0004) — `None` sem
    # Redis conectado, o que faz `spawn_agent` falhar fechado (diferente do
    # resto da plataforma, que degrada pra "mais lento": aqui não há fonte de
    # verdade alternativa pra quem é filho de quem).
    agent_coordinator = AgentCoordinator(redis, ttl_seconds=settings.agent_coordination_ttl_seconds)

    indexer = ContextIndexer(settings=settings, engine=engine, trace_recorder=trace_recorder)

    blob = BlobStore(settings)
    try:
        await blob.ensure_bucket()
    except Exception as exc:
        # Mesmo espírito do Redis opcional acima: sem MinIO no ar, o RAG de
        # documentos fica indisponível, mas o resto da plataforma não trava.
        log.warning(
            "blob.unavailable", error=str(exc)[:200], impact="upload de documentos indisponível"
        )
    documents = DocumentService(
        settings=settings, engine=engine, blob=blob, trace_recorder=trace_recorder
    )
    notes = NoteService(settings=settings, engine=engine, trace_recorder=trace_recorder)
    firecrawl = FirecrawlService(settings=settings, engine=engine)
    skills = SkillService()
    custom_modes = CustomModeService()
    snapshots = SnapshotService()
    try:
        imported_skills = await seed_agent_skills(
            Path(".agents"), engine=engine, embedding_profile=settings.embedding_profile
        )
        if imported_skills > 0:
            log.info("skills.agent_skills.seeded", count=imported_skills)
    except Exception as exc:
        log.warning("skills.agent_skills.seed_failed", error=str(exc))
    audit = AuditService()

    # `get_extensions_manager()`, não `ExtensionsManager()` direto: é o mesmo
    # singleton que `api/routes/extensions.py` e `api/routes/lsp.py` ainda
    # buscam por conta própria — instanciar de novo aqui criaria uma segunda
    # cópia nunca hidratada do Postgres.
    extensions_manager = get_extensions_manager()
    extensions_manager.configure_redis(redis)
    try:
        async with session_scope() as session:
            await extensions_manager.hydrate(session)
    except Exception as exc:
        # Mesmo espírito do Redis/MinIO opcionais: sem o overlay do Postgres,
        # o catálogo ainda funciona com os defaults estáticos em memória.
        log.warning("extensions.hydrate_failed", error=str(exc)[:200])

    auth = AuthService()
    admin_password = settings.admin_password
    if not admin_password:
        # Sem senha fixada, gera uma por processo — só é de fato usada na
        # primeira subida (ensure_seed_user não faz nada se já existe
        # usuário); nas seguintes é ruído barato e descartado.
        admin_password = secrets.token_urlsafe(12)
        # `generated_password`, não `password`: o processor de redação de
        # `logging_setup.py` mascara qualquer campo chamado `password` — o
        # ponto inteiro deste log é o operador conseguir LER a senha aqui.
        log.warning(
            "auth.seed_user.generated_password",
            username=settings.admin_username,
            generated_password=admin_password,
            hint="defina ELTANIX_ADMIN_PASSWORD no .env para fixar a senha do primeiro login",
        )
    await auth.ensure_seed_user(username=settings.admin_username, password=admin_password)
    await auth.purge_expired_sessions()

    # F-7: segredo TOTP cifrado em repouso só quando ELTANIX_MFA_SECRET_KEY
    # existe. Avisa alto se há MFA configurado sem a chave (o segredo está em
    # claro no banco) — silencioso para quem não usa 2º fator.
    if not auth.mfa_secret_encrypted:
        try:
            if await auth.any_mfa_configured():
                log.warning(
                    "auth.mfa.secret_key_missing",
                    impact="segredo TOTP gravado em claro no banco",
                    hint="defina ELTANIX_MFA_SECRET_KEY no .env para cifrá-lo (F-7)",
                )
        except Exception as exc:  # sem banco no boot não deve derrubar o app
            log.warning("auth.mfa.secret_key_check_failed", error=str(exc)[:200])

    mcp_manager = MCPManager(settings)
    await mcp_manager.connect_all()
    mcp_manager.register_tools(tool_registry)

    # Com EXECUTOR_URL definido, a execução vai por um serviço isolado que é o
    # único com acesso ao daemon do Docker (ver ADR 0002). É o modo usado
    # quando a própria API roda em container. Sem ele, cai no daemon local, que
    # é o que faz sentido rodando direto na máquina de desenvolvimento.
    sandboxes: SandboxManager | ExecutorSandboxManager
    if settings.executor_url:
        sandboxes = ExecutorSandboxManager(
            ExecutorConfig(
                base_url=settings.executor_url.rstrip("/"),
                token=settings.executor_token,
                timeout_seconds=settings.sandbox_timeout_seconds,
                max_concurrent=settings.sandbox_max_concurrent,
            )
        )
        log.info("sandbox.mode", mode="executor", url=settings.executor_url)
    else:
        sandboxes = SandboxManager(
            SandboxConfig(
                image=settings.sandbox_image,
                memory_limit=settings.sandbox_memory,
                network_enabled=settings.sandbox_network,
                timeout_seconds=settings.sandbox_timeout_seconds,
                max_concurrent=settings.sandbox_max_concurrent,
            )
        )
        log.info("sandbox.mode", mode="local")

    # Igual ao executor: vazio desliga a ferramenta (ela responde
    # "indisponível" em vez de tentar falar com uma URL vazia).
    browser_config = (
        BrowserConfig(base_url=settings.browser_url.rstrip("/"), token=settings.browser_token)
        if settings.browser_url
        else None
    )

    app.state.engine = engine
    app.state.redis = redis
    app.state.tickets = TicketStore(redis)
    app.state.indexer = indexer
    app.state.sandboxes = sandboxes
    app.state.blob = blob
    app.state.documents = documents
    app.state.notes = notes
    app.state.firecrawl = firecrawl
    app.state.skills = skills
    app.state.custom_modes = custom_modes
    app.state.snapshots = snapshots
    app.state.extensions_manager = extensions_manager
    app.state.audit = audit
    app.state.auth = auth
    app.state.mcp_manager = mcp_manager
    app.state.trace_recorder = trace_recorder
    app.state.agent_coordinator = agent_coordinator
    app.state.projects_root = settings.projects_root
    app.state.browser_config = browser_config
    # Cliente HTTP próprio do painel manual do IDE — separado do que o
    # `AgentRunner` mantém internamente (`_get_browser_http`) porque as duas
    # origens de sessão (agente vs. painel) têm ciclos de vida distintos.
    app.state.browser_http = httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=30)
    )
    # Uma instância de `BrowserClient` por sessão de painel, reaproveitada entre
    # requisições HTTP (ver `api/routes/browser.py::_client`) — sem isto, cada
    # clique no painel manual pagava um `POST /sessions` extra antes da própria
    # ação, porque uma instância nova sempre nasce com `_started=False`.
    app.state.browser_panel_clients = {}
    # Última vez que cada `BrowserClient` do painel foi usado — só para
    # `run_panel_client_purge_reaper` saber quais entradas ociosas descartar
    # (item 11 do plano de robustez do navegador interno).
    app.state.browser_panel_client_last_used = {}
    app.state.agent_runner = AgentRunner(
        settings=settings,
        engine=engine,
        indexer=indexer,
        sandboxes=sandboxes,
        browser_config=browser_config,
        documents=documents,
        notes=notes,
        skills=skills,
        custom_modes=custom_modes,
        snapshots=snapshots,
        audit=audit,
        firecrawl=firecrawl,
        extensions_manager=extensions_manager,
        trace_recorder=trace_recorder,
        coordinator=agent_coordinator,
        blob=blob,
        redis=redis,
    )
    # O desligamento ordenado abaixo cobre o caso normal; este laço cobre o
    # anormal (kill -9, queda), varrendo containers de execuções anteriores que
    # ninguém mais conhece.
    reaper = asyncio.create_task(sandboxes.run_reaper())
    session_purge_reaper = asyncio.create_task(auth.run_session_purge_reaper())
    zombie_session_reaper = asyncio.create_task(app.state.agent_runner.run_zombie_session_reaper())
    replay_purge_reaper = asyncio.create_task(run_replay_purge_reaper(blob=blob, redis=redis))
    panel_client_purge_reaper = asyncio.create_task(run_panel_client_purge_reaper(app.state))
    analytics_batch_reaper = asyncio.create_task(run_analytics_batch_reaper(engine))
    snapshot_prune_reaper = asyncio.create_task(
        run_snapshot_prune_reaper(snapshots, retention_days=settings.agent_snapshot_retention_days)
    )

    log.info(
        "app.started",
        version=__version__,
        projects_root=str(settings.effective_projects_root),
    )

    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        session_purge_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await session_purge_reaper
        zombie_session_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await zombie_session_reaper
        replay_purge_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await replay_purge_reaper
        panel_client_purge_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await panel_client_purge_reaper
        analytics_batch_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await analytics_batch_reaper
        snapshot_prune_reaper.cancel()
        with suppress(asyncio.CancelledError):
            await snapshot_prune_reaper
        # Containers da sessão não podem sobreviver ao processo que os criou:
        # ficariam órfãos consumindo memória até alguém notar.
        await sandboxes.shutdown()
        await app.state.agent_runner.aclose()
        await app.state.browser_http.aclose()
        await mcp_manager.disconnect_all()
        if redis is not None:
            await redis.aclose()
        await shutdown_engine()
        log.info("app.stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Eltanix Coder IDE",
        description=(
            "Gateway multi-modelo local-first com contabilidade de custo. "
            "Expõe API compatível com a OpenAI em /v1."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)

    app.include_router(openai_router)
    app.include_router(auth_router)
    app.include_router(browser_router)
    app.include_router(browser_ws_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(context_router)
    app.include_router(context_rules_router)
    app.include_router(custom_modes_router)
    app.include_router(documents_router)
    app.include_router(extensions_router)
    app.include_router(firecrawl_router)
    app.include_router(notes_router)
    app.include_router(graphify_router)
    app.include_router(skills_router)
    app.include_router(audit_router)
    app.include_router(mcp_router)
    app.include_router(telemetry_router)
    app.include_router(analytics_router)
    app.include_router(agent_router)
    app.include_router(approval_policy_router)
    app.include_router(workspace_router)
    app.include_router(workspace_ws_router)
    app.include_router(projects_router)
    app.include_router(security_router)
    app.include_router(packages_router)
    app.include_router(trello_router)
    app.include_router(containers_router)
    app.include_router(git_router)

    app.include_router(lsp_router)
    app.include_router(lsp_ws_router)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {
            "name": "Eltanix Coder IDE",
            "version": __version__,
            "openai_base_url": "/v1",
            "docs": "/docs",
        }

    return app


app = create_app()
