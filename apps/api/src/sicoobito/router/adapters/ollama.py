"""Ollama — inferência local. Base da política `local-first` e do custo zero."""

from __future__ import annotations

import time
from typing import Any

import httpx

from sicoobito.router.adapters.base import HealthResult, ProviderAdapter
from sicoobito.router.catalog import ModelSpec


class OllamaAdapter(ProviderAdapter):
    name = "ollama"

    def missing_credentials(self, spec: ModelSpec) -> list[str]:
        # Ollama local não usa credencial; só precisa da URL configurada.
        return [] if self.settings.ollama_base_url else ["OLLAMA_BASE_URL"]

    def build_params(self, spec: ModelSpec) -> dict[str, Any]:
        # `ollama_chat/` usa /api/chat (com suporte a roles e tools); `ollama/`
        # cai no /api/generate, que não serve para conversa nem ferramentas.
        prefix = "ollama" if spec.is_embedding else "ollama_chat"
        return {
            "model": f"{prefix}/{spec.model}",
            "api_base": self.settings.ollama_base_url,
        }

    async def healthcheck(self, spec: ModelSpec) -> HealthResult:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/tags"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                installed = {m.get("name", "") for m in response.json().get("models", [])}
        except Exception as exc:
            return HealthResult(ok=False, detail=f"{type(exc).__name__}: {exc}")

        latency = int((time.perf_counter() - started) * 1000)
        wanted = spec.model or ""
        # O Ollama reporta "modelo:tag"; aceitar o nome sem tag evita falso negativo.
        base = wanted.split(":")[0]
        if wanted and not any(n == wanted or n.split(":")[0] == base for n in installed):
            return HealthResult(
                ok=False,
                detail=f"modelo não baixado — rode: ollama pull {wanted}",
                latency_ms=latency,
            )
        return HealthResult(ok=True, detail="online", latency_ms=latency)
