"""Carga do catálogo declarativo: providers.yaml, routes.yaml e pricing.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from eltanix.logging_setup import get_logger

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
    # Dimensão do vetor devolvido por um modelo de embedding. Obrigatória para
    # quem tem a capability `embedding`: a coluna `Vector(EMBEDDING_DIM)` do
    # pgvector é de dimensão fixa, e um modelo de dimensão diferente ou estoura
    # o INSERT ou (pior) grava num espaço vetorial incomparável com o resto do
    # índice. Ver `validate_catalog`.
    embedding_dim: int | None = None
    # Prefixos de instrução do modelo de embedding. Modelos treinados com
    # objetivo assimétrico (nomic, BGE, E5) esperam texto diferente ao indexar
    # e ao consultar — `search_document:` contra `search_query:`. Sem eles a
    # consulta é embutida como se fosse mais um documento, e o modelo trabalha
    # fora do regime em que foi treinado.
    embedding_query_prefix: str | None = None
    embedding_document_prefix: str | None = None

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
    def has_embedding_prefixes(self) -> bool:
        return bool(self.embedding_query_prefix or self.embedding_document_prefix)

    def provenance_tag(self, *, prefixes_applied: bool) -> str:
        """Etiqueta gravada em `embedding_model` (ADR 0017).

        Aplicar prefixo muda o espaço vetorial tanto quanto trocar de modelo:
        um vetor gerado com `search_document:` não é comparável com um gerado
        sem. Carregar isso na etiqueta faz o filtro de proveniência que já
        existe descartar os vetores antigos sozinho quando o prefixo é ligado —
        em vez de misturar os dois espaços em silêncio.
        """
        if prefixes_applied and self.has_embedding_prefixes:
            return f"{self.id}#prefixed"
        return self.id

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
class CatalogIssue:
    """Inconsistência encontrada em `validate_catalog`.

    `fatal=True` significa "usar este modelo corromperia dados" — o modelo é
    desabilitado na carga. `fatal=False` é só ruído de configuração, que vira
    log e aparece no health.
    """

    model_id: str
    message: str
    fatal: bool = True

    def __str__(self) -> str:  # pragma: no cover - conveniência de log
        return f"{self.model_id}: {self.message}"


@dataclass(slots=True)
class Catalog:
    models: dict[str, ModelSpec]
    profiles: dict[str, RouteProfile]
    default_profile: str
    resilience: Resilience
    issues: list[CatalogIssue] = field(default_factory=list)

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


# Modelo cujo id anuncia embedding mas não declara a capability: quase sempre
# é engano de cadastro, e o efeito é o modelo cair num pool de chat.
_EMBEDDING_ID_RE = re.compile(r"(^|[/_-])embed", re.IGNORECASE)


def validate_catalog(
    models: dict[str, ModelSpec],
    profiles: dict[str, RouteProfile],
    *,
    expected_embedding_dim: int | None = None,
) -> list[CatalogIssue]:
    """Confere o catálogo contra o que o banco e os perfis conseguem aceitar.

    O caso que motivou isto: `EMBEDDING_DIM=768` (nomic) com um modelo de 1024
    à frente do perfil `embedding`. Nada no caminho quente reclamava — o INSERT
    do vetor é que falhava, no meio de uma indexação, arquivo por arquivo.
    """
    issues: list[CatalogIssue] = []

    for spec in models.values():
        if not spec.enabled:
            continue

        if spec.is_embedding:
            if spec.is_chat:
                issues.append(
                    CatalogIssue(
                        spec.id,
                        "declara `embedding` e `chat` ao mesmo tempo — um pool de chat "
                        "não sabe usar um modelo de embedding",
                        fatal=False,
                    )
                )
            if spec.embedding_dim is None:
                issues.append(
                    CatalogIssue(
                        spec.id,
                        "capability `embedding` sem `embedding_dim` declarado em "
                        "providers.yaml — a dimensão do vetor não pode ser adivinhada",
                    )
                )
            elif (
                expected_embedding_dim is not None and spec.embedding_dim != expected_embedding_dim
            ):
                issues.append(
                    CatalogIssue(
                        spec.id,
                        f"embedding_dim={spec.embedding_dim} incompatível com "
                        f"EMBEDDING_DIM={expected_embedding_dim} (dimensão da coluna pgvector)",
                    )
                )
        elif _EMBEDDING_ID_RE.search(spec.id) and spec.is_chat:
            issues.append(
                CatalogIssue(
                    spec.id,
                    "id de modelo de embedding cadastrado com capability `chat` — "
                    "confira `capabilities` em providers.yaml",
                )
            )

    # Um perfil de embedding com modelo de chat (ou o contrário) só falha na
    # hora do request, com erro do provedor em vez de erro de configuração.
    for profile in profiles.values():
        espera_embedding = profile.name == "embedding"
        for model_id in profile.models:
            spec = models.get(model_id)
            if spec is None or not spec.enabled:
                continue
            if espera_embedding and not spec.is_embedding:
                issues.append(
                    CatalogIssue(
                        model_id,
                        f"listado no perfil `{profile.name}` mas não tem capability `embedding`",
                        fatal=False,
                    )
                )
            elif not espera_embedding and spec.is_embedding and not spec.is_chat:
                issues.append(
                    CatalogIssue(
                        model_id,
                        f"modelo de embedding listado no perfil de chat `{profile.name}`",
                        fatal=False,
                    )
                )

    return issues


def load_catalog(
    providers_file: Path,
    routes_file: Path,
    *,
    expected_embedding_dim: int | None = None,
) -> Catalog:
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
            embedding_dim=(
                int(entry["embedding_dim"]) if entry.get("embedding_dim") is not None else None
            ),
            embedding_query_prefix=(entry.get("embedding_prefixes") or {}).get("query"),
            embedding_document_prefix=(entry.get("embedding_prefixes") or {}).get("document"),
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

    issues = validate_catalog(models, profiles, expected_embedding_dim=expected_embedding_dim)
    for issue in issues:
        if issue.fatal:
            # Desabilitar é fechar a porta pro dano (vetor de dimensão errada
            # entrando no índice) sem derrubar a API inteira por um modelo mal
            # cadastrado. Quem quiser que suba falhando usa ELTANIX_CATALOG_STRICT.
            spec = models.get(issue.model_id)
            if spec is not None:
                spec.enabled = False
                spec.unavailable_reason = issue.message
            log.error("catalog.invalid_model", model=issue.model_id, detail=issue.message)
        else:
            log.warning("catalog.suspect_model", model=issue.model_id, detail=issue.message)

    log.info(
        "catalog.loaded",
        models=len(models),
        profiles=len(profiles),
        default_profile=default_profile,
        issues=len(issues),
        disabled_by_validation=sum(1 for i in issues if i.fatal),
    )
    return Catalog(
        models=models,
        profiles=profiles,
        default_profile=default_profile,
        resilience=resilience,
        issues=issues,
    )
