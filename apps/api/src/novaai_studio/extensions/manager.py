"""Gerenciador central de extensões, catálogo, estado de ativação e atualizações automáticas."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.extensions import store
from novaai_studio.extensions.catalog import MASTER_EXTENSIONS_CATALOG
from novaai_studio.extensions.client import OpenVSXClient
from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

_AUTO_SYNC_INTERVAL_SECONDS = 3600 * 6  # 6 horas
_SEARCH_CACHE_PREFIX = "novaai_studio:cache:extensions:search"
_SEARCH_CACHE_TTL_SECONDS = 600  # 10 min — o painel de Extensões busca a cada
# tecla digitada; o Open VSX não muda rápido o bastante para justificar bater
# nele a cada busca (mesmo padrão de `optimizer/cache.py`).


class ExtensionsManager:
    """Gerenciador de ciclo de vida e auto-update de extensões.

    O catálogo estático (`MASTER_EXTENSIONS_CATALOG`) fica em memória (nomes,
    descrições, categorias nunca mudam em runtime); ativação/versão/update
    pendente são um overlay carregado do Postgres (`extensions/store.py`) uma
    vez no startup (`hydrate()`) e regravado a cada mutação — troca o antigo
    `config/extensions_state.json` (escrita sem lock, arriscada sob acesso
    concorrente) por uma linha por extensão, no mesmo padrão de `Skill`.
    """

    def __init__(self, client: OpenVSXClient | None = None, redis: Redis | None = None) -> None:
        self.client = client or OpenVSXClient()
        self._redis = redis
        self._installed_map: dict[str, dict[str, Any]] = {}
        self._enabled_map: dict[str, bool] = {}
        self._pending_updates: dict[str, dict[str, Any]] = {}
        self._last_sync_timestamp: float = 0.0
        self._auto_update_enabled: bool = True
        self._sync_lock = asyncio.Lock()
        self._hydrated = False

        for ext in MASTER_EXTENSIONS_CATALOG:
            self._installed_map[ext.id] = ext.to_dict()
            self._enabled_map[ext.id] = ext.active

    async def hydrate(self, session: AsyncSession) -> None:
        """Carrega o overlay persistido do Postgres para a memória. Chamado uma
        vez no `lifespan` da app; best-effort — se falhar, opera só com os
        defaults do catálogo estático (mesma filosofia de degradação graciosa
        de `router/health.py` para Redis indisponível)."""
        try:
            states = await store.list_states(session)
            settings = await store.get_settings(session)
        except Exception as exc:
            log.warning("failed_to_hydrate_extensions_state", error=str(exc))
            return

        for ext_id, state in states.items():
            self._enabled_map[ext_id] = state.active
            if state.installed_version:
                overlay = self._installed_map.setdefault(ext_id, {"id": ext_id})
                overlay["version"] = state.installed_version
            if state.pending_update_json:
                try:
                    self._pending_updates[ext_id] = json.loads(state.pending_update_json)
                except (json.JSONDecodeError, TypeError):
                    pass

        self._auto_update_enabled = settings.auto_update_enabled
        self._last_sync_timestamp = settings.last_sync_timestamp
        self._hydrated = True

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

    def is_active(self, extension_id: str) -> bool:
        """Usado pelo gateway de LSP (`api/routes/lsp.py`) para checar se a
        extensão associada a um servidor está ligada antes de abrir sessão."""
        return self._enabled_map.get(extension_id, True)

    async def toggle_extension(
        self, session: AsyncSession, extension_id: str, active: bool | None = None
    ) -> bool | None:
        """Ativa ou desativa uma extensão. `None` se o id não existe no catálogo."""
        if extension_id not in self._installed_map:
            return None

        cur_active = self._enabled_map.get(extension_id, True)
        new_active = not cur_active if active is None else active
        self._enabled_map[extension_id] = new_active
        await store.upsert_state(session, extension_id, active=new_active)
        return new_active

    async def set_auto_update(self, session: AsyncSession, enabled: bool) -> bool:
        self._auto_update_enabled = enabled
        await store.update_settings(session, auto_update_enabled=enabled)
        return self._auto_update_enabled

    async def sync_with_marketplace(
        self, session: AsyncSession, force: bool = False
    ) -> dict[str, Any]:
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
                for ext_id, update_info in updates.items():
                    await store.upsert_state(
                        session,
                        ext_id,
                        pending_update_json=json.dumps(update_info, ensure_ascii=False),
                    )

                # Se o auto-update estiver ativo, aplica atualizações seguras automaticamente
                if self._auto_update_enabled and updates:
                    for ext_id in list(updates.keys()):
                        await self.update_extension(session, ext_id)

                await store.update_settings(session, last_sync_timestamp=now)
                log.info("extensions_sync_completed", updates_found=len(updates))
            except Exception as exc:
                log.error("extensions_sync_failed", error=str(exc))

            return self.get_catalog()

    async def update_extension(self, session: AsyncSession, extension_id: str) -> bool:
        """Atualiza a versão de uma extensão específica."""
        update_info = self._pending_updates.pop(extension_id, None)
        if not update_info or extension_id not in self._installed_map:
            return False

        latest_ver = update_info["latest_version"]
        self._installed_map[extension_id]["version"] = latest_ver
        await store.upsert_state(
            session, extension_id, installed_version=latest_ver, pending_update_json=None
        )
        log.info("extension_updated", id=extension_id, new_version=latest_ver)
        return True

    async def update_all_extensions(self, session: AsyncSession) -> int:
        """Atualiza todas as extensões que possuem atualizações pendentes."""
        count = 0
        for ext_id in list(self._pending_updates.keys()):
            if await self.update_extension(session, ext_id):
                count += 1
        return count

    def configure_redis(self, redis: Redis | None) -> None:
        """Injeta o cliente Redis depois da criação: o singleton (`get_extensions_manager`)
        pode ser criado antes do `lifespan` conectar ao Redis (ver `main.py`)."""
        self._redis = redis

    async def search_online(self, query: str) -> list[dict[str, Any]]:
        """Busca extensões online no Open VSX Registry, cacheada em Redis por
        `_SEARCH_CACHE_TTL_SECONDS`. Sem Redis, busca direto — mesma degradação
        graciosa do resto do serviço."""
        cache_key = None
        if self._redis is not None:
            digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
            cache_key = f"{_SEARCH_CACHE_PREFIX}:{digest}"
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as exc:
                log.warning("extensions.search_cache_unavailable", error=str(exc))

        results = await self.client.search_marketplace(query)

        if cache_key is not None and results:
            try:
                await self._redis.set(
                    cache_key, json.dumps(results, ensure_ascii=False), ex=_SEARCH_CACHE_TTL_SECONDS
                )
            except Exception as exc:
                log.warning("extensions.search_cache_unavailable", error=str(exc))

        return results


# Singleton — instanciado uma vez em `main.py::lifespan` e guardado em
# `app.state.extensions_manager` (mesmo padrão dos demais serviços com
# estado); esta função continua existindo para os poucos call sites que ainda
# não recebem o serviço via `app.state`/`ToolContext`.
_INSTANCE: ExtensionsManager | None = None


def get_extensions_manager() -> ExtensionsManager:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ExtensionsManager()
    return _INSTANCE
