"""Carga do catálogo declarativo: providers.yaml, routes.yaml e pricing.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    """Substitui ${VAR} pelo valor do ambiente, recursivamente."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass(slots=True)
class ModelSpec:
    """Um modelo do catálogo, antes de virar rota do litellm."""

    id: str
    provider: str
    model: str | None = None
    deployment: str | None = None
    endpoint: str | None = None
    mode: str | None = None
    context_window: int = 8192
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    enabled: bool = True

    # Preenchidos na resolução pelo adaptador.
    available: bool = False
    unavailable_reason: str | None = None
    litellm_params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_embedding(self) -> bool:
        return "embedding" in self.capabilities

    @property
    def is_chat(self) -> bool:
        return "chat" in self.capabilities

    @property
    def supports_prompt_cache(self) -> bool:
        return "prompt_cache" in self.capabilities

    @property
    def usable(self) -> bool:
        return self.enabled and self.available


@dataclass(slots=True)
class RouteProfile:
    name: str
    strategy: str
    models: list[str]
    weights: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Resilience:
    max_attempts: int = 3
    allowed_fails: int = 5
    cooldown_seconds: int = 60
    cooldown_max_seconds: int = 900
    request_timeout_seconds: int = 300


@dataclass(slots=True)
class Catalog:
    models: dict[str, ModelSpec]
    profiles: dict[str, RouteProfile]
    default_profile: str
    resilience: Resilience

    def get(self, model_id: str) -> ModelSpec | None:
        return self.models.get(model_id)

    def usable_models(self) -> list[ModelSpec]:
        return [m for m in self.models.values() if m.usable]

    def profile(self, name: str) -> RouteProfile | None:
        return self.profiles.get(name)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de configuração ausente: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return _expand_env(yaml.safe_load(fh) or {})


def load_catalog(providers_file: Path, routes_file: Path) -> Catalog:
    providers_raw = _read_yaml(providers_file)
    routes_raw = _read_yaml(routes_file)

    models: dict[str, ModelSpec] = {}
    for entry in providers_raw.get("providers", []):
        spec = ModelSpec(
            id=entry["id"],
            provider=entry["provider"],
            model=entry.get("model"),
            deployment=entry.get("deployment"),
            endpoint=entry.get("endpoint"),
            mode=entry.get("mode"),
            context_window=int(entry.get("context_window", 8192)),
            tags=list(entry.get("tags", [])),
            capabilities=list(entry.get("capabilities", ["chat"])),
            enabled=bool(entry.get("enabled", True)),
        )
        if spec.id in models:
            raise ValueError(f"id duplicado em providers.yaml: {spec.id}")
        models[spec.id] = spec

    profiles: dict[str, RouteProfile] = {}
    for name, cfg in (routes_raw.get("profiles") or {}).items():
        listed = list(cfg.get("models", []))
        unknown = [m for m in listed if m not in models]
        if unknown:
            # Não é fatal: um perfil pode referenciar modelos ainda não cadastrados.
            log.warning("catalog.profile.unknown_models", profile=name, models=unknown)
        profiles[name] = RouteProfile(
            name=name,
            strategy=cfg.get("strategy", "priority"),
            models=[m for m in listed if m in models],
            weights={k: float(v) for k, v in (cfg.get("weights") or {}).items()},
        )

    res_raw = routes_raw.get("resilience") or {}
    resilience = Resilience(
        max_attempts=int(res_raw.get("max_attempts", 3)),
        allowed_fails=int(res_raw.get("allowed_fails", 5)),
        cooldown_seconds=int(res_raw.get("cooldown_seconds", 60)),
        cooldown_max_seconds=int(res_raw.get("cooldown_max_seconds", 900)),
        request_timeout_seconds=int(res_raw.get("request_timeout_seconds", 300)),
    )

    default_profile = routes_raw.get("default_profile", "auto")

    log.info(
        "catalog.loaded",
        models=len(models),
        profiles=len(profiles),
        default_profile=default_profile,
    )
    return Catalog(
        models=models,
        profiles=profiles,
        default_profile=default_profile,
        resilience=resilience,
    )
