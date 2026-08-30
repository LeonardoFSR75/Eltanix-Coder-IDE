"""POST /api/context/next-edit — predição do próximo edit / "tab to jump" (ADR 0015).

Engine falso (mesmo padrão de `test_completions_route.py`), sem Postgres/Redis.
`found: false` e toda falha degradam para 204.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from eltanix.config import get_settings
from eltanix.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}

FILE = "def soma(a, b):\n    return a + b\n\n\nprint(soma(1, 2))\n"


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)
    model_id: str = "groq/llama-3.3-70b-versatile"
    cache_hit: bool = False


class _FakeEngine:
    def __init__(self, content: str = "", *, raises: bool = False) -> None:
        self.content = content
        self.raises = raises
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source, session_id=None):
        self.chamadas.append(
            {"requested_model": requested_model, "params": params, "source": source}
        )
        if self.raises:
            raise RuntimeError("provedor fora")
        return _FakeCompletionResult(payload={"choices": [{"message": {"content": self.content}}]})


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    projects_root = tmp_path_factory.mktemp("projetos")
    (projects_root / "demo" / "src").mkdir(parents=True)
    return projects_root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["PROJECTS_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def _set_engine(client: TestClient, content: str = "", *, raises: bool = False) -> _FakeEngine:
    engine = _FakeEngine(content, raises=raises)
    client.app.state.engine = engine
    return engine


_BODY = {
    "project": "demo",
    "path": "src/app.py",
    "file_content": FILE,
    "cursor_line": 2,
    "recent_edits": [{"path": "src/app.py", "diff": "- return a + b\n+ return a - b"}],
    "language": "python",
}


def test_happy_path_returns_validated_edit(client):
    engine = _set_engine(
        client,
        '{"found": true, "start_line": 5, "end_line": 5, "replacement": "print(soma(3, 4))"}',
    )
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["edit"]["start_line"] == 5
    assert body["edit"]["old_text"] == "print(soma(1, 2))\n"
    assert "soma(3, 4)" in body["edit"]["new_text"]
    assert body["edit"]["jump_lines"] == 3
    assert body["edit"]["diff"]
    assert len(body["suggestion_id"]) == 32
    assert engine.chamadas[0]["source"] == "ide:next_edit"
    assert engine.chamadas[0]["requested_model"] == "next-edit"


def test_model_says_not_found_degrades_to_204(client):
    _set_engine(client, '{"found": false}')
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_out_of_bounds_prediction_degrades_to_204(client):
    _set_engine(client, '{"found": true, "start_line": 99, "end_line": 120, "replacement": "x"}')
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_noop_prediction_degrades_to_204(client):
    _set_engine(
        client,
        '{"found": true, "start_line": 2, "end_line": 2, "replacement": "    return a + b"}',
    )
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_model_failure_degrades_to_204(client):
    _set_engine(client, raises=True)
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_kill_switch_disables_the_endpoint(client, monkeypatch):
    _set_engine(client, '{"found": true, "start_line": 5, "end_line": 5, "replacement": "y"}')
    monkeypatch.setattr(get_settings(), "ide_next_edit_enabled", False)
    resp = client.post("/api/context/next-edit", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_requires_auth(client):
    resp = client.post("/api/context/next-edit", json=_BODY)
    assert resp.status_code == 401


def test_outcome_endpoint_accepts_next_edit_kind(client):
    resp = client.post(
        "/api/context/completions/outcome",
        json={
            "suggestion_id": "ne-1",
            "outcome": "accepted",
            "kind": "next_edit",
            "language": "python",
            "jump_lines": 12,
            "chars_suggested": 40,
            "chars_accepted": 40,
        },
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}
