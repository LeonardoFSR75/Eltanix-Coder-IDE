"""GET /api/quality/coverage e /dependency-markers (Onda 1.5 — gutter intelligence).

Sem Postgres/Redis reais; o scan de dependências é injetado por monkeypatch.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from eltanix.config import get_settings
from eltanix.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}

COBERTURA = """<?xml version="1.0" ?>
<coverage line-rate="0.66">
  <packages><package name="p"><classes>
    <class filename="src/app.py" name="app.py">
      <lines>
        <line number="1" hits="2"/>
        <line number="2" hits="0"/>
      </lines>
    </class>
  </classes></package></packages>
</coverage>
"""


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("projetos")

    demo = root / "demo"
    (demo / "src").mkdir(parents=True)
    (demo / "src" / "app.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    (demo / "coverage.xml").write_text(COBERTURA, encoding="utf-8")
    (demo / "requirements.txt").write_text("flask==2.0\njinja2==3.1.2\n", encoding="utf-8")

    bare = root / "bare"
    (bare / "src").mkdir(parents=True)
    (bare / "src" / "lone.py").write_text("x = 1\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["PROJECTS_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def test_coverage_happy_path(client):
    resp = client.get(
        "/api/quality/coverage", params={"project": "demo", "path": "src/app.py"}, headers=AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "cobertura"
    assert body["file"]["covered"] == [1]
    assert body["file"]["uncovered"] == [2]


def test_coverage_204_when_no_report(client):
    resp = client.get(
        "/api/quality/coverage", params={"project": "bare", "path": "src/lone.py"}, headers=AUTH
    )
    assert resp.status_code == 204
    assert resp.text == ""


def test_coverage_204_when_file_absent_from_report(client):
    resp = client.get(
        "/api/quality/coverage",
        params={"project": "demo", "path": "src/app.py.orig"},
        headers=AUTH,
    )
    assert resp.status_code == 204


def test_coverage_requires_auth(client):
    resp = client.get(
        "/api/quality/coverage", params={"project": "demo", "path": "src/app.py"}
    )
    assert resp.status_code == 401


def test_dependency_markers_non_manifest_is_unsupported(client):
    resp = client.get(
        "/api/quality/dependency-markers",
        params={"project": "demo", "path": "src/app.py"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"markers": [], "supported": False}


def test_dependency_markers_maps_audit_to_lines(client, monkeypatch):
    async def _fake_audit(eco: str, project_path, py_exe) -> dict[str, Any]:
        return {
            "supported": True,
            "tool": "pip-audit",
            "tool_available": True,
            "vulnerabilities": [
                {
                    "package": "jinja2",
                    "id": "GHSA-x",
                    "fix_versions": ["3.1.4"],
                    "description": "xss",
                }
            ],
        }

    monkeypatch.setattr("eltanix.api.routes.quality.run_dependency_audit", _fake_audit)
    resp = client.get(
        "/api/quality/dependency-markers",
        params={"project": "demo", "path": "requirements.txt"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_available"] is True
    assert len(body["markers"]) == 1
    assert body["markers"][0]["line"] == 2
    assert body["markers"][0]["package"] == "jinja2"


def test_dependency_markers_audit_failure_degrades(client, monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("pip-audit ausente")

    monkeypatch.setattr("eltanix.api.routes.quality.run_dependency_audit", _boom)
    resp = client.get(
        "/api/quality/dependency-markers",
        params={"project": "demo", "path": "requirements.txt"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json() == {"markers": [], "supported": True, "tool_available": False}
