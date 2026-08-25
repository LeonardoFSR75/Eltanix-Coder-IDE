from __future__ import annotations

from novaai_studio.config import Settings
from novaai_studio.router.adapters import build_adapters


def test_catalog_loads_models_and_profiles(catalog):
    assert catalog.models, "providers.yaml não produziu nenhum modelo"
    assert "auto" in catalog.profiles
    assert catalog.default_profile in catalog.profiles


def test_every_profile_references_known_models(catalog):
    # `load_catalog` já descarta ids desconhecidos; o que sobra tem de existir.
    for profile in catalog.profiles.values():
        for model_id in profile.models:
            assert catalog.get(model_id) is not None, f"{profile.name} -> {model_id}"


def test_every_provider_has_an_adapter(catalog):
    adapters = build_adapters(Settings(_env_file=None))
    used = {spec.provider for spec in catalog.models.values()}
    missing = used - set(adapters)
    assert not missing, f"provedores sem adaptador: {missing}"


def test_ollama_resolves_without_credentials(catalog):
    settings = Settings(_env_file=None)
    adapters = build_adapters(settings)
    spec = catalog.get("ollama/qwen2.5-coder:7b")
    assert spec is not None

    adapters["ollama"].resolve(spec)
    assert spec.available is True
    # Chat precisa de /api/chat; `ollama/` cairia em /api/generate.
    assert spec.litellm_params["model"].startswith("ollama_chat/")


def test_embedding_model_uses_plain_ollama_prefix(catalog):
    settings = Settings(_env_file=None)
    adapters = build_adapters(settings)
    spec = catalog.get("ollama/nomic-embed-text")
    assert spec is not None

    adapters["ollama"].resolve(spec)
    assert spec.litellm_params["model"] == "ollama/nomic-embed-text"


def test_cloud_models_are_unavailable_without_credentials(catalog):
    settings = Settings(_env_file=None)
    adapters = build_adapters(settings)
    spec = catalog.get("foundry/gpt-4o")
    assert spec is not None

    adapters["azure_foundry"].resolve(spec)
    assert spec.available is False
    assert "AZURE_API_BASE" in (spec.unavailable_reason or "")


def test_azure_managed_uses_deployment_name(catalog):
    settings = Settings(
        _env_file=None,
        AZURE_API_BASE="https://exemplo.openai.azure.com",
        AZURE_API_KEY="chave",
    )
    adapters = build_adapters(settings)
    spec = catalog.get("foundry/gpt-4o")
    assert spec is not None

    adapters["azure_foundry"].resolve(spec)
    assert spec.available is True
    assert spec.litellm_params["model"] == "azure/gpt-4o"
    assert spec.litellm_params["api_version"]


def test_azure_serverless_uses_azure_ai_dialect(catalog):
    settings = Settings(
        _env_file=None,
        AZURE_AI_API_BASE="https://exemplo.services.ai.azure.com/models",
        AZURE_AI_API_KEY="chave",
    )
    adapters = build_adapters(settings)
    spec = catalog.get("foundry/llama-3.3-70b")
    assert spec is not None

    adapters["azure_foundry"].resolve(spec)
    assert spec.litellm_params["model"] == "azure_ai/Llama-3.3-70B-Instruct"


def test_databricks_points_at_serving_endpoints(catalog):
    settings = Settings(
        _env_file=None,
        DATABRICKS_HOST="https://exemplo.cloud.databricks.com/",
        DATABRICKS_TOKEN="dapi123",
    )
    adapters = build_adapters(settings)
    spec = catalog.get("databricks/llama-3.3-70b")
    assert spec is not None

    adapters["databricks"].resolve(spec)
    assert spec.litellm_params["api_base"].endswith("/serving-endpoints")
    # A barra final do host não pode duplicar no caminho.
    assert "//serving-endpoints" not in spec.litellm_params["api_base"]
