"""Testes unitários para o gerenciador de extensões e cliente Open VSX.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import Response

from sicoobito.extensions.catalog import MASTER_EXTENSIONS_CATALOG
from sicoobito.extensions.client import OpenVSXClient, _is_newer_version
from sicoobito.extensions.manager import ExtensionsManager


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


def test_extensions_manager_catalog_and_toggle(tmp_path: Path):
    state_file = tmp_path / "extensions_state.json"
    mgr = ExtensionsManager(state_file=state_file)

    catalog = mgr.get_catalog()
    assert catalog["total_count"] == len(MASTER_EXTENSIONS_CATALOG)
    assert catalog["auto_update_enabled"] is True

    ext_id = "sicoobito.shadcn-radix-studio"
    assert mgr.toggle_extension(ext_id, active=False) is False
    updated_catalog = mgr.get_catalog()
    target_ext = next(e for e in updated_catalog["extensions"] if e["id"] == ext_id)
    assert target_ext["active"] is False

    assert mgr.toggle_extension(ext_id, active=True) is True
    target_ext = next(e for e in mgr.get_catalog()["extensions"] if e["id"] == ext_id)
    assert target_ext["active"] is True


@pytest.mark.asyncio
async def test_extensions_manager_sync_and_update(tmp_path: Path):
    state_file = tmp_path / "extensions_state.json"
    mock_client = AsyncMock(spec=OpenVSXClient)
    mock_client.check_updates_batch.return_value = {
        "sicoobito.shadcn-radix-studio": {
            "current_version": "1.4.0",
            "latest_version": "1.5.0",
            "published_at": "2026-08-17T00:00:00Z",
            "downloads": "1.5M",
        }
    }

    mgr = ExtensionsManager(state_file=state_file, client=mock_client)
    mgr._auto_update_enabled = False  # Para inspecionar o pending update antes de aplicar

    catalog = await mgr.sync_with_marketplace(force=True)
    assert catalog["pending_updates_count"] == 1

    target_ext = next(e for e in catalog["extensions"] if e["id"] == "sicoobito.shadcn-radix-studio")
    assert target_ext["hasUpdate"] is True
    assert target_ext["updateInfo"]["latest_version"] == "1.5.0"

    # Atualiza todas
    updated_count = mgr.update_all_extensions()
    assert updated_count == 1

    catalog_after = mgr.get_catalog()
    assert catalog_after["pending_updates_count"] == 0
    target_ext_after = next(e for e in catalog_after["extensions"] if e["id"] == "sicoobito.shadcn-radix-studio")
    assert target_ext_after["version"] == "1.5.0"
    assert target_ext_after["hasUpdate"] is False


@pytest.mark.asyncio
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
