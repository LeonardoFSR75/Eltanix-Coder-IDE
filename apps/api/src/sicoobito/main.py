"""Aplicação FastAPI: montagem e ciclo de vida."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from sicoobito import __version__
from sicoobito.api.routes import health_router, metrics_router
from sicoobito.api.v1 import router as openai_router
from sicoobito.config import get_settings
from sicoobito.db.session import init_engine, shutdown_engine
from sicoobito.logging_setup import get_logger, setup_logging
from sicoobito.optimizer.cache import ResponseCache
from sicoobito.router.budget import BudgetGuard
from sicoobito.router.catalog import load_catalog
from sicoobito.router.engine import RouterEngine
from sicoobito.router.health import HealthTracker
from sicoobito.router.pricing import PriceTable

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
        log.warning(
            "auth.disabled",
            detail="SICOOBITO_API_KEY vazia — a API aceita qualquer chamada local.",
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

    app.state.engine = engine
    app.state.redis = redis
    log.info("app.started", version=__version__)

    try:
        yield
    finally:
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

    app.include_router(openai_router)
    app.include_router(health_router)
    app.include_router(metrics_router)

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
