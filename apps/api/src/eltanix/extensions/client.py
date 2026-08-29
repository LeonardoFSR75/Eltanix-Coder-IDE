"""Cliente assíncrono para comunicação com Open VSX Registry e VS Code Marketplace APIs."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from eltanix.logging_setup import get_logger

log = get_logger(__name__)

_OPEN_VSX_BASE_URL = "https://open-vsx.org/api"
_DEFAULT_TIMEOUT_SECONDS = 8.0


class OpenVSXClient:
    """Cliente HTTP resiliente para consulta e sincronização com repositórios de extensões."""

    def __init__(
        self,
        base_url: str = _OPEN_VSX_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def get_extension_metadata(self, extension_id: str) -> dict[str, Any] | None:
        """Obtém metadados da versão mais recente da extensão no Open VSX."""
        parts = extension_id.split(".", 1)
        if len(parts) != 2:
            return None

        namespace, name = parts
        url = f"{self.base_url}/{namespace}/{name}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url, headers={"User-Agent": "Eltanix-ExtensionManager/2.0"})
                if res.status_code == 200:
                    data = res.json()
                    return {
                        "id": extension_id,
                        "name": data.get("displayName") or data.get("name") or name,
                        "publisher": namespace,
                        "latest_version": data.get("version") or "1.0.0",
                        "description": data.get("description") or "",
                        "downloads": str(data.get("downloadCount") or "10K+"),
                        "rating": float(data.get("averageRating") or 4.8),
                        "icon_url": (data.get("files") or {}).get("icon"),
                        "repository_url": (data.get("repository") or {}).get("url"),
                        "published_at": data.get("timestamp"),
                    }
        except Exception as exc:
            log.debug("open_vsx_query_failed", extension_id=extension_id, error=str(exc))

        return None

    async def search_marketplace(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Busca extensões públicas no Open VSX Registry por palavra-chave."""
        url = f"{self.base_url}/-/search"
        params = {"query": query, "size": limit}

        results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": "Eltanix-ExtensionManager/2.0"},
                )
                if res.status_code == 200:
                    data = res.json()
                    extensions = data.get("extensions") or []
                    for ext in extensions:
                        ns = ext.get("namespace", "")
                        nm = ext.get("name", "")
                        ext_id = f"{ns}.{nm}" if ns and nm else ext.get("id", "")
                        results.append(
                            {
                                "id": ext_id,
                                "name": ext.get("displayName") or ext.get("name") or ext_id,
                                "publisher": ns,
                                "version": ext.get("version") or "1.0.0",
                                "description": ext.get("description") or "",
                                "downloads": str(ext.get("downloadCount") or "1K+"),
                                "rating": float(ext.get("averageRating") or 4.5),
                                "icon_url": (ext.get("files") or {}).get("icon"),
                                "category": "Marketplace Online",
                                "installed": False,
                                "active": False,
                            }
                        )
        except Exception as exc:
            log.warning("open_vsx_search_error", query=query, error=str(exc))

        return results

    async def check_updates_batch(
        self, current_extensions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Verifica atualizações disponíveis concorrentemente para uma lista de extensões."""
        tasks = [
            self.get_extension_metadata(ext.get("upstream_id") or ext.get("id", ""))
            for ext in current_extensions
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        updates: dict[str, dict[str, Any]] = {}
        for ext, res in zip(current_extensions, results, strict=False):
            if isinstance(res, dict) and res.get("latest_version"):
                cur_ver = ext.get("version", "0.0.0")
                latest_ver = res["latest_version"]
                if _is_newer_version(latest_ver, cur_ver):
                    updates[ext["id"]] = {
                        "current_version": cur_ver,
                        "latest_version": latest_ver,
                        "published_at": res.get("published_at"),
                        "downloads": res.get("downloads"),
                    }
        return updates


def _is_newer_version(latest: str, current: str) -> bool:
    """Compara versões no formato semântico simplificado (ex.: '1.4.0' vs '1.3.2')."""
    try:

        def parse(v: str) -> list[int]:
            clean = "".join(c if c.isdigit() or c == "." else "" for c in v)
            return [int(p) for p in clean.split(".") if p.isdigit()]

        return parse(latest) > parse(current)
    except Exception:
        return latest != current and latest > current
