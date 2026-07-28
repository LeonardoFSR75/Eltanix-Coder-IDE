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


def _routes_copy(tmp_path):
    from sicoobito.config import get_settings

    routes_file = tmp_path / "routes.yaml"
    routes_file.write_text(
        get_settings().routes_file.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return routes_file


def test_routes_editor_upsert_new_profile_preserves_comments(tmp_path):
    """A garantia real deste módulo: um perfil novo não pode deslocar o
    comentário de rodapé do arquivo para dentro do bloco `profiles`."""
    from sicoobito.router import routes_editor

    routes_file = _routes_copy(tmp_path)

    data = routes_editor.load(routes_file)
    routes_editor.upsert_profile(
        data,
        "meu-teste",
        strategy="priority",
        models=["ollama/qwen2.5-coder:1.5b"],
        weights=None,
    )
    routes_editor.dump(routes_file, data)

    updated = routes_file.read_text(encoding="utf-8")
    footer = "# Resiliência aplicada a todos os perfis."
    assert footer in updated

    new_profile_idx = updated.index("meu-teste:")
    footer_idx = updated.index(footer)
    resilience_idx = updated.index("resilience:")
    assert new_profile_idx < footer_idx < resilience_idx

    # Perfis pré-existentes (conteúdo e comentários) continuam intactos.
    assert "auto:" in updated and "embedding:" in updated
    assert "# O maior redutor de custo do projeto" in updated


def test_routes_editor_upsert_existing_profile_replaces_in_place(tmp_path):
    from sicoobito.router import routes_editor

    routes_file = _routes_copy(tmp_path)

    data = routes_editor.load(routes_file)
    routes_editor.upsert_profile(
        data,
        "cheap",
        strategy="cost",
        models=["ollama/qwen2.5-coder:1.5b", "foundry/gpt-4o"],
        weights=None,
    )
    routes_editor.dump(routes_file, data)

    updated = routes_file.read_text(encoding="utf-8")
    assert "- foundry/gpt-4o\n" in updated
    assert "# O maior redutor de custo do projeto" in updated
    assert "# Resiliência aplicada a todos os perfis." in updated


def test_routes_editor_delete_profile(tmp_path):
    from sicoobito.router import routes_editor

    routes_file = _routes_copy(tmp_path)

    data = routes_editor.load(routes_file)
    routes_editor.delete_profile(data, "fast")
    routes_editor.dump(routes_file, data)

    updated = routes_file.read_text(encoding="utf-8")
    assert "fast:" not in updated
    assert "# Resiliência aplicada a todos os perfis." in updated


def test_upsert_profile_endpoint_creates_and_persists(client, tmp_path):
    from sicoobito.config import Settings, get_settings

    engine = client.app.state.engine
    routes_copy = _routes_copy(tmp_path)
    fake_settings = Settings(SICOOBITO_CONFIG_DIR=tmp_path)
    client.app.dependency_overrides[get_settings] = lambda: fake_settings
    try:
        response = client.put(
            "/api/providers/profiles/meu-teste",
            headers={"Authorization": "Bearer chave-de-teste"},
            json={
                "strategy": "score",
                "models": ["ollama/qwen2.5-coder:1.5b", "foundry/gpt-4o-mini"],
                "weights": {"health": 0.5, "cost": 0.5},
            },
        )
        assert response.status_code == 200
        criado = next(p for p in response.json()["profiles"] if p["name"] == "meu-teste")
        assert criado["strategy"] == "score"
        assert criado["models"] == ["ollama/qwen2.5-coder:1.5b", "foundry/gpt-4o-mini"]
        assert criado["weights"] == {"health": 0.5, "cost": 0.5}
        assert engine.catalog.profile("meu-teste") is not None

        persisted = routes_copy.read_text(encoding="utf-8")
        assert "meu-teste:" in persisted
        assert "# Resiliência aplicada a todos os perfis." in persisted
    finally:
        engine.catalog.profiles.pop("meu-teste", None)
        client.app.dependency_overrides.pop(get_settings, None)


def test_upsert_profile_rejects_unknown_model(client):
    response = client.put(
        "/api/providers/profiles/meu-teste-2",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"strategy": "priority", "models": ["modelo-que-nao-existe"]},
    )
    assert response.status_code == 400
    assert client.app.state.engine.catalog.profile("meu-teste-2") is None


def test_upsert_profile_rejects_invalid_name(client):
    response = client.put(
        "/api/providers/profiles/Nome Inválido!",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"strategy": "priority", "models": ["ollama/qwen2.5-coder:1.5b"]},
    )
    assert response.status_code == 400


def test_upsert_profile_rejects_invalid_strategy(client):
    response = client.put(
        "/api/providers/profiles/meu-teste-3",
        headers={"Authorization": "Bearer chave-de-teste"},
        json={"strategy": "roleta-russa", "models": ["ollama/qwen2.5-coder:1.5b"]},
    )
    assert response.status_code == 422


def test_delete_profile_requires_switching_default_first(client):
    engine = client.app.state.engine
    response = client.delete(
        f"/api/providers/profiles/{engine.catalog.default_profile}",
        headers={"Authorization": "Bearer chave-de-teste"},
    )
    assert response.status_code == 400


def test_delete_profile_rejects_unknown_profile(client):
    response = client.delete(
        "/api/providers/profiles/perfil-que-nao-existe",
        headers={"Authorization": "Bearer chave-de-teste"},
    )
    assert response.status_code == 404


def test_delete_profile_endpoint_removes_custom_profile(client, tmp_path):
    from sicoobito.config import Settings, get_settings
    from sicoobito.router import routes_editor
    from sicoobito.router.catalog import RouteProfile

    engine = client.app.state.engine
    engine.catalog.profiles["descartavel"] = RouteProfile(
        name="descartavel", strategy="priority", models=["ollama/qwen2.5-coder:1.5b"]
    )
    routes_copy = _routes_copy(tmp_path)
    data = routes_editor.load(routes_copy)
    routes_editor.upsert_profile(
        data, "descartavel", strategy="priority", models=["ollama/qwen2.5-coder:1.5b"], weights=None
    )
    routes_editor.dump(routes_copy, data)

    fake_settings = Settings(SICOOBITO_CONFIG_DIR=tmp_path)
    client.app.dependency_overrides[get_settings] = lambda: fake_settings
    try:
        response = client.delete(
            "/api/providers/profiles/descartavel",
            headers={"Authorization": "Bearer chave-de-teste"},
        )
        assert response.status_code == 200
        assert all(p["name"] != "descartavel" for p in response.json()["profiles"])
        assert engine.catalog.profile("descartavel") is None
        assert "descartavel:" not in routes_copy.read_text(encoding="utf-8")
    finally:
        engine.catalog.profiles.pop("descartavel", None)
        client.app.dependency_overrides.pop(get_settings, None)


def test_env_editor_write_and_read_roundtrip(tmp_path):
    from sicoobito.router import env_editor

    env_file = tmp_path / ".env"
    env_file.write_text("# comentário\nEXISTENTE=valor-antigo\nOUTRA=fica\n", encoding="utf-8")

    env_editor.write_values(env_file, {"EXISTENTE": "valor-novo", "NOVA": "recem-criada"})

    content = env_file.read_text(encoding="utf-8")
    assert "EXISTENTE=valor-novo" in content
    assert "NOVA=recem-criada" in content
    assert "# comentário" in content
    assert "OUTRA=fica" in content
    assert "EXISTENTE=valor-antigo" not in content

    values = env_editor.read_values(env_file, ["EXISTENTE", "NOVA", "AUSENTE"])
    assert values == {"EXISTENTE": "valor-novo", "NOVA": "recem-criada", "AUSENTE": ""}


def test_env_editor_read_values_missing_file(tmp_path):
    from sicoobito.router import env_editor

    values = env_editor.read_values(tmp_path / "nao-existe.env", ["A", "B"])
    assert values == {"A": "", "B": ""}


def test_get_credentials_never_exposes_secret_values(client):
    response = client.get(
        "/api/providers/credentials", headers={"Authorization": "Bearer chave-de-teste"}
    )
    assert response.status_code == 200
    creds = response.json()["credentials"]
    campos_secretos = (
        "azure_api_key",
        "databricks_token",
        "openai_api_key",
        "anthropic_api_key",
        "github_token",
    )
    for campo in campos_secretos:
        assert creds[campo]["value"] is None
    for campo in ("ollama_base_url", "azure_api_base", "databricks_host"):
        assert "value" in creds[campo]
        assert creds[campo]["masked"] is None


def test_update_credentials_applies_immediately_and_persists(client, tmp_path):
    """A gravação é redirecionada para um `.env` em tmp_path via override de
    `get_settings` — sem isso o teste escreveria no `.env` real do projeto."""
    from sicoobito.config import Settings, get_settings

    engine = client.app.state.engine
    original_ollama = engine.settings.ollama_base_url
    original_openai_key = engine.settings.openai_api_key

    env_copy = tmp_path / ".env"
    env_copy.write_text("SOME_OTHER_VAR=mantido\n", encoding="utf-8")

    fake_settings = Settings(SICOOBITO_ENV_FILE=env_copy)
    client.app.dependency_overrides[get_settings] = lambda: fake_settings
    try:
        response = client.put(
            "/api/providers/credentials",
            headers={"Authorization": "Bearer chave-de-teste"},
            json={"ollama_base_url": "http://localhost:22222", "openai_api_key": "sk-teste-1234"},
        )
        assert response.status_code == 200
        creds = response.json()["credentials"]
        assert creds["ollama_base_url"]["value"] == "http://localhost:22222"
        assert creds["openai_api_key"]["configured"] is True
        assert creds["openai_api_key"]["masked"] == "••••1234"
        assert creds["openai_api_key"]["value"] is None

        # Efeito imediato: nada disso exige restart da API.
        assert engine.settings.ollama_base_url == "http://localhost:22222"
        assert engine.settings.openai_api_key == "sk-teste-1234"

        persisted = env_copy.read_text(encoding="utf-8")
        assert "OLLAMA_BASE_URL=http://localhost:22222" in persisted
        assert "OPENAI_API_KEY=sk-teste-1234" in persisted
        assert "SOME_OTHER_VAR=mantido" in persisted
    finally:
        engine.settings.ollama_base_url = original_ollama
        engine.settings.openai_api_key = original_openai_key
        engine.resolve_catalog()
        engine.build()
        client.app.dependency_overrides.pop(get_settings, None)


def test_update_credentials_partial_update_preserves_other_fields(client, tmp_path):
    from sicoobito.config import Settings, get_settings

    engine = client.app.state.engine
    original_github = engine.settings.github_token
    original_anthropic = engine.settings.anthropic_api_key

    fake_settings = Settings(SICOOBITO_ENV_FILE=tmp_path / ".env")
    client.app.dependency_overrides[get_settings] = lambda: fake_settings
    try:
        client.put(
            "/api/providers/credentials",
            headers={"Authorization": "Bearer chave-de-teste"},
            json={"github_token": "ghp_primeiro"},
        )
        response = client.put(
            "/api/providers/credentials",
            headers={"Authorization": "Bearer chave-de-teste"},
            json={"anthropic_api_key": "sk-ant-segundo"},
        )
        assert response.status_code == 200
        # O segundo PUT não menciona github_token — tem que continuar valendo.
        assert engine.settings.github_token == "ghp_primeiro"
        assert engine.settings.anthropic_api_key == "sk-ant-segundo"
    finally:
        engine.settings.github_token = original_github
        engine.settings.anthropic_api_key = original_anthropic
        engine.resolve_catalog()
        engine.build()
        client.app.dependency_overrides.pop(get_settings, None)


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
