"""Testes do serviço browser: nunca abre um Chromium de verdade — `_get_page`
é substituído por uma página falsa (`unittest.mock.AsyncMock`) antes de cada
requisição que a alcançaria, no mesmo espírito dos testes do executor (que
nunca tocam o Docker de verdade).
"""

from __future__ import annotations

import asyncio
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
    page.title = AsyncMock(return_value="Eltanix Coder IDE")
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


def test_health_check_lightpanda_offloaded_to_thread(monkeypatch):
    """Item 8 do plano de robustez: o healthcheck do Lightpanda não pode
    travar o event loop com uma chamada `urllib.request.urlopen` síncrona —
    `_check_lightpanda_sync` roda via `asyncio.to_thread`."""
    app_module = _reload_app(monkeypatch, token=None)
    monkeypatch.setattr(app_module, "_check_lightpanda_sync", lambda cdp_url: True)

    response = TestClient(app_module.app).get("/health")

    assert response.status_code == 200
    assert response.json()["lightpanda_available"] is True


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
    assert data["title"] == "Eltanix Coder IDE"
    assert data["status"] == 200
    assert data["url_is_internal_fallback"] is False
    assert data["original_url"] == "http://web:5400/ide"
    page.goto.assert_awaited_once()
    # Default `capture_screenshot=False` (item 7 do plano de robustez): o
    # agente navega repetidamente sem precisar de imagem a cada passo — só o
    # painel manual (`api/routes/browser.py`) pede `True` explicitamente.
    assert data["image_base64"] is None
    page.screenshot.assert_not_awaited()


def test_navigate_with_capture_screenshot_returns_image(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action",
        json={"action": "navigate", "url": "http://web:5400/ide", "capture_screenshot": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["image_base64"]
    page.screenshot.assert_awaited_once()


def test_navigate_panel_session_rejects_docker_internal_hostname(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/panel-abc/action", json={"action": "navigate", "url": "http://web:5400/ide"}
    )

    assert response.status_code == 400


def test_navigate_agent_session_allows_web_hostname(monkeypatch):
    # Sessão de agente (sem prefixo `panel-`) pode navegar direto para `web`
    # — a allowlist do lado do agente (`agent/tools/browser.py`) já restringe
    # o que chega até aqui; este teste garante que o serviço não duplica um
    # bloqueio incompatível com aquela allowlist.
    app_module = _reload_app(monkeypatch, token=None)
    _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/agent-session-1/action", json={"action": "navigate", "url": "http://web:5400/ide"}
    )

    assert response.status_code == 200


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
    fake_context = MagicMock()
    fake_context.tracing.stop = AsyncMock()
    fake_context.close = AsyncMock()
    app_module._contexts["s1"] = fake_context

    response = client.delete("/sessions/s1")

    assert response.status_code == 200
    assert response.json()["closed"] is True
    # `close_session` finaliza a sessão via `context.close()` (que também
    # fecha a página associada) — não chama `page.close()` diretamente, ver
    # `_finalize_replay`.
    fake_context.close.assert_awaited_once()


def test_close_session_that_does_not_exist(monkeypatch):
    app_module = _reload_app(monkeypatch, token=None)
    client = TestClient(app_module.app)

    response = client.delete("/sessions/inexistente")

    assert response.status_code == 200
    assert response.json()["closed"] is False
    assert "expired_by_ttl" not in response.json()


def test_close_session_signals_expired_by_ttl(monkeypatch):
    """Item 9 do plano: se o reaper TTL já descartou a sessão (com trace/
    vídeo em andamento) antes do DELETE explícito chegar, o chamador precisa
    de um jeito de saber que o replay foi perdido, não que nunca existiu."""
    app_module = _reload_app(monkeypatch, token=None)
    app_module._expired_sessions["s-ttl"] = app_module.time.time()
    client = TestClient(app_module.app)

    response = client.delete("/sessions/s-ttl")

    assert response.status_code == 200
    data = response.json()
    assert data["closed"] is False
    assert data["expired_by_ttl"] is True

    # Sinal de uso único — uma segunda consulta não deve repetir o marcador.
    response2 = client.delete("/sessions/s-ttl")
    assert response2.json().get("expired_by_ttl") is not True


def test_finalize_replay_drops_oversized_trace_blob(monkeypatch):
    """Item 9 do plano: um trace.zip gigante não pode virar uma resposta HTTP
    gigante em base64 — acima do teto, aquele blob é descartado, mas o resto
    do replay (actions/network) continua completo."""
    app_module = _reload_app(monkeypatch, token=None)
    monkeypatch.setattr(app_module, "MAX_REPLAY_BLOB_BYTES", 10)

    session_id = "s-big"
    trace_path = app_module.TRACE_ROOT / f"{session_id}.zip"
    trace_path.write_bytes(b"x" * 100)  # 100 bytes > teto de 10 bytes do teste

    fake_context = MagicMock()
    fake_context.tracing.stop = AsyncMock()
    fake_context.close = AsyncMock()
    app_module._contexts[session_id] = fake_context
    app_module._pages[session_id] = None
    app_module._session_started_at[session_id] = app_module.time.time()
    app_module._action_logs[session_id] = [{"action": "navigate"}]

    resultado = asyncio.run(app_module._finalize_replay(session_id))

    assert resultado is not None
    assert resultado["trace_dropped_size_limit"] is True
    assert resultado["trace_base64"] is None
    assert resultado["actions"] == [{"action": "navigate"}]
    assert not trace_path.exists()


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
    data = response.json()
    assert data["ok"] is True
    assert page.goto.await_count == 2
    # A URL que de fato carregou é uma substituição Docker-interna
    # (`eltanix-<sid>`), nunca alcançável do navegador real do host — o
    # chamador precisa saber disso para não usá-la como `src` de um iframe.
    assert data["url_is_internal_fallback"] is True
    assert data["original_url"] == "http://localhost:5000/app"


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
    app_module._contexts["s1"] = MagicMock()
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


def test_navigate_does_not_capture_screenshot_by_default(monkeypatch):
    """Item 7 do plano de robustez: o agente (payload sem `capture_screenshot`)
    não paga o custo de uma rasterização completa a cada `navigate`."""
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action", json={"action": "navigate", "url": "http://web:5400/ide"}
    )

    assert response.status_code == 200
    assert response.json()["image_base64"] is None
    page.screenshot.assert_not_awaited()


def test_navigate_captures_screenshot_when_requested(monkeypatch):
    """O painel manual (`api/routes/browser.py`) passa `capture_screenshot=True`
    explicitamente — continua recebendo a imagem embutida em `navigate`."""
    app_module = _reload_app(monkeypatch, token=None)
    page = _install_fake_page(app_module, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/sessions/s1/action",
        json={"action": "navigate", "url": "http://web:5400/ide", "capture_screenshot": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["image_base64"]
    page.screenshot.assert_awaited_once()


def test_get_page_conflicts_when_screenshot_requested_on_lightpanda_session(monkeypatch):
    """Item 7 do plano: pedir `screenshot` (que força engine='chromium') numa
    sessão já presa em Lightpanda deve falhar de forma explícita (409), não
    silenciar e deixar `page.screenshot()` estourar um erro genérico depois."""
    app_module = _reload_app(monkeypatch, token=None)
    page = _fake_page()
    app_module._pages["lp-1"] = page
    app_module._session_engine["lp-1"] = "lightpanda"
    client = TestClient(app_module.app)

    response = client.post("/sessions/lp-1/action", json={"action": "screenshot"})

    assert response.status_code == 409
    assert "lightpanda" in response.json()["detail"]
    page.screenshot.assert_not_awaited()


# ── concorrência (item 6 do plano de robustez do navegador interno) ────────


def test_get_page_concurrent_calls_create_only_one_context(monkeypatch):
    """Duas chamadas concorrentes para uma sessão NOVA não podem criar dois
    contextos Chromium — só a vencedora da corrida deve sobreviver, e a
    outra deve reaproveitar o mesmo contexto/página em vez de vazar um novo."""
    app_module = _reload_app(monkeypatch, token=None)

    fake_page = _fake_page()
    fake_context = MagicMock()
    fake_context.new_page = AsyncMock(return_value=fake_page)
    fake_context.tracing.start = AsyncMock()

    fake_browser = MagicMock()
    fake_browser.new_context = AsyncMock(return_value=fake_context)

    async def fake_launch_browser(engine="auto"):
        # Simula latência real de lançar/conectar o browser, dando tempo
        # para a segunda chamada concorrente tentar entrar na mesma seção
        # crítica antes da primeira terminar.
        await asyncio.sleep(0.05)
        return fake_browser, "chromium"

    monkeypatch.setattr(app_module, "_launch_browser", fake_launch_browser)

    async def get_page_locked(session_id: str):
        lock = await app_module._lock_for_session(session_id)
        async with lock:
            return await app_module._get_page(session_id, engine="auto")

    async def cenario():
        return await asyncio.gather(
            get_page_locked("concorrente-1"),
            get_page_locked("concorrente-1"),
        )

    resultados = asyncio.run(cenario())

    assert fake_browser.new_context.await_count == 1
    assert resultados[0][0] is resultados[1][0]


def test_get_page_prunes_stale_pending_requests(monkeypatch):
    """Item 8 do plano: requisições que nunca disparam `response`/
    `requestfailed` (SSE/long-poll penduradas) não podem crescer o dict de
    pendentes de uma sessão para sempre."""
    app_module = _reload_app(monkeypatch, token=None)

    fake_page = _fake_page()
    fake_context = MagicMock()
    fake_context.new_page = AsyncMock(return_value=fake_page)
    fake_context.tracing.start = AsyncMock()

    fake_browser = MagicMock()
    fake_browser.new_context = AsyncMock(return_value=fake_context)

    async def fake_launch_browser(engine="auto"):
        return fake_browser, "chromium"

    monkeypatch.setattr(app_module, "_launch_browser", fake_launch_browser)

    async def cenario():
        lock = await app_module._lock_for_session("s-pend")
        async with lock:
            await app_module._get_page("s-pend", engine="auto")

    asyncio.run(cenario())

    on_request_cb = None
    for chamada in fake_page.on.call_args_list:
        if chamada.args[0] == "request":
            on_request_cb = chamada.args[1]
            break
    assert on_request_cb is not None

    for _ in range(250):
        on_request_cb(object())

    assert len(app_module._pending_requests["s-pend"]) <= 200


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


def test_validate_url_battery_agrees_with_shared_ssrf_module(monkeypatch):
    """Bateria de hosts bloqueados/permitidos — mantida em sincronia manual
    com `eltanix.security.url_safety.BLOCKED_HOSTNAMES` (item 1 do plano de
    robustez do navegador interno, item 18c para esta bateria em si). Este
    serviço não importa aquele módulo de propósito — roda num container
    isolado e deliberadamente mínimo (ver o comentário acima de
    `BLOCKED_HOSTS` em `app.py` e o addendum do ADR 0007) — então não dá pra
    escrever um teste que literalmente chame os dois módulos lado a lado (são
    dois ambientes Python sem relação um com o outro). Esta bateria é o
    substituto possível: se um hostname for adicionado/removido só de um
    lado, quem tocar o outro lado precisa atualizar esta lista também — o
    diff fica visível em revisão de código, em vez de as duas cópias
    divergirem em silêncio.
    """
    app_module = _reload_app(monkeypatch, token=None)

    # Infra que nenhuma sessão alcança, painel ou agente.
    sempre_bloqueados = [
        "169.254.169.254",
        "metadata.google.internal",
        "executor",
        "redis",
        "minio",
        "postgres",
        "mcp-scanner",
    ]
    for hostname in sempre_bloqueados:
        for sessao in ("panel-x", "agent-x"):
            with pytest.raises(app_module.HTTPException) as exc_info:
                app_module.validate_url(f"http://{hostname}/x", session_id=sessao)
            assert exc_info.value.status_code == 400

    # Só o painel manual bloqueia — o agente pode testar a própria aplicação
    # (allowlist espelhada em `eltanix.agent.tools.browser::
    # is_agent_local_test_target`).
    bloqueados_so_para_painel = ["web", "api", "host.docker.internal", "eltanix-outra-sessao"]
    for hostname in bloqueados_so_para_painel:
        with pytest.raises(app_module.HTTPException):
            app_module.validate_url(f"http://{hostname}/x", session_id="panel-x")
        app_module.validate_url(f"http://{hostname}/x", session_id="agent-x")  # não levanta

    # Gatilho de fallback (`eltanix-<sid>`/`host.docker.internal`) e
    # domínios externos comuns — nunca bloqueados por este validador (o
    # isolamento de rede de `browser_net`, não este código, é quem impede a
    # internet pública).
    sempre_permitidos = ["localhost", "127.0.0.1", "0.0.0.0", "exemplo.com"]
    for hostname in sempre_permitidos:
        for sessao in ("panel-x", "agent-x"):
            app_module.validate_url(f"http://{hostname}/x", session_id=sessao)


