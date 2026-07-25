"""Testes da ordenação de candidatos.

A policy é testável sem provedor nenhum: o `HealthTracker` sem Redis já se
comporta como "tudo saudável, sem histórico de latência".
"""

from __future__ import annotations

import pytest

from sicoobito.config import Settings
from sicoobito.router.adapters import build_adapters
from sicoobito.router.health import HealthTracker
from sicoobito.router.policy import RoutingPolicy


@pytest.fixture
def policy(catalog, prices):
    settings = Settings(
        _env_file=None,
        AZURE_API_BASE="https://exemplo.openai.azure.com",
        AZURE_API_KEY="chave",
    )
    adapters = build_adapters(settings)
    for spec in catalog.models.values():
        if adapter := adapters.get(spec.provider):
            adapter.resolve(spec)
    return RoutingPolicy(catalog, prices, HealthTracker(None, catalog.resilience))


async def test_local_first_prefers_ollama(policy):
    decision = await policy.select(
        requested_model="local-first", estimated_prompt_tokens=500
    )
    assert decision.order[0] == "ollama/qwen2.5-coder:7b"


async def test_cheap_profile_orders_by_estimated_cost(policy):
    decision = await policy.select(requested_model="cheap", estimated_prompt_tokens=1000)
    assert decision.strategy == "cost"
    # O local custa zero, então tem de vir na frente do gpt-4o-mini.
    assert decision.order[0] == "ollama/qwen2.5-coder:7b"


async def test_oversized_prompt_skips_small_context_models(policy):
    # 100k tokens não cabem na janela de 32k do Qwen local.
    decision = await policy.select(
        requested_model="local-first", estimated_prompt_tokens=100_000
    )
    assert "ollama/qwen2.5-coder:7b" not in decision.order
    assert any("contexto não cabe" in (c.excluded_reason or "") for c in decision.excluded)
    # Mas o Foundry, com 128k, continua elegível.
    assert "foundry/gpt-4o-mini" in decision.order


async def test_explicit_model_is_not_silently_replaced(policy):
    decision = await policy.select(
        requested_model="foundry/gpt-4o", estimated_prompt_tokens=100
    )
    assert decision.strategy == "explicit"
    assert decision.order == ["foundry/gpt-4o"]


async def test_unavailable_model_is_excluded_with_reason(policy):
    decision = await policy.select(
        requested_model="databricks/llama-3.3-70b", estimated_prompt_tokens=100
    )
    assert decision.order == []
    assert decision.excluded[0].excluded_reason


async def test_auto_profile_scores_and_returns_full_fallback_chain(policy):
    decision = await policy.select(requested_model="auto", estimated_prompt_tokens=1000)
    assert decision.strategy == "score"
    assert len(decision.order) >= 2, "o perfil auto precisa oferecer fallback"


async def test_profile_accepts_auto_slash_prefix(policy):
    prefixed = await policy.select(requested_model="auto/cheap", estimated_prompt_tokens=100)
    plain = await policy.select(requested_model="cheap", estimated_prompt_tokens=100)
    assert prefixed.order == plain.order


async def test_unknown_model_falls_back_to_default_profile(policy):
    decision = await policy.select(
        requested_model="modelo-que-nao-existe", estimated_prompt_tokens=100
    )
    assert decision.profile == policy.catalog.default_profile


async def test_embedding_request_only_returns_embedding_models(policy):
    decision = await policy.select(
        requested_model="embedding", estimated_prompt_tokens=100, require_embedding=True
    )
    assert decision.order
    for model_id in decision.order:
        assert policy.catalog.get(model_id).is_embedding
