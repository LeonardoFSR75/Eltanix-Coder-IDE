from __future__ import annotations

from sicoobito.optimizer.cache import ResponseCache
from sicoobito.optimizer.tokens import count_text, estimate_prompt_tokens
from sicoobito.router.errors import FailureKind, classify


class ContextWindowExceededError(Exception):
    pass


class BadRequestError(Exception):
    pass


class RateLimitError(Exception):
    pass


class ContentPolicyViolationError(Exception):
    pass


def test_context_overflow_skips_without_penalising_provider():
    assert classify(ContextWindowExceededError("too long")) is FailureKind.SKIP


def test_rate_limit_is_transient():
    assert classify(RateLimitError("429")) is FailureKind.TRANSIENT


def test_client_error_is_fatal_and_should_not_retry_elsewhere():
    assert classify(BadRequestError("invalid tool schema")) is FailureKind.FATAL


def test_context_overflow_wrapped_in_bad_request_is_still_a_skip():
    exc = BadRequestError("This model's maximum context length is 8192 tokens")
    assert classify(exc) is FailureKind.SKIP


def test_content_policy_is_fatal():
    assert classify(ContentPolicyViolationError("blocked")) is FailureKind.FATAL


def test_credit_balance_low_is_transient_allowing_fallback():
    exc = BadRequestError("Your credit balance is too low to access the Anthropic API.")
    assert classify(exc) is FailureKind.TRANSIENT


def test_cache_is_disabled_without_redis():
    cache = ResponseCache(None)
    assert cache.enabled is False
    assert cache.is_cacheable({"temperature": 0}) is False


def test_cache_skips_non_deterministic_requests():
    class FakeRedis:
        pass

    cache = ResponseCache(FakeRedis(), only_deterministic=True)  # type: ignore[arg-type]
    assert cache.is_cacheable({"temperature": 0}) is True
    assert cache.is_cacheable({}) is True
    assert cache.is_cacheable({"temperature": 0.7}) is False


def test_cache_key_separates_models():
    class FakeRedis:
        pass

    cache = ResponseCache(FakeRedis())  # type: ignore[arg-type]
    params = {"messages": [{"role": "user", "content": "oi"}], "temperature": 0}
    assert cache.key("ollama/a", params) != cache.key("foundry/b", params)


def test_cache_key_is_stable_across_dict_ordering():
    class FakeRedis:
        pass

    cache = ResponseCache(FakeRedis())  # type: ignore[arg-type]
    a = {"messages": [{"role": "user", "content": "oi"}], "temperature": 0, "max_tokens": 10}
    b = {"max_tokens": 10, "temperature": 0, "messages": [{"content": "oi", "role": "user"}]}
    assert cache.key("m", a) == cache.key("m", b)


def test_token_estimate_grows_with_input():
    short = estimate_prompt_tokens([{"role": "user", "content": "oi"}])
    long = estimate_prompt_tokens([{"role": "user", "content": "oi " * 500}])
    assert 0 < short < long


def test_tool_definitions_are_counted():
    messages = [{"role": "user", "content": "oi"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lê um arquivo do workspace",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    assert estimate_prompt_tokens(messages, tools) > estimate_prompt_tokens(messages)


def test_multimodal_content_does_not_crash_the_counter():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "o que é isto?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ]
    assert estimate_prompt_tokens(messages) > 0


def test_empty_text_counts_zero():
    assert count_text("") == 0
