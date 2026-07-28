"""Saúde e catálogo dos provedores — alimenta a tela /settings/providers."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, EngineDep, SettingsDep
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

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


class SetDefaultProfileRequest(BaseModel):
    profile: str = Field(min_length=1)


_DEFAULT_PROFILE_LINE = re.compile(r"^default_profile:\s*.*$", re.MULTILINE)


def _persist_default_profile(routes_file: Path, profile: str) -> None:
    """Atualiza só a chave `default_profile` no routes.yaml.

    Um round-trip via `yaml.safe_dump` reescreveria o arquivo inteiro e
    apagaria todos os comentários que documentam cada perfil; como é um
    escalar único de topo, basta substituir essa linha e preservar o resto.
    """
    text = routes_file.read_text(encoding="utf-8")
    if not _DEFAULT_PROFILE_LINE.search(text):
        raise ValueError("chave default_profile não encontrada em routes.yaml")
    novo_texto = _DEFAULT_PROFILE_LINE.sub(f"default_profile: {profile}", text, count=1)
    routes_file.write_text(novo_texto, encoding="utf-8")


@router.post("/providers/default-profile")
async def set_default_profile(
    payload: SetDefaultProfileRequest, engine: EngineDep, settings: SettingsDep
) -> dict[str, Any]:
    """Troca o perfil padrão (o que responde a `model: "auto"`).

    Some efeito imediato em memória; a gravação em disco é best-effort — se
    falhar (ex.: arquivo somente leitura), a troca continua valendo até a
    próxima subida da API, e o log registra o motivo.
    """
    if engine.catalog.profile(payload.profile) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Perfil desconhecido: {payload.profile}",
        )

    engine.catalog.default_profile = payload.profile
    try:
        _persist_default_profile(settings.routes_file, payload.profile)
    except Exception as exc:  # persistência é best-effort
        log.warning("providers.default_profile.persist_failed", error=str(exc))

    return {
        "default_profile": engine.catalog.default_profile,
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
