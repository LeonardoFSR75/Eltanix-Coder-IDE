"""Testes unitários para o gerenciador de extensões e cliente Open VSX.

`ExtensionsManager` persiste via `extensions/store.py` (Postgres) — os testes
abaixo isolam a lógica de negócio mockando o módulo `store`, no mesmo espírito
de não exigir Postgres real no dia a dia (`conftest.py::pg_session` cobre o
round-trip real, quando `DATABASE_URL_TEST` está definida)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import Response

from eltanix.db.models import ExtensionSettings, ExtensionState
from eltanix.extensions.catalog import MASTER_EXTENSIONS_CATALOG
from eltanix.extensions.client import OpenVSXClient, _is_newer_version
from eltanix.extensions.manager import ExtensionsManager

_FAKE_SESSION = object()  # store é mockado nestes testes — nunca toca o objeto


def test_master_catalog_contains_six_suites():
    categories = {ext.category for ext in MASTER_EXTENSIONS_CATALOG}
    expected_categories = {
        "Frontend & Visual",
        "IA & Web Scraping",
        "Bancos & RAG",
        "Segurança & Auditoria",
        "APIs & Testes",
        "Segundo Cérebro & Arquitetura",
    }
    assert expected_categories.issubset(categories)
    assert len(MASTER_EXTENSIONS_CATALOG) >= 20


def test_is_newer_version_comparison():
    assert _is_newer_version("1.5.0", "1.4.0") is True
    assert _is_newer_version("2.0.0", "1.9.9") is True
    assert _is_newer_version("1.4.1", "1.4.0") is True
    assert _is_newer_version("1.4.0", "1.4.0") is False
    assert _is_newer_version("1.3.9", "1.4.0") is False


async def test_extensions_manager_toggle_persists_via_store():
    mgr = ExtensionsManager()
    ext_id = "eltanix.shadcn-radix-studio"

    with patch("eltanix.extensions.manager.store.upsert_state", new=AsyncMock()) as mock_upsert:
        new_state = await mgr.toggle_extension(_FAKE_SESSION, ext_id, active=False)
        assert new_state is False
        mock_upsert.assert_awaited_once_with(_FAKE_SESSION, ext_id, active=False)

        target_ext = next(e for e in mgr.get_catalog()["extensions"] if e["id"] == ext_id)
        assert target_ext["active"] is False

        new_state = await mgr.toggle_extension(_FAKE_SESSION, ext_id, active=True)
        assert new_state is True


async def test_extensions_manager_toggle_unknown_id_returns_none():
    mgr = ExtensionsManager()
    with patch("eltanix.extensions.manager.store.upsert_state", new=AsyncMock()) as mock_upsert:
        result = await mgr.toggle_extension(_FAKE_SESSION, "nao.existe")
        assert result is None
        mock_upsert.assert_not_awaited()


async def test_extensions_manager_hydrate_loads_overlay_from_store():
    mgr = ExtensionsManager()
    ext_id = MASTER_EXTENSIONS_CATALOG[0].id
    states = {
        ext_id: ExtensionState(
            extension_id=ext_id,
            active=False,
            installed_version="9.9.9",
            pending_update_json='{"latest_version": "10.0.0"}',
        )
    }
    settings = ExtensionSettings(id=1, auto_update_enabled=False, last_sync_timestamp=123.0)

    with (
        patch(
            "eltanix.extensions.manager.store.list_states", new=AsyncMock(return_value=states)
        ),
        patch(
            "eltanix.extensions.manager.store.get_settings", new=AsyncMock(return_value=settings)
        ),
    ):
        await mgr.hydrate(_FAKE_SESSION)

    assert mgr.is_active(ext_id) is False
    assert mgr._installed_map[ext_id]["version"] == "9.9.9"
    assert mgr._pending_updates[ext_id]["latest_version"] == "10.0.0"
    assert mgr._auto_update_enabled is False
    assert mgr._hydrated is True


async def test_extensions_manager_hydrate_degrades_gracefully_on_error():
    mgr = ExtensionsManager()
    with patch(
        "eltanix.extensions.manager.store.list_states",
        new=AsyncMock(side_effect=RuntimeError("postgres indisponível")),
    ):
        await mgr.hydrate(_FAKE_SESSION)  # não deve levantar

    assert mgr._hydrated is False
    # Catálogo estático continua utilizável mesmo sem overlay.
    assert mgr.get_catalog()["total_count"] == len(MASTER_EXTENSIONS_CATALOG)


async def test_extensions_manager_sync_and_update():
    mock_client = AsyncMock(spec=OpenVSXClient)
    mock_client.check_updates_batch.return_value = {
        "eltanix.shadcn-radix-studio": {
            "current_version": "1.4.0",
            "latest_version": "1.5.0",
            "published_at": "2026-08-17T00:00:00Z",
            "downloads": "1.5M",
        }
    }
    mgr = ExtensionsManager(client=mock_client)
    mgr._auto_update_enabled = False  # Para inspecionar o pending update antes de aplicar

    with (
        patch("eltanix.extensions.manager.store.upsert_state", new=AsyncMock()),
        patch("eltanix.extensions.manager.store.update_settings", new=AsyncMock()),
    ):
        catalog = await mgr.sync_with_marketplace(_FAKE_SESSION, force=True)
        assert catalog["pending_updates_count"] == 1

        target_ext = next(
            e for e in catalog["extensions"] if e["id"] == "eltanix.shadcn-radix-studio"
        )
        assert target_ext["hasUpdate"] is True
        assert target_ext["updateInfo"]["latest_version"] == "1.5.0"

        updated_count = await mgr.update_all_extensions(_FAKE_SESSION)
        assert updated_count == 1

    catalog_after = mgr.get_catalog()
    assert catalog_after["pending_updates_count"] == 0
    target_ext_after = next(
        e for e in catalog_after["extensions"] if e["id"] == "eltanix.shadcn-radix-studio"
    )
    assert target_ext_after["version"] == "1.5.0"
    assert target_ext_after["hasUpdate"] is False


async def test_extensions_manager_search_online_without_redis_hits_client_every_time():
    mock_client = AsyncMock(spec=OpenVSXClient)
    mock_client.search_marketplace.return_value = [{"id": "foo.bar"}]
    mgr = ExtensionsManager(client=mock_client)

    await mgr.search_online("tailwind")
    await mgr.search_online("tailwind")

    assert mock_client.search_marketplace.call_count == 2


async def test_extensions_manager_search_online_caches_in_redis():
    mock_client = AsyncMock(spec=OpenVSXClient)
    mock_client.search_marketplace.return_value = [{"id": "bradlc.vscode-tailwindcss"}]

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # miss na primeira chamada

    mgr = ExtensionsManager(client=mock_client, redis=mock_redis)
    results = await mgr.search_online("tailwind")
    assert results == [{"id": "bradlc.vscode-tailwindcss"}]
    mock_client.search_marketplace.assert_awaited_once()
    mock_redis.set.assert_awaited_once()

    # Segunda chamada: Redis devolve o cache, cliente HTTP não é chamado de novo.
    cached_payload = mock_redis.set.call_args.args[1]
    mock_redis.get.return_value = cached_payload
    results_cached = await mgr.search_online("tailwind")
    assert results_cached == [{"id": "bradlc.vscode-tailwindcss"}]
    mock_client.search_marketplace.assert_awaited_once()  # ainda só uma vez


async def test_extensions_manager_search_online_degrades_when_redis_fails():
    mock_client = AsyncMock(spec=OpenVSXClient)
    mock_client.search_marketplace.return_value = [{"id": "foo.bar"}]

    mock_redis = AsyncMock()
    mock_redis.get.side_effect = RuntimeError("redis indisponível")
    mock_redis.set.side_effect = RuntimeError("redis indisponível")

    mgr = ExtensionsManager(client=mock_client, redis=mock_redis)
    results = await mgr.search_online("tailwind")  # não deve levantar
    assert results == [{"id": "foo.bar"}]


def test_extensions_manager_configure_redis_swaps_client():
    mgr = ExtensionsManager()
    assert mgr._redis is None
    sentinel = object()
    mgr.configure_redis(sentinel)
    assert mgr._redis is sentinel


async def test_open_vsx_client_search():
    client = OpenVSXClient()
    mock_response = Response(
        status_code=200,
        json={
            "extensions": [
                {
                    "namespace": "bradlc",
                    "name": "vscode-tailwindcss",
                    "version": "0.14.3",
                    "displayName": "Tailwind CSS IntelliSense",
                    "description": "Intelligent Tailwind CSS tooling for VS Code",
                    "downloadCount": 15000000,
                    "averageRating": 4.9,
                    "files": {"icon": "https://open-vsx.org/icon.png"},
                }
            ]
        },
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        results = await client.search_marketplace("tailwind")
        assert len(results) == 1
        assert results[0]["id"] == "bradlc.vscode-tailwindcss"
        assert results[0]["publisher"] == "bradlc"
