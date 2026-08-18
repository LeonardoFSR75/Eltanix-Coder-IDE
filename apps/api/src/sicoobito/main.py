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

from sicoobito import __version__
from sicoobito.agent.coordinator import AgentCoordinator
from sicoobito.agent.runner import AgentRunner
from sicoobito.agent.tools import registry as tool_registry
from sicoobito.api.middleware import CorrelationIdMiddleware
from sicoobito.api.routes import (
    agent_router,
    approval_policy_router,
    audit_router,
    auth_router,
    browser_router,
    browser_ws_router,
    containers_router,
    context_router,
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
from sicoobito.api.tickets import TicketStore
from sicoobito.api.v1 import router as openai_router
from sicoobito.audit.service import AuditService
from sicoobito.auth.service import AuthService
from sicoobito.browser.client import BrowserConfig
from sicoobito.config import get_settings
from sicoobito.context.indexer import ContextIndexer
from sicoobito.db.session import init_engine, session_scope, shutdown_engine
from sicoobito.documents.service import DocumentService
from sicoobito.extensions.manager import get_extensions_manager
from sicoobito.firecrawl.service import FirecrawlService
from sicoobito.logging_setup import get_logger, setup_logging
from sicoobito.mcp.manager import MCPManager
from sicoobito.notes.service import NoteService
from sicoobito.optimizer.cache import ResponseCache
from sicoobito.optimizer.semantic_cache import SemanticCache
from sicoobito.router.budget import BudgetGuard
from sicoobito.router.catalog import load_catalog
from sicoobito.router.engine import RouterEngine
from sicoobito.router.health import HealthTracker
from sicoobito.router.pricing import PriceTable
from sicoobito.sandbox.container import SandboxConfig, SandboxManager
from sicoobito.sandbox.executor import ExecutorConfig, ExecutorSandboxManager
from sicoobito.skills.seed import seed_agent_skills
from sicoobito.skills.service import SkillService
from sicoobito.storage.blob import BlobStore
from sicoobito.telemetry.tracer import TraceRecorder

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
            detail="SICOOBITO_API_KEY vazia — só login de usuário autentica a UI web.",
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
    try:
        imported_skills = await seed_agent_skills(Path(".agents"))
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
            hint="defina SICOOBITO_ADMIN_PASSWORD no .env para fixar a senha do primeiro login",
        )
    await auth.ensure_seed_user(username=settings.admin_username, password=admin_password)
    await auth.purge_expired_sessions()

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
    app.state.agent_runner = AgentRunner(
        settings=settings,
        engine=engine,
        indexer=indexer,
        sandboxes=sandboxes,
        browser_config=browser_config,
        documents=documents,
        notes=notes,
        skills=skills,
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
    zombie_session_reaper = asyncio.create_task(
        app.state.agent_runner.run_zombie_session_reaper()
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
        title="SicoobitoCode",
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

    app.include_router(openai_router)
    app.include_router(auth_router)
    app.include_router(browser_router)
    app.include_router(browser_ws_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(context_router)
    app.include_router(documents_router)
    app.include_router(extensions_router)
    app.include_router(firecrawl_router)
    app.include_router(notes_router)
    app.include_router(graphify_router)
    app.include_router(skills_router)
    app.include_router(audit_router)
    app.include_router(mcp_router)
    app.include_router(telemetry_router)
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
            "name": "SicoobitoCode",
            "version": __version__,
            "openai_base_url": "/v1",
            "docs": "/docs",
        }

    return app


app = create_app()
