"""`GET /api/health/ready` — prontidão de infraestrutura (Postgres obrigatório,
Redis opcional) — e o handler de exceção não-tratada (`api/errors.py`), que
precisa devolver JSON com `request_id` e o header `X-Request-ID` mesmo quando o
`CorrelationIdMiddleware` não chega a setá-lo sozinho.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"

from eltanix.api.routes import health as health_route
from eltanix.config import get_settings
from eltanix.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@pytest.fixture
def app():
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _FakeSession:
    def __init__(self, *, boom: bool) -> None:
        self._boom = boom

    async def execute(self, *_a, **_k):
        if self._boom:
            raise RuntimeError("connection refused")
        return None


def _fake_scope(*, boom: bool):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield _FakeSession(boom=boom)

    return _cm


class _FakeRedis:
    def __init__(self, *, boom: bool) -> None:
        self._boom = boom

    async def ping(self) -> bool:
        if self._boom:
            raise RuntimeError("redis down")
        return True


def test_ready_returns_200_when_postgres_answers(client, monkeypatch):
    monkeypatch.setattr(health_route, "session_scope", _fake_scope(boom=False))
    client.app.state.redis = _FakeRedis(boom=False)

    r = client.get("/api/health/ready", headers=AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["redis"] == "ok"


def test_ready_reports_redis_disabled_but_still_ready(client, monkeypatch):
    monkeypatch.setattr(health_route, "session_scope", _fake_scope(boom=False))
    client.app.state.redis = None

    r = client.get("/api/health/ready", headers=AUTH)

    assert r.status_code == 200
    assert r.json()["checks"]["redis"] == "disabled"


def test_ready_stays_ready_when_only_redis_is_down(client, monkeypatch):
    monkeypatch.setattr(health_route, "session_scope", _fake_scope(boom=False))
    client.app.state.redis = _FakeRedis(boom=True)

    r = client.get("/api/health/ready", headers=AUTH)

    assert r.status_code == 200
    assert r.json()["checks"]["redis"] == "error"


def test_ready_returns_503_when_postgres_is_unreachable(client, monkeypatch):
    monkeypatch.setattr(health_route, "session_scope", _fake_scope(boom=True))

    r = client.get("/api/health/ready", headers=AUTH)

    assert r.status_code == 503
    assert r.json()["detail"]["checks"]["postgres"] == "error"


def test_ready_requires_authentication(client, monkeypatch):
    monkeypatch.setattr(health_route, "session_scope", _fake_scope(boom=False))
    assert client.get("/api/health/ready").status_code == 401


def test_unhandled_exception_returns_json_with_request_id(app):
    @app.get("/api/_boom_for_test")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/_boom_for_test", headers={"X-Request-ID": "id-abc-123"})

    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Erro interno no servidor."
    assert body["request_id"] == "id-abc-123"
    assert r.headers.get("x-request-id") == "id-abc-123"
