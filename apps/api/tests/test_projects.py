"""Testes unitários e de integração para a arquitetura de projetos."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eltanix.agent.tools import RiskClass, ToolContext, registry
from eltanix.workspace.projects import (
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
    from eltanix.workspace.projects import resolve
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


@pytest.mark.asyncio
async def test_audit_service_record_accepts_event_metadata_alias(pg_session):
    from eltanix.audit.service import AuditService
    service = AuditService()
    entry = await service.record(
        actor="test",
        module="test",
        action="test_action",
        event_metadata={"key": "val"},
    )
    assert entry.event_metadata == {"key": "val"}


@pytest.mark.asyncio
async def test_create_project_endpoint(tmp_path: Path):
    from httpx import ASGITransport, AsyncClient
    from eltanix.api.deps import require_session
    from eltanix.main import create_app

    app = create_app()
    app.state.projects_root = tmp_path
    app.dependency_overrides[require_session] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/projects",
            json={"name": "Sorteador", "description": "Criar um sorteador para utilizar em aulas"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["name"] == "Sorteador"
        assert data["slug"] == "Sorteador"
        assert (tmp_path / "Sorteador").is_dir()


@pytest.mark.asyncio
async def test_inspect_and_browse_filesystem_endpoints(tmp_path: Path):
    from httpx import ASGITransport, AsyncClient
    from eltanix.api.deps import require_session
    from eltanix.main import create_app

    app = create_app()
    app.state.projects_root = tmp_path
    app.dependency_overrides[require_session] = lambda: None

    # Cria pasta de exemplo com package.json
    demo_dir = tmp_path / "meu-app-react"
    demo_dir.mkdir()
    (demo_dir / "package.json").write_text('{"dependencies": {"react": "^18.0.0", "next": "^14.0.0"}}', encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Teste de inspeção
        res_inspect = await ac.post("/api/projects/inspect-path", json={"path": str(demo_dir)})
        assert res_inspect.status_code == 200, res_inspect.text
        data_inspect = res_inspect.json()
        assert data_inspect["name"] == "meu-app-react"
        assert "React" in data_inspect["frameworks"]
        assert "Next.js" in data_inspect["frameworks"]

        # 2. Teste de navegação do sistema de arquivos
        res_browse = await ac.post("/api/projects/filesystem/browse", json={"path": str(tmp_path)})
        assert res_browse.status_code == 200, res_browse.text
        data_browse = res_browse.json()
        assert data_browse["current_path"] == str(tmp_path.resolve())
        assert any(d["name"] == "meu-app-react" for d in data_browse["directories"])

        # 3. Teste de listagem de raízes quando path é vazio
        res_roots = await ac.post("/api/projects/filesystem/browse", json={"path": None})
        assert res_roots.status_code == 200, res_roots.text
        data_roots = res_roots.json()
        assert len(data_roots["roots"]) > 0


