"""Descoberta de modelos remotos por provedor.

Não há biblioteca de mock de HTTP nas dependências do projeto; seguindo o
estilo já usado na suíte (fakes simples via `monkeypatch`, ver
`test_tickets.py`), cada teste substitui `httpx.AsyncClient` por uma classe
fake que devolve uma resposta fixa ou levanta uma exceção.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from novaai_studio.config import Settings
from novaai_studio.router.adapters.base import DiscoveryError
from novaai_studio.router.adapters.databricks import DatabricksAdapter
from novaai_studio.router.adapters.direct import AnthropicAdapter, GroqAdapter, OpenAIAdapter
from novaai_studio.router.adapters.ollama import OllamaAdapter


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    """Substitui `httpx.AsyncClient`: mesmo protocolo `async with ... as c`."""

    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _patch_client(monkeypatch: pytest.MonkeyPatch, *, payload: Any = None, error: Exception | None = None) -> None:
    response = None if payload is None else _FakeResponse(payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(response, error))


# ── Ollama ────────────────────────────────────────────────────────────────


async def test_ollama_discover_without_base_url_returns_empty() -> None:
    adapter = OllamaAdapter(Settings(_env_file=None, OLLAMA_BASE_URL=""))
    assert await adapter.discover_models() == []


async def test_ollama_discover_lists_tags_and_infers_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        payload={"models": [{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text"}]},
    )
    adapter = OllamaAdapter(Settings(_env_file=None, OLLAMA_BASE_URL="http://localhost:11434"))

    discovered = await adapter.discover_models()

    by_name = {d.raw_name: d for d in discovered}
    assert by_name["qwen2.5-coder:7b"].suggested_id == "ollama/qwen2.5-coder:7b"
    assert by_name["qwen2.5-coder:7b"].capabilities == ["chat", "tools"]
    assert by_name["nomic-embed-text"].capabilities == ["embedding"]
    assert set(by_name["qwen2.5-coder:7b"].estimated_fields) == {"context_window", "capabilities"}


async def test_ollama_discover_raises_discovery_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, error=httpx.ConnectError("recusado"))
    adapter = OllamaAdapter(Settings(_env_file=None, OLLAMA_BASE_URL="http://localhost:11434"))

    with pytest.raises(DiscoveryError):
        await adapter.discover_models()


# ── Databricks ──────────────────────────────────────────────────────────────


async def test_databricks_discover_without_credentials_returns_empty() -> None:
    adapter = DatabricksAdapter(Settings(_env_file=None, DATABRICKS_HOST="", DATABRICKS_TOKEN=""))
    assert await adapter.discover_models() == []


async def test_databricks_discover_uses_task_to_detect_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        payload={
            "endpoints": [
                {
                    "name": "llama-3-3-70b",
                    "config": {"served_entities": [{"task": "llm/v1/chat"}]},
                },
                {
                    "name": "bge-large-en",
                    "config": {"served_entities": [{"task": "llm/v1/embeddings"}]},
                },
            ]
        },
    )
    adapter = DatabricksAdapter(
        Settings(_env_file=None, DATABRICKS_HOST="https://x.databricks.com", DATABRICKS_TOKEN="tok")
    )

    discovered = await adapter.discover_models()

    by_name = {d.raw_name: d for d in discovered}
    assert by_name["llama-3-3-70b"].capabilities == ["chat"]
    assert by_name["bge-large-en"].capabilities == ["embedding"]
    assert by_name["llama-3-3-70b"].suggested_id == "databricks/llama-3-3-70b"
    # `task` é dado real da API — só context_window é palpite aqui.
    assert by_name["llama-3-3-70b"].estimated_fields == ["context_window"]


async def test_databricks_discover_raises_discovery_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, error=httpx.ConnectError("recusado"))
    adapter = DatabricksAdapter(
        Settings(_env_file=None, DATABRICKS_HOST="https://x.databricks.com", DATABRICKS_TOKEN="tok")
    )

    with pytest.raises(DiscoveryError):
        await adapter.discover_models()


# ── Anthropic ────────────────────────────────────────────────────────────────


async def test_anthropic_discover_without_credentials_returns_empty() -> None:
    adapter = AnthropicAdapter(Settings(_env_file=None, ANTHROPIC_API_KEY=""))
    assert await adapter.discover_models() == []


async def test_anthropic_discover_lists_models_with_estimated_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, payload={"data": [{"id": "claude-sonnet-4-5"}, {"id": "claude-opus-4"}]})
    adapter = AnthropicAdapter(Settings(_env_file=None, ANTHROPIC_API_KEY="sk-ant-teste"))

    discovered = await adapter.discover_models()

    ids = {d.suggested_id for d in discovered}
    assert ids == {"anthropic/claude-sonnet-4-5", "anthropic/claude-opus-4"}
    assert all(set(d.estimated_fields) == {"context_window", "capabilities"} for d in discovered)


async def test_groq_discover_raises_discovery_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, error=httpx.ConnectError("recusado"))
    adapter = GroqAdapter(Settings(_env_file=None, GROQ_API_KEY="gsk_teste"))

    with pytest.raises(DiscoveryError):
        await adapter.discover_models()


# ── OpenAI ──────────────────────────────────────────────────────────────────


async def test_openai_discover_without_credentials_returns_empty() -> None:
    adapter = OpenAIAdapter(Settings(_env_file=None, OPENAI_API_KEY=""))
    assert await adapter.discover_models() == []


async def test_openai_discover_lists_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        payload={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}]},
    )
    adapter = OpenAIAdapter(Settings(_env_file=None, OPENAI_API_KEY="sk-teste"))

    discovered = await adapter.discover_models()

    ids = {d.suggested_id for d in discovered}
    assert ids == {"openai/gpt-4o", "openai/gpt-4o-mini"}


# ── Groq ───────────────────────────────────────────────────────────────────


async def test_groq_discover_without_credentials_returns_empty() -> None:
    adapter = GroqAdapter(Settings(_env_file=None, GROQ_API_KEY=""))
    assert await adapter.discover_models() == []


async def test_groq_discover_lists_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        payload={"data": [{"id": "llama-3.3-70b-versatile", "context_window": 128000}]},
    )
    adapter = GroqAdapter(Settings(_env_file=None, GROQ_API_KEY="gsk_teste"))

    discovered = await adapter.discover_models()

    assert len(discovered) == 1
    assert discovered[0].suggested_id == "groq/llama-3.3-70b-versatile"
    assert discovered[0].provider == "groq"
    assert discovered[0].context_window == 128000


async def test_groq_discover_raises_discovery_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, error=httpx.ConnectError("recusado"))
    adapter = GroqAdapter(Settings(_env_file=None, GROQ_API_KEY="gsk_teste"))

    with pytest.raises(DiscoveryError):
        await adapter.discover_models()
