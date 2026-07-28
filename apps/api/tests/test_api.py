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


def test_persist_default_profile_replaces_only_target_line(tmp_path):
    from sicoobito.api.routes.health import _persist_default_profile

    routes_file = tmp_path / "routes.yaml"
    routes_file.write_text(
        "# comentário explicando os perfis\n"
        "default_profile: auto\n"
        "\n"
        "profiles:\n"
        "  auto:\n"
        "    strategy: score\n",
        encoding="utf-8",
    )

    _persist_default_profile(routes_file, "cheap")

    content = routes_file.read_text(encoding="utf-8")
    assert "default_profile: cheap" in content
    # O resto do arquivo (comentários, perfis) não pode ser tocado.
    assert "# comentário explicando os perfis" in content
    assert "strategy: score" in content


def test_persist_default_profile_missing_key_raises(tmp_path):
    from sicoobito.api.routes.health import _persist_default_profile

    routes_file = tmp_path / "routes.yaml"
    routes_file.write_text("profiles:\n  auto:\n    strategy: score\n", encoding="utf-8")

    with pytest.raises(ValueError):
        _persist_default_profile(routes_file, "cheap")


def test_set_default_profile_updates_memory_and_disk(client, tmp_path):
    """Não pode escrever no `config/routes.yaml` real do repositório: a
    persistência é redirecionada para uma cópia em tmp_path via override de
    `get_settings`, e o catálogo em memória é restaurado no final para não
    vazar estado entre testes."""
    from sicoobito.config import Settings, get_settings

    engine = client.app.state.engine
    original_default = engine.catalog.default_profile
    routes_copy = tmp_path / "routes.yaml"
    routes_copy.write_text(
        get_settings().routes_file.read_text(encoding="utf-8"), encoding="utf-8"
    )

    fake_settings = Settings(SICOOBITO_CONFIG_DIR=tmp_path)
    client.app.dependency_overrides[get_settings] = lambda: fake_settings
    try:
        response = client.post(
            "/api/providers/default-profile",
            headers={"Authorization": "Bearer chave-de-teste"},
            json={"profile": "cheap"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["default_profile"] == "cheap"
        assert next(p for p in body["profiles"] if p["name"] == "cheap")["is_default"] is True
        assert engine.catalog.default_profile == "cheap"
        assert "default_profile: cheap" in routes_copy.read_text(encoding="utf-8")
    finally:
        engine.catalog.default_profile = original_default
        client.app.dependency_overrides.pop(get_settings, None)


def test_set_default_profile_rejects_unknown_profile(client):
    response = client.post(
        "/api/providers/default-profile",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"profile": "perfil-que-nao-existe"},
    )
    assert response.status_code == 404


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
    # O que importa é **não** ser 404: o perfil padrão assumiu o modelo
    # desconhecido em vez de recusar. O código exato depende do ambiente — 503
    # quando não há provedor no ar, 200 quando o Ollama do compose responde —, e
    # amarrar o teste a um deles o faz falhar justamente quando a plataforma
    # passa a funcionar.
    assert response.status_code != 404
    assert response.status_code in {200, 502, 503}
