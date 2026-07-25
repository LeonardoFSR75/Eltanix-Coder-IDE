"""Saúde e catálogo dos provedores — alimenta a tela /settings/providers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, status

from sicoobito.api.deps import AuthDep, EngineDep

router = APIRouter(prefix="/api", tags=["health"], dependencies=[AuthDep])


@router.get("/health")
async def health(engine: EngineDep) -> dict[str, Any]:
    usable = engine.catalog.usable_models()
    return {
        "status": "ok",
        "models_total": len(engine.catalog.models),
        "models_usable": len(usable),
        "profiles": sorted(engine.catalog.profiles),
        "cache_enabled": engine.cache.enabled,
        "pricing_updated_at": engine.prices.updated_at,
    }


@router.get("/health/providers")
async def providers_health(engine: EngineDep) -> dict[str, Any]:
    """Sonda todos os modelos em paralelo.

    Sequencial isto levaria segundos por provedor indisponível — cada um espera
    o próprio timeout.
    """
    model_ids = list(engine.catalog.models)
    results = await asyncio.gather(
        *(engine.healthcheck(mid) for mid in model_ids), return_exceptions=True
    )

    checks: list[dict[str, Any]] = []
    for model_id, result in zip(model_ids, results, strict=True):
        if isinstance(result, BaseException):
            checks.append({"model": model_id, "ok": False, "detail": str(result)})
        else:
            checks.append(result)

    healthy = sum(1 for c in checks if c.get("ok"))
    return {
        "healthy": healthy,
        "total": len(checks),
        "providers": checks,
    }


@router.get("/providers")
async def list_providers(engine: EngineDep) -> dict[str, Any]:
    return {
        "models": [
            {
                "id": spec.id,
                "provider": spec.provider,
                "context_window": spec.context_window,
                "tags": spec.tags,
                "capabilities": spec.capabilities,
                "enabled": spec.enabled,
                "available": spec.available,
                "unavailable_reason": spec.unavailable_reason,
                "price": _price_view(engine, spec.id),
            }
            for spec in engine.catalog.models.values()
        ],
        "profiles": [
            {
                "name": name,
                "strategy": profile.strategy,
                "models": profile.models,
                "weights": profile.weights,
                "is_default": name == engine.catalog.default_profile,
            }
            for name, profile in engine.catalog.profiles.items()
        ],
    }


def _price_view(engine: EngineDep, model_id: str) -> dict[str, float | None] | None:
    price = engine.prices.price_of(model_id)
    if price is None:
        return None
    return {
        "input": float(price.input) if price.input is not None else None,
        "output": float(price.output) if price.output is not None else None,
        "cache_read": float(price.cache_read) if price.cache_read is not None else None,
        "cache_write": float(price.cache_write) if price.cache_write is not None else None,
    }


@router.post("/providers/{model_id:path}/reset")
async def reset_circuit(model_id: str, engine: EngineDep) -> dict[str, Any]:
    """Fecha o circuito de um modelo manualmente, sem esperar o cooldown."""
    if engine.catalog.get(model_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo desconhecido: {model_id}",
        )
    await engine.health.reset(model_id)
    return {"model": model_id, "reset": True}


@router.post("/cache/clear")
async def clear_cache(engine: EngineDep) -> dict[str, Any]:
    removed = await engine.cache.clear()
    return {"removed": removed}
