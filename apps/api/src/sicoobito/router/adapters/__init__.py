from __future__ import annotations

from sicoobito.config import Settings
from sicoobito.router.adapters.azure_foundry import AzureFoundryAdapter
from sicoobito.router.adapters.base import (
    DiscoveredModel,
    DiscoveryError,
    HealthResult,
    ProviderAdapter,
)
from sicoobito.router.adapters.databricks import DatabricksAdapter
from sicoobito.router.adapters.direct import AnthropicAdapter, GroqAdapter, OpenAIAdapter
from sicoobito.router.adapters.ollama import OllamaAdapter

_ADAPTER_TYPES: list[type[ProviderAdapter]] = [
    OllamaAdapter,
    AzureFoundryAdapter,
    DatabricksAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    GroqAdapter,
]


def build_adapters(settings: Settings) -> dict[str, ProviderAdapter]:
    """Instancia um adaptador por provedor, indexado pelo nome usado no YAML."""
    return {cls.name: cls(settings) for cls in _ADAPTER_TYPES}


__all__ = [
    "AnthropicAdapter",
    "AzureFoundryAdapter",
    "DatabricksAdapter",
    "DiscoveredModel",
    "DiscoveryError",
    "GroqAdapter",
    "HealthResult",
    "OllamaAdapter",
    "OpenAIAdapter",
    "ProviderAdapter",
    "build_adapters",
]
