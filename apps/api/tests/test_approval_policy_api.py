"""Rota da política de auto-aprovação — GET/PUT /api/agent/approval-policy.

`.eltanix/approval_policy.yaml` já tinha editor de round-trip
(`agent/approval_policy_editor.py`) sem rota nenhuma — este é o teste da
ligação (agent/approval_policy_config.py::load_approval_policy já tem
cobertura própria em test_approval_policy_config.py).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from eltanix.config import get_settings
from eltanix.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    projects_root = tmp_path_factory.mktemp("projetos")
    (projects_root / "demo").mkdir()
    return projects_root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["PROJECTS_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def test_get_without_file_returns_empty_policy(client):
    resposta = client.get("/api/agent/approval-policy?project=demo", headers=AUTH)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["version"] == 1
    assert corpo["second_opinion"] is False
    assert corpo["rules"] == []


def test_put_then_get_roundtrips_rules(client):
    payload = {
        "project": "demo",
        "second_opinion": True,
        "rules": [
            {"kind": "edit_path_glob", "path_glob": "*.md", "max_changed_lines": 10},
            {"kind": "exec_command_prefix", "allowed_prefixes": ["npm test"]},
        ],
    }
    resposta = client.put("/api/agent/approval-policy", json=payload, headers=AUTH)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["second_opinion"] is True
    assert len(corpo["rules"]) == 2
    assert corpo["rules"][0]["path_glob"] == "*.md"
    assert corpo["rules"][1]["allowed_prefixes"] == ["npm test"]

    relido = client.get("/api/agent/approval-policy?project=demo", headers=AUTH).json()
    assert relido == corpo


def test_put_replaces_rules_entirely(client):
    client.put(
        "/api/agent/approval-policy",
        json={
            "project": "demo",
            "second_opinion": False,
            "rules": [{"kind": "exec_command_prefix", "allowed_prefixes": ["pytest"]}],
        },
        headers=AUTH,
    )
    corpo = client.get("/api/agent/approval-policy?project=demo", headers=AUTH).json()
    assert len(corpo["rules"]) == 1
    assert corpo["rules"][0]["kind"] == "exec_command_prefix"


def test_requires_auth(client):
    resposta = client.get("/api/agent/approval-policy?project=demo")
    assert resposta.status_code == 401
