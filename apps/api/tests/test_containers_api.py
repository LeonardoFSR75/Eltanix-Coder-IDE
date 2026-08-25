"""Testes automatizados das rotas de Containers Docker (/api/containers/*)."""

import os
import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from eltanix.main import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer chave-de-teste"}


def test_containers_tree_endpoint_returns_tree():
    response = client.get("/api/containers/tree", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "containers_by_project" in data
    assert "images" in data
    assert "registries" in data
    assert "networks" in data
    assert "volumes" in data
    assert "contexts" in data
    assert "help_and_feedback" in data


def test_container_action_endpoint():
    response = client.post(
        "/api/containers/eltanix-executor-1/action",
        json={"action": "restart"},
        headers=AUTH,
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True


def test_container_logs_endpoint():
    response = client.get("/api/containers/eltanix-executor-1/logs", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert "container_id" in data
