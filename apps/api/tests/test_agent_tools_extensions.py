"""Ferramenta `manage_extensions` do agente: risco dinâmico e cada ação.

Mesmo espírito de `test_extensions_manager.py` — mocka `extensions/store.py` e o
`session_scope()` para não depender de Postgres real, testando só a lógica da
ferramenta e sua integração com `ExtensionsManager`."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from novaai_studio.agent.tools import RiskClass, Tool, ToolContext, registry
from novaai_studio.extensions.manager import ExtensionsManager
from novaai_studio.workspace.fs import WorkspaceFS


def _tool(name: str) -> Tool:
    ferramenta = registry.get(name)
    assert ferramenta is not None, f"ferramenta '{name}' não encontrada"
    return ferramenta


@pytest.fixture
def ctx(tmp_path: Path):
    return ToolContext(
        session_id="teste",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        extensions_manager=ExtensionsManager(),
    )


@asynccontextmanager
async def _fake_session_scope():
    yield object()


def test_manage_extensions_dynamic_risk():
    ferramenta = _tool("manage_extensions")
    for action in ("list", "search", "recommend"):
        assert ferramenta.resolve_risk({"action": action}) is RiskClass.READ
    for action in ("toggle", "update", "update_all", "sync"):
        assert ferramenta.resolve_risk({"action": action}) is RiskClass.WRITE


async def test_manage_extensions_without_manager_fails(tmp_path: Path):
    ctx_sem_manager = ToolContext(
        session_id="teste", workspace_root=tmp_path, fs=WorkspaceFS(tmp_path)
    )
    resultado = await _tool("manage_extensions").handler(ctx_sem_manager, {"action": "list"})
    assert resultado.ok is False


async def test_manage_extensions_list(ctx):
    resultado = await _tool("manage_extensions").handler(ctx, {"action": "list"})
    assert resultado.ok
    assert "Extensões" in resultado.content
    assert resultado.data["total_count"] > 0


async def test_manage_extensions_search_requires_query(ctx):
    resultado = await _tool("manage_extensions").handler(ctx, {"action": "search"})
    assert resultado.ok is False


async def test_manage_extensions_search(ctx):
    with patch.object(
        ctx.extensions_manager, "search_online", new=AsyncMock(return_value=[{"id": "a.b"}])
    ):
        resultado = await _tool("manage_extensions").handler(
            ctx, {"action": "search", "query": "tailwind"}
        )
    assert resultado.ok
    assert resultado.data["count"] == 1


async def test_manage_extensions_recommend_python_project(ctx):
    (ctx.workspace_root / "requirements.txt").write_text("flask\n", encoding="utf-8")
    resultado = await _tool("manage_extensions").handler(ctx, {"action": "recommend"})
    assert resultado.ok
    assert resultado.data["ecosystem"] == "python"
    ids = {i["id"] for i in resultado.data["recommended"]}
    assert "ms-python.python" in ids


async def test_manage_extensions_toggle_requires_extension_id(ctx):
    resultado = await _tool("manage_extensions").handler(ctx, {"action": "toggle"})
    assert resultado.ok is False


async def test_manage_extensions_toggle_unknown_id(ctx):
    with (
        patch("novaai_studio.agent.tools.extensions.session_scope", _fake_session_scope),
        patch("novaai_studio.extensions.manager.store.upsert_state", new=AsyncMock()),
    ):
        resultado = await _tool("manage_extensions").handler(
            ctx, {"action": "toggle", "extension_id": "nao.existe"}
        )
    assert resultado.ok is False


async def test_manage_extensions_toggle_known_id(ctx):
    ext_id = ctx.extensions_manager.get_catalog()["extensions"][0]["id"]
    with (
        patch("novaai_studio.agent.tools.extensions.session_scope", _fake_session_scope),
        patch("novaai_studio.extensions.manager.store.upsert_state", new=AsyncMock()),
    ):
        resultado = await _tool("manage_extensions").handler(
            ctx, {"action": "toggle", "extension_id": ext_id, "active": False}
        )
    assert resultado.ok
    assert resultado.data == {"id": ext_id, "active": False}


async def test_manage_extensions_sync(ctx):
    with (
        patch("novaai_studio.agent.tools.extensions.session_scope", _fake_session_scope),
        patch("novaai_studio.extensions.manager.store.upsert_state", new=AsyncMock()),
        patch("novaai_studio.extensions.manager.store.update_settings", new=AsyncMock()),
        patch.object(
            ctx.extensions_manager.client, "check_updates_batch", new=AsyncMock(return_value={})
        ),
    ):
        resultado = await _tool("manage_extensions").handler(ctx, {"action": "sync"})
    assert resultado.ok


async def test_manage_extensions_unknown_action(ctx):
    resultado = await _tool("manage_extensions").handler(ctx, {"action": "voar"})
    assert resultado.ok is False
