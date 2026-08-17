"""Gerenciador central de extensões, catálogo, estado de ativação e atualizações automáticas.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from sicoobito.extensions.catalog import MASTER_EXTENSIONS_CATALOG, ExtensionDefinition
from sicoobito.extensions.client import OpenVSXClient
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

_STATE_FILE_PATH = Path("config/extensions_state.json")
_AUTO_SYNC_INTERVAL_SECONDS = 3600 * 6  # 6 horas


class ExtensionsManager:
    """Gerenciador de ciclo de vida, persistência e auto-update de extensões."""

    def __init__(
        self,
        state_file: Path = _STATE_FILE_PATH,
        client: OpenVSXClient | None = None,
    ) -> None:
        self.state_file = state_file
        self.client = client or OpenVSXClient()
        self._installed_map: dict[str, dict[str, Any]] = {}
        self._enabled_map: dict[str, bool] = {}
        self._pending_updates: dict[str, dict[str, Any]] = {}
        self._last_sync_timestamp: float = 0.0
        self._auto_update_enabled: bool = True
        self._sync_lock = asyncio.Lock()
        self._load_state()

    def _load_state(self) -> None:
        """Carrega catálogo padrão e mescla com estado persistido em disco."""
        for ext in MASTER_EXTENSIONS_CATALOG:
            self._installed_map[ext.id] = ext.to_dict()
            self._enabled_map[ext.id] = ext.active

        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                for ext_id, ext_data in data.get("installed", {}).items():
                    if ext_id in self._installed_map:
                        self._installed_map[ext_id].update(ext_data)
                    else:
                        self._installed_map[ext_id] = ext_data

                self._enabled_map.update(data.get("enabled", {}))
                self._pending_updates = data.get("pending_updates", {})
                self._last_sync_timestamp = float(data.get("last_sync_timestamp", 0.0))
                self._auto_update_enabled = bool(data.get("auto_update_enabled", True))
            except Exception as exc:
                log.warning("failed_to_load_extensions_state", error=str(exc))

    def _save_state(self) -> None:
        """Persiste estado de extensões em disco."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "installed": self._installed_map,
                "enabled": self._enabled_map,
                "pending_updates": self._pending_updates,
                "last_sync_timestamp": self._last_sync_timestamp,
                "auto_update_enabled": self._auto_update_enabled,
            }
            self.state_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.warning("failed_to_save_extensions_state", error=str(exc))

    def get_catalog(self) -> dict[str, Any]:
        """Retorna o catálogo completo estruturado para o frontend."""
        items: list[dict[str, Any]] = []
        for ext_id, ext in self._installed_map.items():
            item = dict(ext)
            item["active"] = self._enabled_map.get(ext_id, True)
            update_info = self._pending_updates.get(ext_id)
            item["hasUpdate"] = bool(update_info)
            item["updateInfo"] = update_info
            items.append(item)

        return {
            "extensions": items,
            "total_count": len(items),
            "pending_updates_count": len(self._pending_updates),
            "last_sync_timestamp": self._last_sync_timestamp,
            "auto_update_enabled": self._auto_update_enabled,
        }

    def toggle_extension(self, extension_id: str, active: bool | None = None) -> bool:
        """Ativa ou desativa uma extensão."""
        if extension_id not in self._installed_map:
            return False

        cur_active = self._enabled_map.get(extension_id, True)
        new_active = not cur_active if active is None else active
        self._enabled_map[extension_id] = new_active
        self._save_state()
        return new_active

    def set_auto_update(self, enabled: bool) -> bool:
        """Habilita ou desabilita o auto-update automático."""
        self._auto_update_enabled = enabled
        self._save_state()
        return self._auto_update_enabled

    async def sync_with_marketplace(self, force: bool = False) -> dict[str, Any]:
        """Executa sincronização assíncrona com Open VSX Registry para buscar novas versões."""
        async with self._sync_lock:
            now = time.time()
            if not force and (now - self._last_sync_timestamp < 60):
                return self.get_catalog()

            extensions_list = list(self._installed_map.values())
            try:
                updates = await self.client.check_updates_batch(extensions_list)
                self._pending_updates = updates
                self._last_sync_timestamp = now

                # Se o auto-update estiver ativo, aplica atualizações seguras automaticamente
                if self._auto_update_enabled and updates:
                    for ext_id, u_info in list(updates.items()):
                        self.update_extension(ext_id)

                self._save_state()
                log.info("extensions_sync_completed", updates_found=len(updates))
            except Exception as exc:
                log.error("extensions_sync_failed", error=str(exc))

            return self.get_catalog()

    def update_extension(self, extension_id: str) -> bool:
        """Atualiza a versão de uma extensão específica."""
        update_info = self._pending_updates.pop(extension_id, None)
        if not update_info or extension_id not in self._installed_map:
            return False

        latest_ver = update_info["latest_version"]
        self._installed_map[extension_id]["version"] = latest_ver
        self._save_state()
        log.info("extension_updated", id=extension_id, new_version=latest_ver)
        return True

    def update_all_extensions(self) -> int:
        """Atualiza todas as extensões que possuem atualizações pendentes."""
        count = 0
        for ext_id in list(self._pending_updates.keys()):
            if self.update_extension(ext_id):
                count += 1
        return count

    async def search_online(self, query: str) -> list[dict[str, Any]]:
        """Busca extensões online no Open VSX Registry."""
        return await self.client.search_marketplace(query)


# Singleton
_INSTANCE: ExtensionsManager | None = None


def get_extensions_manager() -> ExtensionsManager:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ExtensionsManager()
    return _INSTANCE
