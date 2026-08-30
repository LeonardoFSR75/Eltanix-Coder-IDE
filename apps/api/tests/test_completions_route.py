"""POST /api/context/completions — autocompletar inline / ghost text (ADR 0014).

Engine falso (mesmo padrão de `test_inline_edit.py`), sem Postgres/Redis reais.
Toda falha do recurso degrada para 204 — ghost text nunca mostra erro.
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


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)
    model_id: str = "ollama/qwen2.5-coder:1.5b"
    cache_hit: bool = False


class _FakeEngine:
    def __init__(self, resposta: str = "", *, raises: bool = False) -> None:
        self.resposta = resposta
        self.raises = raises
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source, session_id=None):
        self.chamadas.append(
            {"requested_model": requested_model, "params": params, "source": source}
        )
        if self.raises:
            raise RuntimeError("provedor fora")
        return _FakeCompletionResult(payload={"choices": [{"message": {"content": self.resposta}}]})


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    projects_root = tmp_path_factory.mktemp("projetos")
    demo = projects_root / "demo"
    (demo / "src").mkdir(parents=True)
    (demo / "src" / "app.py").write_bytes(b"def soma(a, b):\n    return a + b\n")
    return projects_root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["PROJECTS_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def _set_engine(client: TestClient, resposta: str = "", *, raises: bool = False) -> _FakeEngine:
    engine = _FakeEngine(resposta, raises=raises)
    client.app.state.engine = engine
    return engine


_BODY = {
    "project": "demo",
    "path": "src/app.py",
    "prefix": "def soma(a, b):\n    return ",
    "suffix": "\n\nprint(soma(1, 2))",
    "language": "python",
}


def test_happy_path_returns_completion(client):
    engine = _set_engine(client, "a + b")
    resp = client.post("/api/context/completions", json=_BODY, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["completion"] == "a + b"
    assert body["model"] == "ollama/qwen2.5-coder:1.5b"
    assert body["cached"] is False
    assert len(body["suggestion_id"]) == 32
    assert engine.chamadas[0]["source"] == "ide:completion"
    assert engine.chamadas[0]["requested_model"] == "completion"
    assert engine.chamadas[0]["params"]["max_tokens"] == 64


def test_strips_code_fence_from_model_answer(client):
    _set_engine(client, "```python\na + b\n```")
    resp = client.post("/api/context/completions", json=_BODY, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["completion"] == "a + b"


def test_empty_model_answer_degrades_to_204(client):
    _set_engine(client, "   \n  ")
    resp = client.post("/api/context/completions", json=_BODY, headers=AUTH)
    assert resp.status_code == 204
    assert resp.text == ""


def test_model_failure_degrades_to_204(client):
    _set_engine(client, raises=True)
    resp = client.post("/api/context/completions", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_blank_prefix_and_suffix_short_circuits_to_204(client):
    engine = _set_engine(client, "não deveria ser chamado")
    resp = client.post(
        "/api/context/completions",
        json={**_BODY, "prefix": "   ", "suffix": ""},
        headers=AUTH,
    )
    assert resp.status_code == 204
    assert engine.chamadas == []


def test_kill_switch_disables_the_endpoint(client, monkeypatch):
    _set_engine(client, "a + b")
    settings = get_settings()
    monkeypatch.setattr(settings, "ide_inline_completions_enabled", False)
    resp = client.post("/api/context/completions", json=_BODY, headers=AUTH)
    assert resp.status_code == 204


def test_requires_auth(client):
    resp = client.post("/api/context/completions", json=_BODY)
    assert resp.status_code == 401


def test_outcome_endpoint_accepts_best_effort(client):
    resp = client.post(
        "/api/context/completions/outcome",
        json={
            "suggestion_id": "abc123",
            "outcome": "accepted",
            "language": "python",
            "chars_suggested": 5,
            "chars_accepted": 5,
        },
        headers=AUTH,
    )
    # Persistência é best-effort (sem Postgres aqui) — a rota nunca falha o editor.
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}


def test_outcome_rejects_unknown_outcome_value(client):
    resp = client.post(
        "/api/context/completions/outcome",
        json={"suggestion_id": "abc", "outcome": "maybe"},
        headers=AUTH,
    )
    assert resp.status_code == 422
