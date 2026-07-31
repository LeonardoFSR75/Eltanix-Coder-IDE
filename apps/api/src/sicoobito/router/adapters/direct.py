"""Provedores diretos (OpenAI, Anthropic).

Existem no catálogo para comparação de qualidade e custo contra as opções
corporativas — não são caminho preferencial.
"""

from __future__ import annotations

from typing import Any

import httpx

from sicoobito.router.adapters.base import DiscoveredModel, DiscoveryError, ProviderAdapter
from sicoobito.router.catalog import ModelSpec

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models?limit=1000"
_ANTHROPIC_API_VERSION = "2023-06-01"


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        return [] if self.settings.openai_api_key else ["OPENAI_API_KEY"]

    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        return {"model": f"openai/{spec.model}", "api_key": self.settings.openai_api_key}


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        return [] if self.settings.anthropic_api_key else ["ANTHROPIC_API_KEY"]

    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        return {"model": f"anthropic/{spec.model}", "api_key": self.settings.anthropic_api_key}

    async def discover_models(self) -> list[DiscoveredModel]:
        if not self.settings.anthropic_api_key:
            return []

        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(_ANTHROPIC_MODELS_URL, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise DiscoveryError(f"Anthropic: {exc}") from exc

        # A listagem não devolve contexto nem capacidades — ambos ficam com
        # um palpite conservador, marcado em estimated_fields para a revisão
        # não tratar isso como fato.
        return [
            DiscoveredModel(
                suggested_id=f"anthropic/{item['id']}",
                provider="anthropic",
                raw_name=item["id"],
                model=item["id"],
                context_window=200_000,
                capabilities=["chat", "tools"],
                estimated_fields=["context_window", "capabilities"],
            )
            for item in data.get("data", [])
            if item.get("id")
        ]
