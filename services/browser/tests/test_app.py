"""Testes do serviço browser: nunca abre um Chromium de verdade — `_get_page`
é substituído por uma página falsa (`unittest.mock.AsyncMock`) antes de cada
requisição que a alcançaria, no mesmo espírito dos testes do executor (que
nunca tocam o Docker de verdade).
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

TOKEN = "segredo-de-teste"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _reload_app(monkeypatch, *, token: str | None = TOKEN):
    if token is None:
        monkeypatch.delenv("BROWSER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("BROWSER_TOKEN", token)

    import app as app_module  # type: ignore[import-not-found]

    importlib.reload(app_module)
    return app_module


def _fake_page() -> MagicMock:
    page = MagicMock()
    page.is_closed.return_value = False
    page.url = "http://web:5400/ide"
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.title = AsyncMock(return_value="SicoobitoCode")
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfake")
    page.inner_text = AsyncMock(return_value="conteúdo da página")
    page.close = AsyncMock()
    page.mouse.click = AsyncMock()
    return page


def _install_fake_page(app_module, monkeypatch, engine_used: str = "chromium") -> MagicMock:
    page = _fake_page()
    fake_get_page = AsyncMock(return_value=(page, engine_used))
    monkeypatch.setattr(app_module, "_get_page", fake_get_page)
    return page


# ── auth ─────────────────────────────────────────────────────────────────


def test_require_token_rejects_request_without_authorization_header(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    client = TestClient(app_module.app)

    response = client.post("/sessions", json={"session_id": "s1"})

    assert response.status_code == 401


def test_require_token_rejects_wrong_token(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions", json={"session_id": "s1"}, headers={"Authorization": "Bearer errado"}
    )

    assert response.status_code == 401


def test_require_token_accepts_correct_token(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions", json={"session_id": "s1"}, headers=AUTH_HEADERS)

    assert response.status_code == 200


def test_no_token_configured_allows_any_request(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions", json={"session_id": "s1"})

    assert response.status_code == 200


# ── health ───────────────────────────────────────────────────────────────


def test_health_reports_session_count(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    data = TestClient(app_module.app).get("/health").json()
    assert data["status"] == "ok"
    assert data["sessions"] == 0


# ── ações ────────────────────────────────────────────────────────────────


def test_navigate_rejects_non_http_url(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "file:///etc/passwd"}
    )

    assert response.status_code == 400


def test_navigate_returns_url_title_and_status(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "http://web:5400/ide"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["title"] == "SicoobitoCode"
    assert data["status"] == 200
    page.goto.assert_awaited_once()


def test_click_requires_selector_or_coordinates(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions/s1/action", json={"action": "click"})

    assert response.status_code == 400


def test_click_by_selector(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action", json={"action": "click", "selector": "#botao"}
    )

    assert response.status_code == 200
    page.click.assert_awaited_once()


def test_click_by_coordinates(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions/s1/action", json={"action": "click", "x": 10, "y": 20})

    assert response.status_code == 200
    page.mouse.click.assert_awaited_once_with(10, 20)


def test_type_requires_selector_and_text(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions/s1/action", json={"action": "type", "selector": "#campo"})

    assert response.status_code == 400


def test_screenshot_returns_base64(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions/s1/action", json={"action": "screenshot"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["image_base64"]) > 0


def test_content_returns_page_text(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/sessions/s1/action", json={"action": "content"})

    assert response.status_code == 200
    assert response.json()["text"] == "conteúdo da página"


def test_action_that_raises_becomes_bad_gateway(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    page.goto.side_effect = RuntimeError("boom")
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "http://web:5400"}
    )

    assert response.status_code == 502


def test_close_session_closes_the_page(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)
    client.post("/sessions", json={"session_id": "s1"})
    app_module._pages["s1"] = page

    response = client.delete("/sessions/s1")

    assert response.status_code == 200
    assert response.json()["closed"] is True
    page.close.assert_awaited_once()


def test_close_session_that_does_not_exist(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    client = TestClient(app_module.app)

    response = client.delete("/sessions/inexistente")

    assert response.status_code == 200
    assert response.json()["closed"] is False


def test_navigate_localhost_falls_back_to_host_gateway(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)

    # Primeira chamada falha com connection refused; segunda (fallback) tem sucesso
    page.goto.side_effect = [
        RuntimeError("net::ERR_CONNECTION_REFUSED at http://localhost:5000"),
        MagicMock(status=200),
    ]

    client = TestClient(app_module.app)
    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "http://localhost:5000/app"}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert page.goto.await_count == 2


def test_navigate_returns_console_and_page_errors(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)

    async def fake_goto(*args, **kwargs):
        app_module._console_logs["s1"].append(
            "[ERROR] Uncaught TypeError: undefined is not a function"
        )
        app_module._page_errors["s1"].append("ReferenceError: App is not defined")
        return MagicMock(status=200)

    page.goto.side_effect = fake_goto

    client = TestClient(app_module.app)
    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "http://web:5400/app"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "console_errors" in data
    assert "page_errors" in data
    assert len(data["console_errors"]) == 1
    assert len(data["page_errors"]) == 1


def test_close_session_cleans_logs(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    app_module._console_logs["s1"] = ["[ERROR] test"]
    app_module._page_errors["s1"] = ["Error: test"]

    client = TestClient(app_module.app)
    response = client.delete("/sessions/s1")

    assert response.status_code == 200
    assert "s1" not in app_module._console_logs
    assert "s1" not in app_module._page_errors


# ── dual-engine (Lightpanda & Chromium) ──────────────────────────────────


def test_create_session_with_lightpanda_engine(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch, engine_used="lightpanda")
    client = TestClient(app_module.app)

    response = client.post("/sessions", json={"session_id": "lp-1", "engine": "lightpanda"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "lp-1"
    assert data["created"] is True
    assert data["engine_used"] == "lightpanda"


def test_action_reports_engine_used(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch, engine_used="lightpanda")
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/lp-1/action",
        json={"action": "content", "engine": "lightpanda"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["engine_used"] == "lightpanda"
    assert data["text"] == "conteúdo da página"


def test_health_reports_dual_engine_support(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    client = TestClient(app_module.app)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "engines_supported" in data
    assert "lightpanda" in data["engines_supported"]
    assert "chromium" in data["engines_supported"]


