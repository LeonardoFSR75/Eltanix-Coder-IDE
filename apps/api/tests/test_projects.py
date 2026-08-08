"""Testes unitários e de integração para a arquitetura de projetos."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sicoobito.agent.tools import RiskClass, ToolContext, registry
from sicoobito.workspace.projects import (
    list_projects,
    sync_projects_db,
    validate_name,
)


def test_validate_name():
    assert validate_name("meu-projeto") == "meu-projeto"
    with pytest.raises(ValueError):
        validate_name("../hack")
    with pytest.raises(ValueError):
        validate_name("projeto/sub")


def test_resolve_case_insensitive(tmp_path: Path):
    from sicoobito.workspace.projects import resolve
    (tmp_path / "Mestrado").mkdir()
    res = resolve(tmp_path, "mestrado")
    assert res.name == "Mestrado"


def test_list_projects(tmp_path: Path):
    (tmp_path / "proj1").mkdir()
    (tmp_path / "proj2").mkdir()
    (tmp_path / ".git").mkdir()

    projs = list_projects(tmp_path)
    slugs = {p.slug for p in projs}
    assert "proj1" in slugs
    assert "proj2" in slugs
    assert ".git" not in slugs


def test_manage_project_tool_registered():
    tool = registry.get("manage_project")
    assert tool is not None
    assert tool.risk is RiskClass.READ


@pytest.mark.asyncio
async def test_manage_project_tool_action_list(tmp_path: Path):
    (tmp_path / "demo").mkdir()

    ctx = MagicMock(spec=ToolContext)
    ctx.projects_root = tmp_path
    ctx.project = "demo"

    tool = registry.get("manage_project")
    assert tool is not None

    res = await tool.handler(ctx, {"action": "list"})
    assert res.ok
    assert "demo" in str(res.data)


@pytest.mark.asyncio
async def test_sync_projects_db_with_postgres(pg_session, tmp_path: Path):
    (tmp_path / "proj_db").mkdir()
    records = await sync_projects_db(pg_session, tmp_path)
    assert any(r.slug == "proj_db" for r in records)
