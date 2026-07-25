"""Interface comum dos adaptadores de provedor.

Um adaptador traduz uma entrada do `providers.yaml` em parâmetros do litellm e
sabe dizer se as credenciais necessárias existem. É o único lugar onde detalhe
de fornecedor é permitido (ver ADR 0001).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sicoobito.config import Settings
from sicoobito.router.catalog import ModelSpec


@dataclass(slots=True)
class HealthResult:
    ok: bool
    detail: str | None = None
    latency_ms: int | None = None


class ProviderAdapter(ABC):
    """Base dos adaptadores. Uma instância por provedor, não por modelo."""

    name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        """Nomes das variáveis de ambiente obrigatórias que estão vazias."""

    @abstractmethod
    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        """Parâmetros `litellm_params` da rota correspondente a este modelo."""

    async def healthcheck(self, spec: ModelSpec) -> HealthResult:
        """Verificação leve de conectividade. Default: confia nas credenciais.

        Adaptadores com endpoint barato de listagem (Ollama) sobrescrevem isto.
        """
        missing = self.missing_credentials(spec)
        if missing:
            return HealthResult(ok=False, detail=f"credenciais ausentes: {', '.join(missing)}")
        return HealthResult(ok=True, detail="credenciais presentes (sem verificação ativa)")

    def resolve(self, spec: ModelSpec) -> ModelSpec:
        """Marca disponibilidade e preenche `litellm_params`."""
        missing = self.missing_credentials(spec)
        if missing:
            spec.available = False
            spec.unavailable_reason = f"faltando {', '.join(missing)}"
            return spec
        spec.available = True
        spec.unavailable_reason = None
        spec.litellm_params = self.build_params(spec)
        return spec
