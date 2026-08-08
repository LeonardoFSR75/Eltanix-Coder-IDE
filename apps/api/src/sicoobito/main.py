"""Aplicação FastAPI: montagem e ciclo de vida."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from sicoobito import __version__
from sicoobito.agent.runner import AgentRunner
from sicoobito.agent.tools import registry as tool_registry
from sicoobito.api.middleware import CorrelationIdMiddleware
from sicoobito.api.routes import (
    agent_router,
    audit_router,
    auth_router,
    context_router,
    documents_router,
    git_router,
    graphify_router,
    health_router,
    lsp_router,
    lsp_ws_router,
    mcp_router,
    metrics_router,
    notes_router,
    projects_router,
    skills_router,
    telemetry_router,
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
from sicoobito.db.session import init_engine, shutdown_engine
from sicoobito.documents.service import DocumentService
from sicoobito.logging_setup import get_logger, setup_logging
from sicoobito.mcp.manager import MCPManager
from sicoobito.notes.service import NoteService
from sicoobito.optimizer.cache import ResponseCache
from sicoobito.router.budget import BudgetGuard
from sicoobito.router.catalog import load_catalog
from sicoobito.router.engine import RouterEngine
from sicoobito.router.health import HealthTracker
from sicoobito.router.pricing import PriceTable
from sicoobito.sandbox.container import SandboxConfig, SandboxManager
from sicoobito.sandbox.executor import ExecutorConfig, ExecutorSandboxManager
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

    engine = RouterEngine(
        settings=settings,
        catalog=catalog,
        prices=prices,
        health=health,
        cache=cache,
        budget=BudgetGuard(settings),
    )
    engine.build()

    # Buffer de spans de tools/RAG, com persistência opcional em Redis se conectado.
    trace_recorder = TraceRecorder(redis=redis)

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
    skills = SkillService()
    audit = AuditService()

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

    mcp_manager = MCPManager(settings)
    await mcp_manager.connect_all()
    mcp_manager.register_tools(tool_registry)

    # Com EXECUTOR_URL definido, a execução vai por um serviço isolado que é o
    # único com acesso ao daemon do Docker (ver ADR 0002). É o modo usado
    # quando a própria API roda em container. Sem ele, cai no daemon local, que
    # é o que faz sentido rodando direto na máquina de desenvolvimento.
    if settings.executor_url:
        sandboxes = ExecutorSandboxManager(
            ExecutorConfig(
                base_url=settings.executor_url.rstrip("/"),
                token=settings.executor_token,
                image=settings.sandbox_image,
                network=settings.sandbox_network,
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
    app.state.skills = skills
    app.state.audit = audit
    app.state.auth = auth
    app.state.mcp_manager = mcp_manager
    app.state.trace_recorder = trace_recorder
    app.state.projects_root = settings.projects_root
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
        trace_recorder=trace_recorder,
    )
    # O desligamento ordenado abaixo cobre o caso normal; este laço cobre o
    # anormal (kill -9, queda), varrendo containers de execuções anteriores que
    # ninguém mais conhece.
    reaper = asyncio.create_task(sandboxes.run_reaper())

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
        # Containers da sessão não podem sobreviver ao processo que os criou:
        # ficariam órfãos consumindo memória até alguém notar.
        await sandboxes.shutdown()
        await app.state.agent_runner.aclose()
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
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(context_router)
    app.include_router(documents_router)
    app.include_router(notes_router)
    app.include_router(graphify_router)
    app.include_router(skills_router)
    app.include_router(audit_router)
    app.include_router(mcp_router)
    app.include_router(telemetry_router)
    app.include_router(agent_router)
    app.include_router(workspace_router)
    app.include_router(workspace_ws_router)
    app.include_router(projects_router)
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
