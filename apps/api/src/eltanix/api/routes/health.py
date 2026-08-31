"""Saúde e catálogo dos provedores — alimenta a tela /settings/providers."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from eltanix.api.deps import AuthDep, EngineDep, SettingsDep
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.router import env_editor, providers_editor, routes_editor
from eltanix.router.adapters.base import DiscoveredModel, DiscoveryError
from eltanix.router.catalog import ModelSpec, RouteProfile

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["health"], dependencies=[AuthDep])

_VALID_STRATEGIES = {"priority", "cost", "latency", "score"}
_VALID_WEIGHT_KEYS = {"health", "cost", "latency", "success_rate", "context_fit"}
_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MODEL_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-./:]{0,127}$")
_VALID_CAPABILITIES = {"chat", "tools", "vision", "prompt_cache", "embedding"}

# (campo no JSON/UI, atributo em Settings, variável no .env, é segredo)
_CREDENTIAL_FIELDS: list[tuple[str, str, str, bool]] = [
    ("ollama_base_url", "ollama_base_url", "OLLAMA_BASE_URL", False),
    ("azure_api_base", "azure_api_base", "AZURE_API_BASE", False),
    ("azure_api_key", "azure_api_key", "AZURE_API_KEY", True),
    ("databricks_host", "databricks_host", "DATABRICKS_HOST", False),
    ("databricks_token", "databricks_token", "DATABRICKS_TOKEN", True),
    ("openai_api_key", "openai_api_key", "OPENAI_API_KEY", True),
    ("anthropic_api_key", "anthropic_api_key", "ANTHROPIC_API_KEY", True),
    ("groq_api_key", "groq_api_key", "GROQ_API_KEY", True),
    ("github_token", "github_token", "GITHUB_TOKEN", True),
    ("firecrawl_api_key", "firecrawl_api_key", "FIRECRAWL_API_KEY", True),
    ("firecrawl_api_url", "firecrawl_api_url", "FIRECRAWL_API_URL", False),
]

# `azure_api_base`/`databricks_host` viajam JUNTO com uma api_key/token real em
# toda chamada ao provedor (ver adapters/azure_foundry.py, adapters/databricks.py)
# — sem essa validação, trocar o host bastaria para fazer o segredo real ser
# enviado para um host arbitrário controlado por quem tiver sessão válida.
_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.azure.com",
    "instance-data",
    "instance-data.ec2.internal",
}
# Nomes de serviço internos do docker-compose que não devem ser alcançáveis
# através de um campo de host de provedor (mesmo o Ollama, que não carrega
# segredo, não deve poder ser usado para sondar os outros serviços).
_INTERNAL_SERVICE_HOSTS = {"postgres", "redis", "minio", "executor", "browser", "api", "web"}


def _resolve_host_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return []
    resolved: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            resolved.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return resolved


def _is_private_or_reserved(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_provider_host_url(
    field_name: str, value: str, *, require_https: bool, allow_private: bool
) -> None:
    """Bloqueia SSRF/exfiltração via host de provedor configurável pela UI.

    Validação em tempo de escrita (best-effort contra DNS rebinding — não há
    pinning de IP nas chamadas subsequentes do litellm, mas isso já barra o
    ataque direto de apontar o host para um servidor do atacante ou para um
    serviço interno do compose)."""
    parsed = urlparse(value)
    esquemas_ok = ("https",) if require_https else ("http", "https")
    if parsed.scheme not in esquemas_ok:
        raise ValueError(f"{field_name}: esquema deve ser {'/'.join(esquemas_ok)}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{field_name}: host inválido")
    lowered = hostname.lower()
    if lowered in _METADATA_HOSTS:
        raise ValueError(f"{field_name}: host bloqueado")
    if lowered in _INTERNAL_SERVICE_HOSTS:
        raise ValueError(f"{field_name}: host bloqueado")
    ips = _resolve_host_ips(hostname)
    if not ips and not allow_private:
        raise ValueError(f"{field_name}: não foi possível resolver o host")
    for ip in ips:
        if str(ip) in _METADATA_HOSTS:
            raise ValueError(f"{field_name}: host bloqueado")
        if not allow_private and _is_private_or_reserved(ip):
            raise ValueError(
                f"{field_name}: aponta para endereço privado/reservado — não permitido"
            )


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
        # Modelo desabilitado por `validate_catalog` (dimensão de embedding
        # incompatível, capability trocada — ver ADR 0017) some silenciosamente
        # do pool: sem isto, o sintoma é só "models_usable" menor do que se
        # esperava, sem dizer qual nem por quê.
        "catalog_issues": [
            {"model": i.model_id, "detail": i.message, "fatal": i.fatal}
            for i in engine.catalog.issues
        ],
    }


@router.get("/health/ready")
async def readiness(request: Request) -> dict[str, Any]:
    """Prontidão para orquestrador (Compose/k8s), separada do `/health` acima —
    aquele é vivacidade + estado do catálogo, este sonda as dependências de
    infraestrutura de verdade.

    Postgres é obrigatório: falhou, a resposta é 503 e o container é marcado
    unhealthy. Redis é opcional por design (ver invariante "falha de serviço
    opcional degrada, não derruba" no CLAUDE.md) — ausente ou fora do ar não
    reprova a prontidão, só aparece como `disabled`/`error` no corpo.
    """
    checks: dict[str, str] = {}

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        log.warning("health.ready.postgres_failed", error=str(exc)[:200])
        checks["postgres"] = "error"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        ) from exc

    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        checks["redis"] = "disabled"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            log.warning("health.ready.redis_failed", error=str(exc)[:200])
            checks["redis"] = "error"

    return {"status": "ready", "checks": checks}


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
        "models": [_model_view(spec, engine) for spec in engine.catalog.models.values()],
        "profiles": _profiles_view(engine),
    }


def _model_view(spec: ModelSpec, engine: EngineDep) -> dict[str, Any]:
    return {
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


def _profiles_view(engine: EngineDep) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "strategy": profile.strategy,
            "models": profile.models,
            "weights": profile.weights,
            "is_default": name == engine.catalog.default_profile,
        }
        for name, profile in engine.catalog.profiles.items()
    ]


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
        "profiles": _profiles_view(engine),
    }


class UpsertProfileRequest(BaseModel):
    strategy: str
    models: list[str] = Field(min_length=1)
    weights: dict[str, float] | None = None

    @field_validator("strategy")
    @classmethod
    def _valida_strategy(cls, value: str) -> str:
        if value not in _VALID_STRATEGIES:
            raise ValueError(f"strategy deve ser um de {sorted(_VALID_STRATEGIES)}")
        return value

    @field_validator("weights")
    @classmethod
    def _valida_weights(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return value
        desconhecidos = set(value) - _VALID_WEIGHT_KEYS
        if desconhecidos:
            raise ValueError(f"pesos desconhecidos: {sorted(desconhecidos)}")
        negativos = [k for k, v in value.items() if v < 0]
        if negativos:
            raise ValueError(f"pesos não podem ser negativos: {sorted(negativos)}")
        return value


@router.put("/providers/profiles/{name}")
async def upsert_profile(
    name: str, payload: UpsertProfileRequest, engine: EngineDep, settings: SettingsDep
) -> dict[str, Any]:
    """Cria um perfil novo ou substitui um existente por completo.

    Não dá pra criar um perfil de roteamento sem que os modelos citados já
    existam no catálogo — apontar pra um id inexistente só falharia depois,
    na hora de rotear de verdade.
    """
    if not _PROFILE_NAME_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de perfil inválido: use letras minúsculas, números, '-' ou '_', "
            "começando com letra (até 32 caracteres).",
        )

    desconhecidos = [m for m in payload.models if engine.catalog.get(m) is None]
    if desconhecidos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modelo(s) desconhecido(s) no catálogo: {', '.join(desconhecidos)}",
        )

    engine.catalog.profiles[name] = RouteProfile(
        name=name,
        strategy=payload.strategy,
        models=list(payload.models),
        weights=dict(payload.weights or {}),
    )

    try:
        data = routes_editor.load(settings.routes_file)
        routes_editor.upsert_profile(
            data, name, strategy=payload.strategy, models=payload.models, weights=payload.weights
        )
        routes_editor.dump(settings.routes_file, data)
    except Exception as exc:  # persistência é best-effort
        log.warning("providers.profile.persist_failed", profile=name, error=str(exc))

    return {"profiles": _profiles_view(engine)}


@router.delete("/providers/profiles/{name}")
async def delete_profile(name: str, engine: EngineDep, settings: SettingsDep) -> dict[str, Any]:
    """Remove um perfil de roteamento.

    Trocar o padrão antes é obrigatório: apagar o perfil que `auto` resolveria
    deixaria todo pedido genérico sem destino até a próxima subida da API.
    """
    if engine.catalog.profile(name) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Perfil desconhecido: {name}"
        )
    if name == engine.catalog.default_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esse é o perfil padrão atual — troque o padrão antes de excluí-lo.",
        )
    if len(engine.catalog.profiles) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não dá pra remover o último perfil de roteamento.",
        )

    del engine.catalog.profiles[name]

    try:
        data = routes_editor.load(settings.routes_file)
        routes_editor.delete_profile(data, name)
        routes_editor.dump(settings.routes_file, data)
    except Exception as exc:  # persistência é best-effort
        log.warning("providers.profile.delete_persist_failed", profile=name, error=str(exc))

    return {"profiles": _profiles_view(engine)}


def _mask_secret(value: str) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "••••"
    return f"••••{value[-4:]}"


def _credentials_view(engine: EngineDep) -> dict[str, Any]:
    """Nunca devolve o valor de um campo-segredo — só se está configurado e os
    últimos 4 caracteres, para o usuário reconhecer qual chave é qual."""
    view: dict[str, Any] = {}
    for json_key, attr, _alias, secret in _CREDENTIAL_FIELDS:
        value = getattr(engine.settings, attr)
        view[json_key] = {
            "configured": bool(value),
            "value": None if secret else value,
            "masked": _mask_secret(value) if secret else None,
        }
    return view


@router.get("/providers/credentials")
async def get_credentials(engine: EngineDep) -> dict[str, Any]:
    return {"credentials": _credentials_view(engine)}


class UpdateCredentialsRequest(BaseModel):
    ollama_base_url: str | None = None
    azure_api_base: str | None = None
    azure_api_key: str | None = None
    databricks_host: str | None = None
    databricks_token: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    github_token: str | None = None
    firecrawl_api_key: str | None = None
    firecrawl_api_url: str | None = None

    @field_validator(
        "ollama_base_url",
        "azure_api_base",
        "azure_api_key",
        "databricks_host",
        "databricks_token",
        "openai_api_key",
        "anthropic_api_key",
        "groq_api_key",
        "github_token",
        "firecrawl_api_key",
        "firecrawl_api_url",
    )
    @classmethod
    def _sem_quebra_de_linha(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("credencial não pode conter quebra de linha")
        return value

    @field_validator("azure_api_base", "databricks_host")
    @classmethod
    def _validar_host_com_segredo_pareado(cls, value: str | None) -> str | None:
        # Estes dois campos viajam junto com uma api_key/token real — exige
        # https e recusa host privado/reservado/interno do compose.
        if value:
            _validate_provider_host_url(
                "azure_api_base/databricks_host", value, require_https=True, allow_private=False
            )
        return value

    @field_validator("ollama_base_url", "firecrawl_api_url")
    @classmethod
    def _validar_ollama_base_url(cls, value: str | None) -> str | None:
        # Sem segredo pareado, mas ainda assim não pode virar uma rota para
        # sondar outros serviços internos do compose ou o metadata endpoint.
        if value:
            _validate_provider_host_url("base_url", value, require_https=False, allow_private=True)
        return value


@router.put("/providers/credentials")
async def update_credentials(
    payload: UpdateCredentialsRequest, engine: EngineDep, settings: SettingsDep
) -> dict[str, Any]:
    """Atualiza credenciais de provedor. Só os campos enviados são tocados —
    campo omitido (`None`) mantém o valor atual; string vazia limpa a chave.

    Aplica na hora: reconstrói a disponibilidade de cada modelo e o router do
    litellm a partir do `engine.settings` já atualizado, sem exigir restart. A
    gravação no `.env` é best-effort, igual ao resto da tela de configuração.
    """
    updates = payload.model_dump(exclude_none=True)
    if updates:
        env_updates: dict[str, str] = {}
        for json_key, attr, alias, _secret in _CREDENTIAL_FIELDS:
            if json_key in updates:
                setattr(engine.settings, attr, updates[json_key])
                env_updates[alias] = updates[json_key]

        engine.resolve_catalog()
        engine.build()

        try:
            env_editor.write_values(settings.env_file_path, env_updates)
        except Exception as exc:  # persistência é best-effort
            log.warning("providers.credentials.persist_failed", error=str(exc))

    return {"credentials": _credentials_view(engine)}


def _discovery_identity(spec: ModelSpec) -> str | None:
    """Chave de comparação contra o catálogo — não é o `id`, que o usuário
    pode ter escolhido livremente na hora de cadastrar o modelo à mão."""
    return spec.endpoint or spec.deployment or spec.model


def _split_discovered(
    catalog: Any, discovered: list[DiscoveredModel]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_identity = {
        (spec.provider, _discovery_identity(spec)): spec.id for spec in catalog.models.values()
    }

    new: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for candidate in discovered:
        raw = candidate.endpoint or candidate.deployment or candidate.model or candidate.raw_name
        existing_id = by_identity.get((candidate.provider, raw))
        payload = {
            "suggested_id": candidate.suggested_id,
            "provider": candidate.provider,
            "raw_name": candidate.raw_name,
            "model": candidate.model,
            "deployment": candidate.deployment,
            "endpoint": candidate.endpoint,
            "mode": candidate.mode,
            "context_window": candidate.context_window,
            "tags": candidate.tags,
            "capabilities": candidate.capabilities,
            "estimated_fields": candidate.estimated_fields,
        }
        if existing_id:
            already.append({**payload, "existing_id": existing_id})
        else:
            new.append(payload)
    return new, already


@router.post("/providers/{provider}/discover")
async def discover_provider_models(provider: str, engine: EngineDep) -> dict[str, Any]:
    """Consulta a API de listagem do provedor e devolve o que ainda não está
    no catálogo. Nunca escreve nada — é só a etapa de revisão; a gravação
    fica a cargo de `discover/confirm`, com o usuário escolhendo o que entra.
    """
    adapter = engine.adapters.get(provider)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Provedor desconhecido: {provider}"
        )

    # A chamada é incondicional de propósito: cada adaptador que suporta
    # descoberta já se guarda contra credencial ausente (devolve [] sem rede),
    # e o default (não suportado) devolve None sem tocar em `self.settings`.
    # Checar credencial antes faria "sem suporte + sem credencial" virar 200
    # em vez de 501 — a falta de suporte é um fato estrutural, independente
    # de credencial estar configurada ou não.
    try:
        discovered = await adapter.discover_models()
    except DiscoveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Descoberta automática não é suportada para '{provider}'.",
        )

    missing = adapter.missing_credentials(ModelSpec(id="__discovery_probe__", provider=provider))
    if missing:
        return {
            "provider": provider,
            "new": [],
            "already_cataloged": [],
            "error": f"credenciais ausentes: {', '.join(missing)}",
        }

    new, already_cataloged = _split_discovered(engine.catalog, discovered)
    return {"provider": provider, "new": new, "already_cataloged": already_cataloged, "error": None}


class DiscoveredModelIn(BaseModel):
    id: str
    model: str | None = None
    deployment: str | None = None
    endpoint: str | None = None
    mode: str | None = None
    context_window: int = Field(default=8192, gt=0)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=lambda: ["chat"])
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _valida_id(cls, value: str) -> str:
        if not _MODEL_ID_RE.match(value):
            raise ValueError(
                "id inválido: use letras, números e '_ - . / :', começando por letra ou número."
            )
        return value

    @field_validator("capabilities")
    @classmethod
    def _valida_capabilities(cls, value: list[str]) -> list[str]:
        desconhecidas = set(value) - _VALID_CAPABILITIES
        if desconhecidas:
            raise ValueError(f"capabilities desconhecidas: {sorted(desconhecidas)}")
        return value


class ConfirmDiscoveryRequest(BaseModel):
    models: list[DiscoveredModelIn] = Field(min_length=1)


@router.post("/providers/{provider}/discover/confirm")
async def confirm_discovered_models(
    provider: str,
    payload: ConfirmDiscoveryRequest,
    engine: EngineDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Grava no catálogo os candidatos que o usuário revisou e confirmou.

    Nunca sobrescreve um `id` já existente — o cliente vê 409 e resolve
    renomeando na tela de revisão; sobrescrever um modelo cadastrado à mão é
    uma operação diferente, fora do escopo desta tela.
    """
    if provider not in engine.adapters:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Provedor desconhecido: {provider}"
        )

    ids = [m.id for m in payload.models]
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ids repetidos no mesmo envio."
        )

    colisoes = [i for i in ids if engine.catalog.get(i) is not None]
    if colisoes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"id(s) já existentes no catálogo: {', '.join(colisoes)}",
        )

    new_specs = [
        ModelSpec(
            id=m.id,
            provider=provider,
            model=m.model,
            deployment=m.deployment,
            endpoint=m.endpoint,
            mode=m.mode,
            context_window=m.context_window,
            tags=m.tags,
            capabilities=m.capabilities or ["chat"],
            enabled=m.enabled,
        )
        for m in payload.models
    ]
    for spec in new_specs:
        engine.catalog.models[spec.id] = spec

    engine.resolve_catalog()
    engine.build()

    try:
        data = providers_editor.load(settings.providers_file)
        providers_editor.append_models(
            data,
            [
                {
                    "id": spec.id,
                    "provider": spec.provider,
                    "model": spec.model,
                    "deployment": spec.deployment,
                    "endpoint": spec.endpoint,
                    "mode": spec.mode,
                    "context_window": spec.context_window,
                    "tags": spec.tags,
                    "capabilities": spec.capabilities,
                    "enabled": spec.enabled,
                }
                for spec in new_specs
            ],
        )
        providers_editor.dump(settings.providers_file, data)
    except Exception as exc:  # persistência é best-effort
        log.warning("providers.discover.persist_failed", provider=provider, error=str(exc))

    return {
        "added": [spec.id for spec in new_specs],
        "models": [_model_view(spec, engine) for spec in engine.catalog.models.values()],
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
