"""Testes da fachada HTTP.

Sobem a aplicação de verdade, com lifespan: catálogo carregado, Redis ausente
(degradação exercitada) e nenhuma dependência de Postgres nas rotas testadas.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["SICOOBITO_API_KEY"] = "chave-de-teste"
# Aponta para portas mortas de propósito: o startup precisa sobreviver a isso.
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from sicoobito.config import get_settings
from sicoobito.main import create_app


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def test_app_starts_without_redis(client):
    response = client.get("/", headers={"Authorization": "Bearer chave-de-teste"})
    assert response.status_code == 200
    assert response.json()["openai_base_url"] == "/v1"


def test_models_endpoint_requires_the_api_key(client):
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer errada"}).status_code == 401


def test_models_endpoint_lists_catalog_and_profiles(client):
    response = client.get("/v1/models", headers={"Authorization": "Bearer chave-de-teste"})
    assert response.status_code == 200

    ids = {model["id"] for model in response.json()["data"]}
    assert "ollama/qwen2.5-coder:7b" in ids
    # Perfis precisam aparecer como "modelo": é assim que o cliente pede auto/cheap.
    assert "auto/cheap" in ids
    assert "auto" in ids


def test_x_api_key_header_is_accepted(client):
    response = client.get("/v1/models", headers={"X-API-Key": "chave-de-teste"})
    assert response.status_code == 200


def test_health_reports_catalog_state(client):
    response = client.get("/api/health", headers={"Authorization": "Bearer chave-de-teste"})
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["models_total"] > 0
    # Sem Redis, o cache tem de estar desligado em vez de estourar.
    assert body["cache_enabled"] is False


def test_providers_catalog_exposes_availability_reasons(client):
    response = client.get("/api/providers", headers={"Authorization": "Bearer chave-de-teste"})
    assert response.status_code == 200

    models = {m["id"]: m for m in response.json()["models"]}
    foundry = models["foundry/gpt-4o"]
    assert foundry["available"] is False
    assert "AZURE_API_BASE" in (foundry["unavailable_reason"] or "")


def test_chat_without_any_reachable_provider_returns_503_not_500(client):
    # Sem Ollama no ar e sem credenciais de nuvem, nenhum candidato é elegível.
    # O cliente precisa ver "sem provedor", não um stack trace.
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"model": "databricks/llama-3.3-70b", "messages": [{"role": "user", "content": "oi"}]},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["type"] == "no_candidates"


def test_unknown_model_falls_back_to_default_profile_not_404(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"model": "modelo-inexistente", "messages": [{"role": "user", "content": "oi"}]},
    )
    # 503 (nenhum provedor no ar neste ambiente) e não 404: o perfil padrão assumiu.
    assert response.status_code in {502, 503}
