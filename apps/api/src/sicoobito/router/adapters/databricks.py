"""Databricks Model Serving."""

from __future__ import annotations

from typing import Any

from sicoobito.router.adapters.base import ProviderAdapter
from sicoobito.router.catalog import ModelSpec


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
