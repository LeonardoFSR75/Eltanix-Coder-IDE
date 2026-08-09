"""Motor de roteamento — a única porta de saída para LLM (ver ADR 0001).

O litellm entra aqui como biblioteca (`litellm.Router`), não como proxy: o
fallback, a contabilidade de custo e o cache precisam ficar no nosso processo.
O `num_retries` do litellm fica em zero de propósito — quem decide reencaminhar
é a `RoutingPolicy`, que sabe do circuit breaker e do custo de cada candidato.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# Evita a busca da tabela de preços remota do litellm na importação: este é um
# produto local-first e não deve depender da rede para subir.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm import Router as LiteLLMRouter

from sicoobito.config import Settings
from sicoobito.logging_setup import get_logger
from sicoobito.optimizer.cache import ResponseCache

# Alias explícito: `router.errors` também exporta um `classify`, que recebe uma
# exceção. Importar os dois com o mesmo nome faria o segundo sobrescrever o
# primeiro silenciosamente.
from sicoobito.optimizer.complexity import classify as classify_complexity
from sicoobito.optimizer.compressor import ContextCompressor
from sicoobito.optimizer.tokens import count_text, estimate_prompt_tokens
from sicoobito.router.adapters import ProviderAdapter, build_adapters
from sicoobito.router.budget import BudgetGuard
from sicoobito.router.catalog import Catalog, ModelSpec
from sicoobito.router.errors import (
    AllCandidatesFailedError,
    FailureKind,
    NoCandidatesError,
    classify,
    extract_failed_tool_call,
)
from sicoobito.router.health import HealthTracker
from sicoobito.router.policy import RoutingPolicy
from sicoobito.router.pricing import PriceTable, Usage
from sicoobito.router.telemetry import TelemetryEntry, record

log = get_logger(__name__)

litellm.drop_params = True  # parâmetros não suportados são descartados, não fatais
litellm.suppress_debug_info = True

# Provedores que falam o dialeto OpenAI e aceitam `stream_options`.
_OPENAI_DIALECT = {"openai", "azure_foundry"}


def _synthetic_tool_call_payload(nome: str, argumentos: dict[str, Any]) -> dict[str, Any]:
    """Monta um payload no formato de `choices[0].message.tool_calls` a partir
    de uma function-call recuperada de um erro `tool_use_failed` (ver
    `router.errors.extract_failed_tool_call`) — o resto do pipeline (agent/
    graph.py) não sabe que essa chamada não veio direto do provedor."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_recovered_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {"name": nome, "arguments": json.dumps(argumentos)},
                        }
                    ],
                }
            }
        ]
    }


@dataclass(slots=True)
class CompletionResult:
    payload: dict[str, Any]
    model_id: str
    provider: str
    usage: Usage
    cost_usd: Decimal
    cost_known: bool
    latency_ms: int
    cache_hit: bool = False
    fallback_from: list[str] = field(default_factory=list)
    attempts: int = 1


class RouterEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        catalog: Catalog,
        prices: PriceTable,
        health: HealthTracker,
        cache: ResponseCache,
        budget: BudgetGuard,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.prices = prices
        self.health = health
        self.cache = cache
        self.budget = budget
        self.compressor = compressor or ContextCompressor(enabled=settings.compression_enabled)
        self.adapters: dict[str, ProviderAdapter] = build_adapters(settings)
        self.policy = RoutingPolicy(catalog, prices, health)
        self._router: LiteLLMRouter | None = None

    # ── Construção ──────────────────────────────────────────────────────────

    def resolve_catalog(self) -> None:
        """Resolve credenciais e parâmetros de cada modelo do catálogo."""
        for spec in self.catalog.models.values():
            adapter = self.adapters.get(spec.provider)
            if adapter is None:
                spec.available = False
                spec.unavailable_reason = f"provedor sem adaptador: {spec.provider}"
                log.warning("router.adapter.missing", model=spec.id, provider=spec.provider)
                continue
            adapter.resolve(spec)

        usable = self.catalog.usable_models()
        log.info(
            "router.catalog.resolved",
            usable=len(usable),
            total=len(self.catalog.models),
            unavailable=[m.id for m in self.catalog.models.values() if not m.usable],
        )

    def build(self) -> None:
        self.resolve_catalog()
        model_list = [
            {
                "model_name": spec.id,
                "litellm_params": {
                    **spec.litellm_params,
                    "timeout": self.catalog.resilience.request_timeout_seconds,
                },
                "model_info": {"id": spec.id, "max_input_tokens": spec.context_window},
            }
            for spec in self.catalog.usable_models()
        ]

        if not model_list:
            log.warning("router.build.empty")

        self._router = LiteLLMRouter(
            model_list=model_list,
            # Retry e fallback são nossos: o litellm não conhece o breaker nem
            # a ordenação por custo/latência da RoutingPolicy.
            num_retries=0,
            timeout=self.catalog.resilience.request_timeout_seconds,
            routing_strategy="simple-shuffle",
            set_verbose=False,
        )
        log.info("router.built", routes=len(model_list))

    @property
    def litellm_router(self) -> LiteLLMRouter:
        if self._router is None:
            raise RuntimeError("RouterEngine.build() não foi chamado.")
        return self._router

    # ── Otimização ──────────────────────────────────────────────────────────

    async def _optimize(
        self, params: dict[str, Any], source: str
    ) -> tuple[dict[str, Any], Any, Any]:
        """Comprime o contexto e classifica a complexidade antes de rotear."""
        messages = list(params.get("messages") or [])
        tools = params.get("tools")

        verdict = None
        if self.settings.complexity_routing_enabled:
            verdict = classify_complexity(messages=messages, tools=tools, source=source)

        compression = await self.compressor.compress(messages, tools=tools)
        if compression.tokens_saved > 0:
            params = {**params, "messages": compression.messages}

        return params, compression, verdict

    def _apply_complexity(self, requested_model: str, verdict: Any) -> str:
        """Redireciona apenas pedidos genéricos.

        Trocar o modelo quando o cliente pediu um id concreto quebraria a
        expectativa dele e tornaria o custo por modelo impossível de interpretar.
        """
        if verdict is None:
            return requested_model
        if self.catalog.get(requested_model) is not None:
            return requested_model
        if requested_model not in {"auto", "auto/auto", ""}:
            return requested_model
        if self.catalog.profile(verdict.profile) is None:
            return requested_model

        log.debug(
            "router.complexity.redirected",
            from_model=requested_model,
            to_profile=verdict.profile,
            reason=verdict.reason,
        )
        return verdict.profile

    # ── Preparação do request ───────────────────────────────────────────────

    def _prepare_params(self, spec: ModelSpec, params: dict[str, Any]) -> dict[str, Any]:
        prepared = {k: v for k, v in params.items() if v is not None}
        prepared["messages"] = self._apply_prompt_cache(
            list(prepared.get("messages") or []), spec
        )
        if prepared.get("stream") and spec.provider in _OPENAI_DIALECT:
            # Sem isso, provedores OpenAI-compatible não mandam `usage` no fim do
            # stream e a contabilidade viraria estimativa.
            prepared.setdefault("stream_options", {"include_usage": True})
        return prepared

    def _apply_prompt_cache(
        self, messages: list[dict[str, Any]], spec: ModelSpec
    ) -> list[dict[str, Any]]:
        """Marca o prefixo estável para prompt caching, quando o provedor suporta.

        Em provedores OpenAI/Azure o cache de prefixo é automático e a ordem das
        mensagens já basta. O Anthropic exige `cache_control` explícito, e o
        candidato natural é o system prompt: é o maior bloco que não muda entre
        turnos de uma mesma sessão.
        """
        if not messages or not spec.supports_prompt_cache or spec.provider != "anthropic":
            return messages

        marked = [dict(m) for m in messages]
        for message in marked:
            if message.get("role") != "system":
                continue
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            elif isinstance(content, list) and content:
                last = dict(content[-1])
                last["cache_control"] = {"type": "ephemeral"}
                message["content"] = [*content[:-1], last]
            break
        return marked

    # ── Execução ────────────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        requested_model: str,
        params: dict[str, Any],
        source: str = "unknown",
        project_slug: str | None = None,
    ) -> CompletionResult:
        await self.budget.check()

        params, compression, verdict = await self._optimize(params, source)
        messages = list(params.get("messages") or [])
        estimated = estimate_prompt_tokens(messages, params.get("tools"))

        # Um pedido genérico (`auto`) pode ser redirecionado pela complexidade;
        # um modelo pedido explicitamente nunca é trocado por baixo do cliente.
        effective_model = self._apply_complexity(requested_model, verdict)

        decision = await self.policy.select(
            requested_model=effective_model, estimated_prompt_tokens=estimated
        )
        if not decision.candidates:
            reasons = [f"{c.spec.id}: {c.excluded_reason}" for c in decision.excluded]
            await record(
                TelemetryEntry(
                    requested_model=requested_model,
                    source=source,
                    profile=decision.profile,
                    status="error",
                    error_type="NoCandidatesError",
                    error_message="; ".join(reasons) or "catálogo vazio",
                    prompt_tokens=estimated,
                    usage_estimated=True,
                    cost_known=False,
                    complexity=verdict.complexity if verdict else None,
                    project_slug=project_slug,
                )
            )
            raise NoCandidatesError(
                f"Nenhum modelo elegível para '{requested_model}'.", excluded=reasons
            )

        tried: list[str] = []
        last_error: Exception | None = None

        for candidate in decision.candidates[: self.catalog.resilience.max_attempts]:
            spec = candidate.spec
            prepared = self._prepare_params(spec, params)

            if cached := await self.cache.get(spec.id, prepared):
                log.info("router.cache.hit", model=spec.id, source=source)
                saved_cost = self.prices.cost(
                    spec.id,
                    Usage(
                        prompt_tokens=cached.prompt_tokens,
                        completion_tokens=cached.completion_tokens,
                    ),
                )
                await record(
                    TelemetryEntry(
                        requested_model=requested_model,
                        source=source,
                        profile=decision.profile,
                        resolved_model=spec.id,
                        provider=spec.provider,
                        fallback_from=tried,
                        attempts=len(tried) + 1,
                        latency_ms=0,
                        cache_hit=True,
                        tokens_saved=cached.tokens_saved,
                        cost_saved_usd=saved_cost.usd,
                        cost_known=saved_cost.known,
                        project_slug=project_slug,
                    )
                )
                return CompletionResult(
                    payload=cached.payload,
                    model_id=spec.id,
                    provider=spec.provider,
                    usage=Usage(),
                    cost_usd=Decimal(0),
                    cost_known=True,
                    latency_ms=0,
                    cache_hit=True,
                    fallback_from=tried,
                    attempts=len(tried) + 1,
                )

            started = time.perf_counter()
            try:
                response = await self.litellm_router.acompletion(model=spec.id, **prepared)
            except Exception as exc:
                latency = int((time.perf_counter() - started) * 1000)

                # Alguns modelos (ex.: Groq llama-3.3-70b-versatile) às vezes erram o
                # formato da function-call; a API rejeita com `tool_use_failed` em vez
                # de simplesmente não chamar nenhuma tool. Recuperar aqui evita gastar
                # uma tentativa inteira de fallback num modelo às vezes mais caro/lento
                # por um erro de formatação que já sabemos corrigir.
                recovered = extract_failed_tool_call(exc)
                if recovered is not None:
                    nome, argumentos = recovered
                    log.warning(
                        "router.tool_call.recovered",
                        model=spec.id,
                        tool=nome,
                        latency_ms=latency,
                    )
                    payload = _synthetic_tool_call_payload(nome, argumentos)
                    usage = Usage(prompt_tokens=estimated, estimated=True)
                    cost = self.prices.cost(spec.id, usage)
                    await self.health.record_success(spec.id, latency)
                    await record(
                        TelemetryEntry(
                            requested_model=requested_model,
                            source=source,
                            profile=decision.profile,
                            resolved_model=spec.id,
                            provider=spec.provider,
                            fallback_from=tried,
                            attempts=len(tried) + 1,
                            latency_ms=latency,
                            prompt_tokens=usage.prompt_tokens,
                            usage_estimated=True,
                            cost_usd=cost.usd,
                            cost_known=cost.known,
                            project_slug=project_slug,
                        )
                    )
                    return CompletionResult(
                        payload=payload,
                        model_id=spec.id,
                        provider=spec.provider,
                        usage=usage,
                        cost_usd=cost.usd,
                        cost_known=cost.known,
                        latency_ms=latency,
                        fallback_from=tried,
                        attempts=len(tried) + 1,
                    )

                kind = classify(exc)
                last_error = exc
                tried.append(spec.id)

                log.warning(
                    "router.attempt.failed",
                    model=spec.id,
                    kind=kind.value,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                    latency_ms=latency,
                )

                if kind is FailureKind.TRANSIENT:
                    await self.health.record_failure(spec.id, reason=type(exc).__name__)

                if kind is FailureKind.FATAL:
                    await record(
                        TelemetryEntry(
                            requested_model=requested_model,
                            source=source,
                            profile=decision.profile,
                            resolved_model=spec.id,
                            provider=spec.provider,
                            fallback_from=tried[:-1],
                            attempts=len(tried),
                            status="error",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            latency_ms=latency,
                            prompt_tokens=estimated,
                            usage_estimated=True,
                            cost_known=False,
                            project_slug=project_slug,
                        )
                    )
                    raise
                continue

            latency = int((time.perf_counter() - started) * 1000)
            payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)

            usage = Usage.from_litellm(payload.get("usage"))
            if usage.total_tokens == 0:
                usage = self._estimate_usage(estimated, payload)

            cost = self.prices.cost(spec.id, usage)
            await self.health.record_success(spec.id, latency)
            await self.cache.set(
                spec.id,
                prepared,
                payload,
                prompt_tokens=usage.prompt_tokens + usage.cache_read_tokens,
                completion_tokens=usage.completion_tokens,
            )
            await record(
                TelemetryEntry(
                    requested_model=requested_model,
                    source=source,
                    profile=decision.profile,
                    resolved_model=spec.id,
                    provider=spec.provider,
                    fallback_from=tried,
                    attempts=len(tried) + 1,
                    latency_ms=latency,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    usage_estimated=usage.estimated,
                    cost_usd=cost.usd,
                    cost_known=cost.known,
                    tokens_saved=compression.tokens_saved,
                    cost_saved_usd=self._savings_value(spec.id, compression.tokens_saved),
                    savings_breakdown=compression.savings,
                    complexity=verdict.complexity if verdict else None,
                    project_slug=project_slug,
                )
            )
            log.info(
                "router.completed",
                model=spec.id,
                latency_ms=latency,
                tokens=usage.total_tokens,
                cost_usd=float(cost.usd),
                fallbacks=len(tried),
                source=source,
            )
            return CompletionResult(
                payload=payload,
                model_id=spec.id,
                provider=spec.provider,
                usage=usage,
                cost_usd=cost.usd,
                cost_known=cost.known,
                latency_ms=latency,
                fallback_from=tried,
                attempts=len(tried) + 1,
            )

        assert last_error is not None
        await record(
            TelemetryEntry(
                requested_model=requested_model,
                source=source,
                profile=decision.profile,
                fallback_from=tried,
                attempts=len(tried),
                status="error",
                error_type=type(last_error).__name__,
                error_message=str(last_error),
                prompt_tokens=estimated,
                usage_estimated=True,
                cost_known=False,
                complexity=verdict.complexity if verdict else None,
                project_slug=project_slug,
            )
        )
        raise AllCandidatesFailedError(
            f"Todos os candidatos falharam para '{requested_model}': {', '.join(tried)}",
            attempts=tried,
            last_error=last_error,
        )

    async def stream(
        self,
        *,
        requested_model: str,
        params: dict[str, Any],
        source: str = "unknown",
        project_slug: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming com fallback antes do primeiro chunk.

        Depois que o primeiro chunk chega ao cliente não há como trocar de
        modelo sem corromper a resposta — a partir daí a falha é propagada.
        """
        await self.budget.check()

        params, compression, verdict = await self._optimize(params, source)
        messages = list(params.get("messages") or [])
        estimated = estimate_prompt_tokens(messages, params.get("tools"))
        effective_model = self._apply_complexity(requested_model, verdict)

        decision = await self.policy.select(
            requested_model=effective_model, estimated_prompt_tokens=estimated
        )
        if not decision.candidates:
            reasons = [f"{c.spec.id}: {c.excluded_reason}" for c in decision.excluded]
            raise NoCandidatesError(
                f"Nenhum modelo elegível para '{requested_model}'.", excluded=reasons
            )

        tried: list[str] = []
        last_error: Exception | None = None

        for candidate in decision.candidates[: self.catalog.resilience.max_attempts]:
            spec = candidate.spec
            prepared = self._prepare_params(spec, {**params, "stream": True})
            started = time.perf_counter()

            try:
                iterator = await self.litellm_router.acompletion(model=spec.id, **prepared)
            except Exception as exc:
                kind = classify(exc)
                last_error = exc
                tried.append(spec.id)
                log.warning(
                    "router.stream.setup_failed",
                    model=spec.id,
                    kind=kind.value,
                    error=str(exc)[:300],
                )
                if kind is FailureKind.TRANSIENT:
                    await self.health.record_failure(spec.id, reason=type(exc).__name__)
                if kind is FailureKind.FATAL:
                    raise
                continue

            async for event in self._consume_stream(
                iterator=iterator,
                spec=spec,
                decision_profile=decision.profile,
                requested_model=requested_model,
                source=source,
                estimated_prompt_tokens=estimated,
                tried=list(tried),
                started=started,
                compression=compression,
                verdict=verdict,
                project_slug=project_slug,
            ):
                yield event
            return

        assert last_error is not None
        raise AllCandidatesFailedError(
            f"Todos os candidatos falharam para '{requested_model}': {', '.join(tried)}",
            attempts=tried,
            last_error=last_error,
        )

    async def _consume_stream(
        self,
        *,
        iterator: Any,
        spec: ModelSpec,
        decision_profile: str | None,
        requested_model: str,
        source: str,
        estimated_prompt_tokens: int,
        tried: list[str],
        started: float,
        compression: Any = None,
        verdict: Any = None,
        project_slug: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        ttft_ms: int | None = None
        usage = Usage()
        text_parts: list[str] = []
        failed: Exception | None = None

        try:
            async for chunk in iterator:
                if ttft_ms is None:
                    ttft_ms = int((time.perf_counter() - started) * 1000)

                data = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)

                if raw_usage := data.get("usage"):
                    usage = Usage.from_litellm(raw_usage)

                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if content := delta.get("content"):
                        text_parts.append(str(content))

                yield data
        except Exception as exc:
            failed = exc
            log.warning("router.stream.interrupted", model=spec.id, error=str(exc)[:300])
        finally:
            latency = int((time.perf_counter() - started) * 1000)

            if usage.total_tokens == 0:
                # Provedor mudo sobre `usage`: estimamos, e marcamos como estimado
                # para o dashboard não apresentar chute como medição.
                usage = Usage(
                    prompt_tokens=estimated_prompt_tokens,
                    completion_tokens=count_text("".join(text_parts)),
                    estimated=True,
                )

            cost = self.prices.cost(spec.id, usage)

            if failed is None:
                await self.health.record_success(spec.id, latency)
            elif classify(failed) is FailureKind.TRANSIENT:
                await self.health.record_failure(spec.id, reason=type(failed).__name__)

            await record(
                TelemetryEntry(
                    requested_model=requested_model,
                    source=source,
                    profile=decision_profile,
                    resolved_model=spec.id,
                    provider=spec.provider,
                    fallback_from=tried,
                    attempts=len(tried) + 1,
                    status="ok" if failed is None else "error",
                    error_type=type(failed).__name__ if failed else None,
                    error_message=str(failed) if failed else None,
                    stream=True,
                    latency_ms=latency,
                    ttft_ms=ttft_ms,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    usage_estimated=usage.estimated,
                    cost_usd=cost.usd,
                    cost_known=cost.known,
                    tokens_saved=compression.tokens_saved if compression else 0,
                    cost_saved_usd=self._savings_value(
                        spec.id, compression.tokens_saved if compression else 0
                    ),
                    savings_breakdown=compression.savings if compression else {},
                    complexity=verdict.complexity if verdict else None,
                    project_slug=project_slug,
                )
            )

            if failed is None:
                log.info(
                    "router.stream.completed",
                    model=spec.id,
                    latency_ms=latency,
                    ttft_ms=ttft_ms,
                    tokens=usage.total_tokens,
                    cost_usd=float(cost.usd),
                    source=source,
                )

        if failed is not None:
            raise failed

    async def embed(
        self,
        *,
        requested_model: str,
        inputs: list[str],
        source: str = "unknown",
        project_slug: str | None = None,
    ) -> CompletionResult:
        await self.budget.check()

        estimated = sum(count_text(text) for text in inputs)
        decision = await self.policy.select(
            requested_model=requested_model,
            estimated_prompt_tokens=estimated,
            require_embedding=True,
        )
        if not decision.candidates:
            reasons = [f"{c.spec.id}: {c.excluded_reason}" for c in decision.excluded]
            raise NoCandidatesError(
                f"Nenhum modelo de embedding elegível para '{requested_model}'.",
                excluded=reasons,
            )

        tried: list[str] = []
        last_error: Exception | None = None

        for candidate in decision.candidates[: self.catalog.resilience.max_attempts]:
            spec = candidate.spec
            started = time.perf_counter()
            try:
                response = await self.litellm_router.aembedding(model=spec.id, input=inputs)
            except Exception as exc:
                last_error = exc
                tried.append(spec.id)
                if classify(exc) is FailureKind.TRANSIENT:
                    await self.health.record_failure(spec.id, reason=type(exc).__name__)
                log.warning("router.embed.failed", model=spec.id, error=str(exc)[:300])
                continue

            latency = int((time.perf_counter() - started) * 1000)
            payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
            usage = Usage.from_litellm(payload.get("usage"))
            if usage.total_tokens == 0:
                usage = Usage(prompt_tokens=estimated, estimated=True)
            cost = self.prices.cost(spec.id, usage)

            await self.health.record_success(spec.id, latency)
            await record(
                TelemetryEntry(
                    requested_model=requested_model,
                    source=source,
                    endpoint="embedding",
                    profile=decision.profile,
                    resolved_model=spec.id,
                    provider=spec.provider,
                    fallback_from=tried,
                    attempts=len(tried) + 1,
                    latency_ms=latency,
                    prompt_tokens=usage.prompt_tokens,
                    usage_estimated=usage.estimated,
                    cost_usd=cost.usd,
                    cost_known=cost.known,
                    project_slug=project_slug,
                )
            )
            return CompletionResult(
                payload=payload,
                model_id=spec.id,
                provider=spec.provider,
                usage=usage,
                cost_usd=cost.usd,
                cost_known=cost.known,
                latency_ms=latency,
                fallback_from=tried,
                attempts=len(tried) + 1,
            )

        assert last_error is not None
        raise AllCandidatesFailedError(
            f"Todos os candidatos de embedding falharam: {', '.join(tried)}",
            attempts=tried,
            last_error=last_error,
        )

    def _savings_value(self, model_id: str, tokens_saved: int) -> Decimal:
        """Valor em dólar dos tokens de input que deixaram de ser enviados."""
        if tokens_saved <= 0:
            return Decimal(0)
        return self.prices.cost(model_id, Usage(prompt_tokens=tokens_saved)).usd

    @staticmethod
    def _estimate_usage(estimated_prompt: int, payload: dict[str, Any]) -> Usage:
        text = "".join(
            str((choice.get("message") or {}).get("content") or "")
            for choice in payload.get("choices") or []
        )
        return Usage(
            prompt_tokens=estimated_prompt,
            completion_tokens=count_text(text),
            estimated=True,
        )

    # ── Diagnóstico ─────────────────────────────────────────────────────────

    async def healthcheck(self, model_id: str) -> dict[str, Any]:
        spec = self.catalog.get(model_id)
        if spec is None:
            return {"model": model_id, "ok": False, "detail": "modelo não está no catálogo"}
        adapter = self.adapters.get(spec.provider)
        if adapter is None:
            return {"model": model_id, "ok": False, "detail": "sem adaptador"}

        result = await adapter.healthcheck(spec)
        snapshot = await self.health.snapshot(model_id)
        return {
            "model": model_id,
            "provider": spec.provider,
            "enabled": spec.enabled,
            "ok": result.ok,
            "detail": result.detail,
            "probe_latency_ms": result.latency_ms,
            "circuit_open": not snapshot.available,
            "cooldown_remaining_s": snapshot.cooldown_remaining_s,
            "consecutive_fails": snapshot.consecutive_fails,
            "successes": snapshot.successes,
            "failures": snapshot.failures,
            "success_rate": round(snapshot.success_rate, 4),
            "latency_p50_ms": snapshot.latency_p50_ms,
            "latency_p95_ms": snapshot.latency_p95_ms,
            "unavailable_reason": spec.unavailable_reason,
        }
