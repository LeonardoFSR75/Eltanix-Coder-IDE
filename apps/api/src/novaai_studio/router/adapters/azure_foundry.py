"""Azure AI Foundry.

Dois modos convivem no catálogo e precisam de tratamento diferente:

- `managed`    deployment do Azure OpenAI. O identificador é o **nome do
               deployment**, não o do modelo, e a chamada exige `api_version`.
- `serverless` endpoint MaaS do catálogo Foundry (Llama, Mistral, Phi...),
               que fala o dialeto `azure_ai/` e usa outro par base/chave.
"""

from __future__ import annotations

from typing import Any

from novaai_studio.router.adapters.base import ProviderAdapter
from novaai_studio.router.catalog import ModelSpec


class AzureFoundryAdapter(ProviderAdapter):
    name = "azure_foundry"

    def _is_serverless(self, spec: ModelSpec) -> bool:
        return (spec.mode or "managed") == "serverless"

    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        missing: list[str] = []
        if self._is_serverless(spec):
            if not self.settings.azure_ai_api_base:
                missing.append("AZURE_AI_API_BASE")
            if not self.settings.azure_ai_api_key:
                missing.append("AZURE_AI_API_KEY")
            return missing

        if not self.settings.azure_api_base:
            missing.append("AZURE_API_BASE")
        # Com Entra ID a chave é dispensável: o token vem do azure-identity.
        if not self.settings.azure_api_key and not self.settings.azure_use_entra_id:
            missing.append("AZURE_API_KEY")
        return missing

    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        if self._is_serverless(spec):
            return {
                "model": f"azure_ai/{spec.model}",
                "api_base": self.settings.azure_ai_api_base,
                "api_key": self.settings.azure_ai_api_key,
            }

        params: dict[str, Any] = {
            "model": f"azure/{spec.deployment or spec.model}",
            "api_base": self.settings.azure_api_base,
            "api_version": self.settings.azure_api_version,
        }
        if self.settings.azure_use_entra_id:
            params["azure_ad_token_provider"] = _entra_token_provider()
        else:
            params["api_key"] = self.settings.azure_api_key
        return params


def _entra_token_provider():
    """Provider de token AAD. Importado sob demanda: `azure-identity` é opcional."""
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    except ImportError as exc:  # pragma: no cover - depende do extra instalado
        raise RuntimeError(
            "AZURE_USE_ENTRA_ID=true exige o extra `azure`: uv sync --extra azure"
        ) from exc

    return get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
