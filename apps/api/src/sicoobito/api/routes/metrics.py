"""Métricas de token, custo e economia, derivadas do `request_log`.

Toda agregação é feita em SQL sobre a tabela de fatos — não há agregado
materializado que possa divergir do que realmente aconteceu.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import Numeric, case, cast, func, select

from sicoobito.api.deps import AuthDep, EngineDep
from sicoobito.db.models import RequestLog
from sicoobito.db.session import session_scope

router = APIRouter(prefix="/api/metrics", tags=["metrics"], dependencies=[AuthDep])

_COST = cast(RequestLog.cost_usd, Numeric(18, 8))
_SAVED = cast(RequestLog.cost_saved_usd, Numeric(18, 8))


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@router.get("/summary")
async def summary(engine: EngineDep, days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    since = _since(days)

    async with session_scope() as session:
        row = (
            await session.execute(
                select(
                    func.count(RequestLog.id).label("requests"),
                    func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
                    func.coalesce(func.sum(RequestLog.completion_tokens), 0),
                    func.coalesce(func.sum(RequestLog.cache_read_tokens), 0),
                    func.coalesce(func.sum(_COST), 0),
                    func.coalesce(func.sum(_SAVED), 0),
                    func.coalesce(func.sum(RequestLog.tokens_saved), 0),
                    func.coalesce(
                        func.sum(case((RequestLog.cache_hit.is_(True), 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((RequestLog.status == "error", 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((RequestLog.cost_known.is_(False), 1), else_=0)), 0
                    ),
                    func.avg(RequestLog.latency_ms),
                ).where(RequestLog.created_at >= since)
            )
        ).one()

    (
        requests,
        prompt_tokens,
        completion_tokens,
        cache_read_tokens,
        cost,
        saved_cost,
        tokens_saved,
        cache_hits,
        errors,
        unpriced,
        avg_latency,
    ) = row

    budget = await engine.budget.status()

    return {
        "window_days": days,
        "requests": int(requests),
        "errors": int(errors),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cache_read_tokens": int(cache_read_tokens),
        "total_tokens": int(prompt_tokens) + int(completion_tokens),
        "cost_usd": float(cost),
        "avg_latency_ms": int(avg_latency) if avg_latency is not None else None,
        "cache_hits": int(cache_hits),
        "cache_hit_rate": round(int(cache_hits) / int(requests), 4) if requests else 0.0,
        "savings": {
            "tokens_saved": int(tokens_saved),
            "cost_saved_usd": float(saved_cost),
        },
        # Requests cujo modelo não está em pricing.yaml: o custo total acima é um
        # piso, não o valor final.
        "unpriced_requests": int(unpriced),
        "budget": {
            "daily_spent_usd": float(budget.daily_spent),
            "daily_limit_usd": budget.daily_limit,
            "monthly_spent_usd": float(budget.monthly_spent),
            "monthly_limit_usd": budget.monthly_limit,
            "hard_stop": budget.hard_stop,
        },
    }


@router.get("/timeseries")
async def timeseries(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    since = _since(days)
    day = func.date_trunc("day", RequestLog.created_at).label("day")

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    day,
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
                    func.coalesce(func.sum(RequestLog.completion_tokens), 0),
                    func.coalesce(func.sum(_COST), 0),
                    func.coalesce(func.sum(_SAVED), 0),
                )
                .where(RequestLog.created_at >= since)
                .group_by(day)
                .order_by(day)
            )
        ).all()

    return {
        "points": [
            {
                "day": d.date().isoformat(),
                "requests": int(reqs),
                "prompt_tokens": int(pt),
                "completion_tokens": int(ct),
                "cost_usd": float(cost),
                "cost_saved_usd": float(saved),
            }
            for d, reqs, pt, ct, cost, saved in rows
        ]
    }


@router.get("/by-model")
async def by_model(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    since = _since(days)

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    RequestLog.resolved_model,
                    RequestLog.provider,
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
                    func.coalesce(func.sum(RequestLog.completion_tokens), 0),
                    func.coalesce(func.sum(_COST), 0),
                    func.avg(RequestLog.latency_ms),
                    func.coalesce(
                        func.sum(case((RequestLog.status == "error", 1), else_=0)), 0
                    ),
                )
                .where(RequestLog.created_at >= since, RequestLog.resolved_model.is_not(None))
                .group_by(RequestLog.resolved_model, RequestLog.provider)
                .order_by(func.sum(_COST).desc())
            )
        ).all()

    return {
        "models": [
            {
                "model": model,
                "provider": provider,
                "requests": int(reqs),
                "prompt_tokens": int(pt),
                "completion_tokens": int(ct),
                "total_tokens": int(pt) + int(ct),
                "cost_usd": float(cost),
                "avg_latency_ms": int(latency) if latency is not None else None,
                "errors": int(errors),
            }
            for model, provider, reqs, pt, ct, cost, latency, errors in rows
        ]
    }


@router.get("/by-source")
async def by_source(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """Gasto por ferramenta cliente — responde 'quem está consumindo meu orçamento'."""
    since = _since(days)

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    RequestLog.source,
                    func.count(RequestLog.id),
                    func.coalesce(
                        func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens), 0
                    ),
                    func.coalesce(func.sum(_COST), 0),
                )
                .where(RequestLog.created_at >= since)
                .group_by(RequestLog.source)
                .order_by(func.sum(_COST).desc())
            )
        ).all()

    return {
        "sources": [
            {
                "source": source,
                "requests": int(reqs),
                "total_tokens": int(tokens),
                "cost_usd": float(cost),
            }
            for source, reqs, tokens, cost in rows
        ]
    }


@router.get("/savings")
async def savings(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """Economia por técnica.

    É isto que separa otimização de token de fé: cada engine aparece com o
    número que produziu, e a que não aparecer não está justificando o custo de
    existir.
    """
    since = _since(days)

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(RequestLog.savings_breakdown, RequestLog.resolved_model).where(
                    RequestLog.created_at >= since,
                    RequestLog.savings_breakdown.is_not(None),
                )
            )
        ).all()

        cache_hits, cache_tokens, cache_cost = (
            await session.execute(
                select(
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(RequestLog.tokens_saved), 0),
                    func.coalesce(func.sum(_SAVED), 0),
                ).where(RequestLog.created_at >= since, RequestLog.cache_hit.is_(True))
            )
        ).one()

        por_complexidade = (
            await session.execute(
                select(
                    RequestLog.complexity,
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(_COST), 0),
                )
                .where(RequestLog.created_at >= since, RequestLog.complexity.is_not(None))
                .group_by(RequestLog.complexity)
            )
        ).all()

    por_tecnica: dict[str, int] = {}
    for breakdown, _model in rows:
        for tecnica, tokens in (breakdown or {}).items():
            por_tecnica[tecnica] = por_tecnica.get(tecnica, 0) + int(tokens)

    # O cache é contabilizado à parte porque economiza a chamada inteira, não
    # apenas tokens de input.
    por_tecnica["cache_exato"] = por_tecnica.get("cache_exato", 0) + int(cache_tokens)

    return {
        "window_days": days,
        "by_technique": [
            {"technique": nome, "tokens_saved": tokens}
            for nome, tokens in sorted(por_tecnica.items(), key=lambda kv: -kv[1])
            if tokens > 0
        ],
        "cache": {
            "hits": int(cache_hits),
            "tokens_saved": int(cache_tokens),
            "cost_saved_usd": float(cache_cost),
        },
        "by_complexity": [
            {"complexity": nivel, "requests": int(qtd), "cost_usd": float(custo)}
            for nivel, qtd, custo in por_complexidade
        ],
    }


@router.get("/recent")
async def recent(
    limit: int = Query(default=50, ge=1, le=500),
    project: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)
    if project:
        stmt = stmt.where(RequestLog.project_slug == project)
    async with session_scope() as session:
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "requests": [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "source": r.source,
                "requested_model": r.requested_model,
                "resolved_model": r.resolved_model,
                "provider": r.provider,
                "profile": r.profile,
                "status": r.status,
                "error_type": r.error_type,
                "stream": r.stream,
                "latency_ms": r.latency_ms,
                "ttft_ms": r.ttft_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": float(r.cost_usd),
                "cost_known": r.cost_known,
                "cache_hit": r.cache_hit,
                "usage_estimated": r.usage_estimated,
                "fallback_from": r.fallback_from,
            }
            for r in rows
        ]
    }
