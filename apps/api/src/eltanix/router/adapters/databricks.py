"""Databricks Model Serving."""

from __future__ import annotations

from typing import Any

import httpx

from eltanix.router.adapters.base import DiscoveredModel, DiscoveryError, ProviderAdapter
from eltanix.router.catalog import ModelSpec


class DatabricksAdapter(ProviderAdapter):
    name = "databricks"

    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        missing: list[str] = []
        if not self.settings.databricks_host:
            missing.append("DATABRICKS_HOST")
        if not self.settings.databricks_token:
            missing.append("DATABRICKS_TOKEN")
        return missing

    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        host = self.settings.databricks_host.rstrip("/")
        return {
            "model": f"databricks/{spec.endpoint or spec.model}",
            "api_base": f"{host}/serving-endpoints",
            "api_key": self.settings.databricks_token,
        }

    async def discover_models(self) -> list[DiscoveredModel]:
        if not self.settings.databricks_host or not self.settings.databricks_token:
            return []

        host = self.settings.databricks_host.rstrip("/")
        url = f"{host}/api/2.0/serving-endpoints"
        headers = {"Authorization": f"Bearer {self.settings.databricks_token}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise DiscoveryError(
                    "Databricks: Permissão negada (403 Forbidden). O token não possui permissão "
                    "de leitura em '/api/2.0/serving-endpoints'. Verifique as permissões do PAT "
                    "ou cadastre o modelo manualmente."
                ) from exc
            if exc.response.status_code == 401:
                raise DiscoveryError(
                    "Databricks: Token inválido ou expirado (401 Unauthorized). Verifique o "
                    "DATABRICKS_TOKEN em Configurações."
                ) from exc
            raise DiscoveryError(f"Databricks: {exc}") from exc
        except Exception as exc:
            raise DiscoveryError(f"Databricks: {exc}") from exc

        discovered: list[DiscoveredModel] = []
        for item in data.get("endpoints", []):
            name = item.get("name")
            if not name:
                continue
            # `task` vem do endpoint, não é heurística: "llm/v1/embeddings"
            # diferencia embedding de chat com dado real do provedor.
            tasks = {
                entity.get("task")
                for entity in (item.get("config") or {}).get("served_entities", [])
                if entity.get("task")
            }
            is_embedding = "llm/v1/embeddings" in tasks
            discovered.append(
                DiscoveredModel(
                    suggested_id=f"databricks/{name}",
                    provider="databricks",
                    raw_name=name,
                    endpoint=name,
                    capabilities=["embedding"] if is_embedding else ["chat"],
                    estimated_fields=["context_window"],
                )
            )
        return discovered
