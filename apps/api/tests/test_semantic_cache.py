"""`SemanticCache`: a propriedade de segurança central é o gate de
elegibilidade — nunca roda com `tools` presente, nunca para fonte excluída,
nunca sem `embed_fn` ligado. Sem Postgres real: `session_scope`/
`semantic_cache_store` são trocados por fakes que só capturam os argumentos.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from novaai_studio.optimizer import semantic_cache as semantic_cache_module
from novaai_studio.optimizer.cache import CachedResponse, ResponseCache
from novaai_studio.optimizer.semantic_cache import SemanticCache, _extract_query_text


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@dataclass
class _FakeEmbedResult:
    payload: dict[str, Any] = field(default_factory=dict)


class _FakeEmbedFn:
    def __init__(self, vector: list[float] | None = (0.1, 0.2, 0.3)) -> None:
        self.vector = vector
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, *, requested_model, inputs, source):
        self.chamadas.append({"requested_model": requested_model, "inputs": inputs, "source": source})
        if self.vector is None:
            return _FakeEmbedResult(payload={})
        return _FakeEmbedResult(payload={"data": [{"index": 0, "embedding": list(self.vector)}]})


@pytest.fixture
def semantic_cache():
    redis_cache = ResponseCache(_FakeRedis(), enabled=True)
    cache = SemanticCache(
        redis_cache=redis_cache,
        enabled=True,
        embedding_profile="embedding",
        max_cosine_distance=0.05,
        ttl_seconds=3600,
        excluded_sources=["agent:code_review"],
    )
    cache.set_embed_fn(_FakeEmbedFn())
    return cache


# ── _extract_query_text ──────────────────────────────────────────────────────


def test_extract_query_text_gets_last_user_message():
    mensagens = [
        {"role": "system", "content": "prompt do sistema"},
        {"role": "user", "content": "primeira pergunta"},
        {"role": "assistant", "content": "resposta"},
        {"role": "user", "content": "segunda pergunta"},
    ]
    assert _extract_query_text(mensagens) == "segunda pergunta"


def test_extract_query_text_handles_multimodal_content():
    mensagens = [
        {"role": "user", "content": [{"type": "text", "text": "parte 1"}, {"type": "text", "text": "parte 2"}]}
    ]
    assert _extract_query_text(mensagens) == "parte 1\nparte 2"


def test_extract_query_text_empty_without_user_message():
    assert _extract_query_text([{"role": "system", "content": "x"}]) == ""


# ── Gate de elegibilidade — a propriedade de segurança central ─────────────


async def test_lookup_returns_none_when_disabled():
    redis_cache = ResponseCache(_FakeRedis(), enabled=True)
    cache = SemanticCache(
        redis_cache=redis_cache,
        enabled=False,
        embedding_profile="embedding",
        max_cosine_distance=0.05,
        ttl_seconds=3600,
        excluded_sources=[],
    )
    cache.set_embed_fn(_FakeEmbedFn())
    resultado = await cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, source="teste"
    )
    assert resultado is None


async def test_lookup_returns_none_without_embed_fn():
    redis_cache = ResponseCache(_FakeRedis(), enabled=True)
    cache = SemanticCache(
        redis_cache=redis_cache,
        enabled=True,
        embedding_profile="embedding",
        max_cosine_distance=0.05,
        ttl_seconds=3600,
        excluded_sources=[],
    )
    # set_embed_fn nunca chamado — simula a janela entre construir SemanticCache
    # e o RouterEngine terminar de montar (ver main.py::lifespan).
    resultado = await cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, source="teste"
    )
    assert resultado is None


async def test_lookup_returns_none_when_tools_present(semantic_cache):
    # A propriedade de segurança central: presença de `tools` desliga o
    # cache semântico incondicionalmente, mesmo com tudo mais habilitado.
    resultado = await semantic_cache.lookup(
        "modelo",
        {"messages": [{"role": "user", "content": "x"}], "tools": [{"type": "function"}]},
        source="teste",
    )
    assert resultado is None


async def test_lookup_returns_none_for_excluded_source(semantic_cache):
    resultado = await semantic_cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, source="agent:code_review"
    )
    assert resultado is None


async def test_lookup_returns_none_without_user_message(semantic_cache):
    resultado = await semantic_cache.lookup(
        "modelo", {"messages": [{"role": "system", "content": "x"}]}, source="teste"
    )
    assert resultado is None


async def test_lookup_degrades_to_none_when_embedding_fails():
    redis_cache = ResponseCache(_FakeRedis(), enabled=True)
    cache = SemanticCache(
        redis_cache=redis_cache,
        enabled=True,
        embedding_profile="embedding",
        max_cosine_distance=0.05,
        ttl_seconds=3600,
        excluded_sources=[],
    )

    async def _raising_embed_fn(**kwargs):
        raise RuntimeError("modelo de embedding fora do ar")

    cache.set_embed_fn(_raising_embed_fn)
    resultado = await cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, source="teste"
    )
    assert resultado is None


async def test_record_is_noop_when_tools_present(semantic_cache, monkeypatch):
    chamado = False

    async def _fake_insert(*args, **kwargs):
        nonlocal chamado
        chamado = True

    monkeypatch.setattr(semantic_cache_module.semantic_cache_store, "insert", _fake_insert)
    await semantic_cache.record(
        "modelo",
        {"messages": [{"role": "user", "content": "x"}], "tools": [{"type": "function"}]},
        "chave-redis",
        source="teste",
    )
    assert chamado is False


# ── lookup/record com store fake (sem Postgres) ─────────────────────────────


@asynccontextmanager
async def _fake_session_scope():
    yield object()


async def test_lookup_returns_cached_response_on_semantic_hit(semantic_cache, monkeypatch):
    monkeypatch.setattr(semantic_cache_module, "session_scope", _fake_session_scope)

    async def _fake_find_nearest(session, *, model_id, embedding, max_distance):
        assert model_id == "modelo"
        assert max_distance == 0.05
        return "chave-redis-existente"

    monkeypatch.setattr(
        semantic_cache_module.semantic_cache_store, "find_nearest", _fake_find_nearest
    )

    payload = {"choices": [{"message": {"content": "resposta cacheada"}}]}
    await semantic_cache._redis_cache._redis.set(  # type: ignore[attr-defined]
        "chave-redis-existente",
        __import__("json").dumps(
            {"payload": payload, "prompt_tokens": 10, "completion_tokens": 5, "model_id": "modelo"}
        ),
    )

    resultado = await semantic_cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "pergunta parecida"}]}, source="teste"
    )
    assert resultado is not None
    assert resultado.payload == payload


async def test_lookup_returns_none_without_nearby_candidate(semantic_cache, monkeypatch):
    monkeypatch.setattr(semantic_cache_module, "session_scope", _fake_session_scope)

    async def _fake_find_nearest(session, *, model_id, embedding, max_distance):
        return None

    monkeypatch.setattr(
        semantic_cache_module.semantic_cache_store, "find_nearest", _fake_find_nearest
    )
    resultado = await semantic_cache.lookup(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, source="teste"
    )
    assert resultado is None


async def test_record_inserts_embedding_for_eligible_call(semantic_cache, monkeypatch):
    monkeypatch.setattr(semantic_cache_module, "session_scope", _fake_session_scope)
    capturado = {}

    async def _fake_insert(session, *, model_id, redis_cache_key, embedding, expires_at):
        capturado["model_id"] = model_id
        capturado["redis_cache_key"] = redis_cache_key
        capturado["embedding"] = embedding
        capturado["expires_at"] = expires_at

    monkeypatch.setattr(semantic_cache_module.semantic_cache_store, "insert", _fake_insert)

    await semantic_cache.record(
        "modelo", {"messages": [{"role": "user", "content": "x"}]}, "chave-nova", source="teste"
    )
    assert capturado["model_id"] == "modelo"
    assert capturado["redis_cache_key"] == "chave-nova"
    assert capturado["embedding"] == [0.1, 0.2, 0.3]
