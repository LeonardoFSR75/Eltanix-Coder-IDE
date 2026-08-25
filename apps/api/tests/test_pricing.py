from __future__ import annotations

from decimal import Decimal

from eltanix.router.pricing import PriceTable, Usage


def test_local_models_cost_nothing(prices):
    cost = prices.cost(
        "ollama/qwen2.5-coder:7b", Usage(prompt_tokens=100_000, completion_tokens=50_000)
    )
    assert cost.known is True
    assert cost.usd == Decimal(0)


def test_cost_uses_per_million_rates(prices):
    # gpt-4o: 2.50 input / 10.00 output por 1M
    cost = prices.cost("foundry/gpt-4o", Usage(prompt_tokens=1_000_000, completion_tokens=0))
    assert cost.usd == Decimal("2.50")

    cost = prices.cost("foundry/gpt-4o", Usage(prompt_tokens=0, completion_tokens=1_000_000))
    assert cost.usd == Decimal("10.00")


def test_cache_read_uses_discounted_rate(prices):
    cost = prices.cost("foundry/gpt-4o", Usage(prompt_tokens=0, cache_read_tokens=1_000_000))
    assert cost.usd == Decimal("1.25")


def test_unknown_model_reports_cost_as_unknown_not_zero():
    table = PriceTable({})
    cost = table.cost("modelo/inexistente", Usage(prompt_tokens=1000, completion_tokens=1000))
    assert cost.known is False
    assert cost.usd == Decimal(0)


def test_usage_from_openai_shape():
    usage = Usage.from_litellm({"prompt_tokens": 120, "completion_tokens": 30})
    assert usage.prompt_tokens == 120
    assert usage.completion_tokens == 30
    assert usage.total_tokens == 150


def test_usage_separates_cached_tokens_from_prompt():
    # A OpenAI reporta `prompt_tokens` incluindo os cacheados; contar os dois
    # cheios cobraria o mesmo token duas vezes.
    usage = Usage.from_litellm(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
    )
    assert usage.cache_read_tokens == 800
    assert usage.prompt_tokens == 200


def test_usage_from_anthropic_shape():
    usage = Usage.from_litellm(
        {
            "input_tokens": 500,
            "output_tokens": 80,
            "cache_read_input_tokens": 400,
            "cache_creation_input_tokens": 100,
        }
    )
    assert usage.cache_read_tokens == 400
    assert usage.cache_write_tokens == 100
    assert usage.prompt_tokens == 100


def test_usage_from_none_is_empty():
    usage = Usage.from_litellm(None)
    assert usage.total_tokens == 0
