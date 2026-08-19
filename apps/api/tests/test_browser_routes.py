"""Testes das rotas do painel manual de navegador (`/api/browser/*`,
`api/routes/browser.py`) — item 17 do plano de robustez do navegador
interno. Antes desta mudança, as 7 rotas do router não tinham nenhuma
cobertura direta via HTTP (só a lógica por baixo, via testes de
`services/browser`, do `BrowserClient` isolado, ou do purge de clientes
ociosos em `test_browser_panel_clients.py`).

`TestClient(app)` sem `with` não roda o `lifespan` de `main.py` (confirmado
manualmente) — os campos de `app.state` que o lifespan normalmente povoa
(`browser_panel_clients`, `browser_config`, `tickets`, ...) têm que ser
montados à mão por teste, via a fixture `estado` abaixo.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ["SICOOBITO_API_KEY"] = "chave-de-teste"
os.environ.setdefault("REDIS_URL", "redis://localhost:65533/0")

import pytest
from fastapi.testclient import TestClient

from sicoobito.api.tickets import TicketStore
from sicoobito.browser.client import (
    BrowserClient,
    BrowserConfig,
    BrowserError,
    BrowserUnavailableError,
)
from sicoobito.main import app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@pytest.fixture
def estado():
    """Recria os campos de `app.state` que o lifespan normalmente povoa,
    isolados por teste — sem isto, `browser_panel_clients` acumularia
    sessões de um teste para o outro (a mesma classe de bug que o item 11
    corrigiu em produção, aqui como vazamento entre testes)."""
    app.state.browser_panel_clients = {}
    app.state.browser_panel_client_last_used = {}
    app.state.browser_config = BrowserConfig(base_url="http://browser-fake:5406", token="tok")
    app.state.tickets = TicketStore(None)
    app.state.redis = None
    app.state.blob = None
    yield app.state
    campos = (
        "browser_panel_clients",
        "browser_panel_client_last_used",
        "browser_config",
        "tickets",
    )
    for attr in campos:
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def client():
    return TestClient(app)


def _mock_browser_client() -> MagicMock:
    mock = MagicMock(spec=BrowserClient)
    mock.action = AsyncMock(
        return_value={"ok": True, "url": "http://web:5400", "title": "App", "status": 200}
    )
    mock.network_log = AsyncMock(return_value=[])
    mock.stop = AsyncMock(return_value=None)
    return mock


# ── POST /api/browser/action — validação ────────────────────────────────


def test_navigate_requires_http_url(client, estado):
    resp = client.post(
        "/api/browser/action",
        json={"session_id": "s1", "action": "navigate", "url": "javascript:alert(1)"},
        headers=AUTH,
    )
    assert resp.status_code == 400


def test_click_requires_selector_or_coordinates(client, estado):
    resp = client.post(
        "/api/browser/action", json={"session_id": "s1", "action": "click"}, headers=AUTH
    )
    assert resp.status_code == 400


def test_type_requires_selector_and_text(client, estado):
    resp = client.post(
        "/api/browser/action",
        json={"session_id": "s1", "action": "type", "selector": "#q"},
        headers=AUTH,
    )
    assert resp.status_code == 400


# ── POST /api/browser/action — caminho feliz e degradação ──────────────


def test_navigate_reaches_service_and_captures_screenshot_flag(client, estado):
    mock = _mock_browser_client()
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.post(
        "/api/browser/action",
        json={"session_id": "s1", "action": "navigate", "url": "http://web:5400"},
        headers=AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock.action.assert_awaited_once()
    payload_enviado = mock.action.call_args.args[0]
    assert payload_enviado["capture_screenshot"] is True
    assert payload_enviado["url"] == "http://web:5400"


def test_screenshot_action_does_not_force_capture_screenshot_flag(client, estado):
    mock = _mock_browser_client()
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.post(
        "/api/browser/action", json={"session_id": "s1", "action": "screenshot"}, headers=AUTH
    )

    assert resp.status_code == 200
    payload_enviado = mock.action.call_args.args[0]
    assert payload_enviado["capture_screenshot"] is False


def test_action_degrades_to_503_when_browser_service_not_configured(client, estado):
    estado.browser_config = None

    resp = client.post(
        "/api/browser/action",
        json={"session_id": "s1", "action": "content"},
        headers=AUTH,
    )

    assert resp.status_code == 503


def test_action_translates_browser_unavailable_error_to_503(client, estado):
    mock = _mock_browser_client()
    mock.action = AsyncMock(side_effect=BrowserUnavailableError("serviço fora do ar"))
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.post(
        "/api/browser/action", json={"session_id": "s1", "action": "content"}, headers=AUTH
    )

    assert resp.status_code == 503


def test_action_translates_browser_error_to_502(client, estado):
    mock = _mock_browser_client()
    mock.action = AsyncMock(side_effect=BrowserError("motor recusou a ação"))
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.post(
        "/api/browser/action", json={"session_id": "s1", "action": "content"}, headers=AUTH
    )

    assert resp.status_code == 502


# ── GET /api/browser/sessions/{id}/network ──────────────────────────────


def test_network_log_returns_requests_from_client(client, estado):
    mock = _mock_browser_client()
    mock.network_log = AsyncMock(return_value=[{"url": "http://web:5400/api", "method": "GET"}])
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.get("/api/browser/sessions/s1/network", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["requests"][0]["method"] == "GET"


def test_network_log_degrades_to_502_on_browser_error(client, estado):
    mock = _mock_browser_client()
    mock.network_log = AsyncMock(side_effect=BrowserError("falha ao ler log"))
    estado.browser_panel_clients["panel-s1"] = mock

    resp = client.get("/api/browser/sessions/s1/network", headers=AUTH)

    assert resp.status_code == 502


# ── POST /api/browser/sessions/{id}/stream-ticket ───────────────────────


def test_stream_ticket_issues_ticket_scoped_to_this_session(client, estado):
    resp = client.post("/api/browser/sessions/s1/stream-ticket", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in"] > 0
    assert isinstance(body["ticket"], str) and body["ticket"]


def test_stream_ticket_service_unavailable_returns_503(client, estado):
    estado.browser_config = None

    resp = client.post("/api/browser/sessions/s1/stream-ticket", headers=AUTH)

    assert resp.status_code == 503


# ── Isolamento entre sessões (item 17: sessão A não deve alcançar sessão B) ──


async def test_stream_ticket_cannot_be_consumed_for_a_different_session(estado):
    """O ticket é a única credencial do salto WS (o navegador não manda
    `Authorization`) — sem escopo por `session_id`, um ticket vazado/
    adivinhado abriria o screencast de QUALQUER sessão, não só a que o
    pediu."""
    from sicoobito.api.routes.browser import _escopo_stream

    ticket = await estado.tickets.issue(_escopo_stream("sess-a"))

    # A própria sessão que pediu: consome normalmente.
    ok_mesma_sessao = await estado.tickets.issue(_escopo_stream("sess-a"))
    assert await estado.tickets.consume(ok_mesma_sessao, _escopo_stream("sess-a")) is True

    # Uma sessão B tentando usar o ticket da sessão A: rejeitado, mesmo
    # sabendo o token — o escopo (`browser-stream:<session_id>`) não bate.
    assert await estado.tickets.consume(ticket, _escopo_stream("sess-b")) is False


def test_actions_on_different_sessions_use_independent_cached_clients(client, estado):
    """Duas sessões nunca compartilham a mesma instância de `BrowserClient`
    cacheada — fechar/reiniciar uma não pode arrastar a outra junto."""
    mock_a = _mock_browser_client()
    mock_b = _mock_browser_client()
    estado.browser_panel_clients["panel-sess-a"] = mock_a
    estado.browser_panel_clients["panel-sess-b"] = mock_b

    client.post(
        "/api/browser/action", json={"session_id": "sess-a", "action": "content"}, headers=AUTH
    )
    client.post(
        "/api/browser/action", json={"session_id": "sess-b", "action": "content"}, headers=AUTH
    )

    mock_a.action.assert_awaited_once()
    mock_b.action.assert_awaited_once()
    assert estado.browser_panel_clients["panel-sess-a"] is mock_a
    assert estado.browser_panel_clients["panel-sess-b"] is mock_b


def test_closing_one_session_does_not_touch_the_other(client, estado):
    mock_a = _mock_browser_client()
    mock_b = _mock_browser_client()
    estado.browser_panel_clients["panel-sess-a"] = mock_a
    estado.browser_panel_clients["panel-sess-b"] = mock_b

    resp = client.delete("/api/browser/sessions/sess-a", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["closed"] is True
    mock_a.stop.assert_awaited_once()
    assert "panel-sess-a" not in estado.browser_panel_clients
    assert estado.browser_panel_clients["panel-sess-b"] is mock_b
    mock_b.stop.assert_not_awaited()


# ── DELETE /api/browser/sessions/{id} ────────────────────────────────────


def test_close_session_never_touched_is_a_noop(client, estado):
    resp = client.delete("/api/browser/sessions/nunca-usada", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"closed": False}


def test_close_session_persists_replay_when_service_returns_bytes(client, estado, monkeypatch):
    mock = _mock_browser_client()
    mock.stop = AsyncMock(return_value={"trace_base64": "abc", "duration_ms": 500})
    estado.browser_panel_clients["panel-s1"] = mock

    store_replay = AsyncMock(return_value={"session_id": "s1"})
    monkeypatch.setattr("sicoobito.api.routes.browser.store_replay", store_replay)

    resp = client.delete("/api/browser/sessions/s1", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["closed"] is True
    assert body["replay"] is True
    assert "replay_lost" not in body
    store_replay.assert_awaited_once()


def test_close_session_signals_replay_lost_when_expired_by_ttl(client, estado, monkeypatch):
    mock = _mock_browser_client()
    mock.stop = AsyncMock(return_value={"expired_by_ttl": True})
    estado.browser_panel_clients["panel-s1"] = mock

    monkeypatch.setattr(
        "sicoobito.api.routes.browser.store_replay", AsyncMock(return_value=None)
    )
    mark_expired = AsyncMock()
    monkeypatch.setattr("sicoobito.api.routes.browser.mark_replay_expired", mark_expired)

    resp = client.delete("/api/browser/sessions/s1", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["replay"] is False
    assert body["replay_lost"] is True
    mark_expired.assert_awaited_once()


# ── GET /api/browser/replays e /api/browser/replays/{id} ────────────────


def test_list_replays_passes_through_recent_replays(client, estado, monkeypatch):
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.list_recent_replays",
        AsyncMock(return_value=[{"session_id": "s1"}]),
    )

    resp = client.get("/api/browser/replays", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"replays": [{"session_id": "s1"}]}


def test_get_replay_returns_404_when_never_existed(client, estado, monkeypatch):
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.get_replay", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.was_replay_expired", AsyncMock(return_value=False)
    )

    resp = client.get("/api/browser/replays/nunca-existiu", headers=AUTH)

    assert resp.status_code == 404


def test_get_replay_returns_410_when_lost_to_ttl_expiry(client, estado, monkeypatch):
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.get_replay", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.was_replay_expired", AsyncMock(return_value=True)
    )

    resp = client.get("/api/browser/replays/expirou", headers=AUTH)

    assert resp.status_code == 410


def test_get_replay_returns_entry_with_presigned_urls(client, estado, monkeypatch):
    monkeypatch.setattr(
        "sicoobito.api.routes.browser.get_replay",
        AsyncMock(
            return_value={
                "session_id": "s1",
                "video_key": "browser-sessions/s1/1/video.webm",
                "trace_key": "browser-sessions/s1/1/trace.zip",
            }
        ),
    )
    blob = MagicMock()
    blob.presigned_get_url = AsyncMock(side_effect=lambda key: f"https://minio.local/{key}")
    estado.blob = blob

    resp = client.get("/api/browser/replays/s1", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["video_url"] == "https://minio.local/browser-sessions/s1/1/video.webm"
    assert body["trace_url"] == "https://minio.local/browser-sessions/s1/1/trace.zip"


# ── Autenticação (ADR 0005 — nunca aberta por omissão) ──────────────────


def test_routes_require_authentication(client, estado):
    resp = client.get("/api/browser/replays")
    assert resp.status_code == 401
