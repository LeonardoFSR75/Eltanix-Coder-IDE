"""Ollama — inferência local. Base da política `local-first` e do custo zero."""

from __future__ import annotations

import time
from typing import Any

import httpx

from novaai_studio.router.adapters.base import (
    DiscoveredModel,
    DiscoveryError,
    HealthResult,
    ProviderAdapter,
)
from novaai_studio.router.catalog import ModelSpec

# Pistas no nome que indicam modelo de embedding — o Ollama não expõe essa
# distinção em /api/tags, então é heurística, não fato (ver DiscoveredModel).
_EMBEDDING_NAME_HINTS = ("embed", "bge", "nomic", "minilm", "e5-")


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

    async def _fetch_tags(self) -> list[dict[str, Any]]:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return list(response.json().get("models", []))

    async def healthcheck(self, spec: ModelSpec) -> HealthResult:
        started = time.perf_counter()
        try:
            tags = await self._fetch_tags()
        except Exception as exc:
            return HealthResult(ok=False, detail=f"{type(exc).__name__}: {exc}")

        installed = {m.get("name", "") for m in tags}
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

    async def discover_models(self) -> list[DiscoveredModel]:
        if not self.settings.ollama_base_url:
            return []
        try:
            tags = await self._fetch_tags()
        except Exception as exc:
            raise DiscoveryError(f"Ollama: {exc}") from exc

        discovered: list[DiscoveredModel] = []
        for entry in tags:
            name = entry.get("name", "")
            if not name:
                continue
            is_embedding = any(hint in name.lower() for hint in _EMBEDDING_NAME_HINTS)
            discovered.append(
                DiscoveredModel(
                    suggested_id=f"ollama/{name}",
                    provider="ollama",
                    raw_name=name,
                    model=name,
                    capabilities=["embedding"] if is_embedding else ["chat", "tools"],
                    estimated_fields=["context_window", "capabilities"],
                )
            )
        return discovered
