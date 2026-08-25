"""Correlation ID: um `X-Request-ID` por requisição, reusado se o chamador já mandar um."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novaai_studio.config import get_settings
from novaai_studio.main import create_app


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def test_response_carries_a_request_id(client):
    response = client.get("/api/health", headers={"Authorization": "Bearer chave-de-teste"})
    assert response.status_code == 200
    assert response.headers.get("x-request-id")


def test_client_supplied_request_id_is_reused(client):
    response = client.get(
        "/api/health",
        headers={"Authorization": "Bearer chave-de-teste", "X-Request-ID": "meu-id-123"},
    )
    assert response.headers["x-request-id"] == "meu-id-123"


def test_two_requests_get_different_ids(client):
    r1 = client.get("/api/health", headers={"Authorization": "Bearer chave-de-teste"})
    r2 = client.get("/api/health", headers={"Authorization": "Bearer chave-de-teste"})
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
