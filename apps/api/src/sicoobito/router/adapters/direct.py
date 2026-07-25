"""Provedores diretos (OpenAI, Anthropic).

Existem no catálogo para comparação de qualidade e custo contra as opções
corporativas — não são caminho preferencial.
"""

from __future__ import annotations

from typing import Any

from sicoobito.router.adapters.base import ProviderAdapter
from sicoobito.router.catalog import ModelSpec


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
