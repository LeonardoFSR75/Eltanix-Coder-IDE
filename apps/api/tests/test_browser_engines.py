"""Testes da integração de múltiplos motores de navegador (Lightpanda + Chromium) na API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from eltanix.agent.tools.base import ToolContext
from eltanix.agent.tools.browser import browser_action
from eltanix.browser.client import BrowserClient, BrowserConfig


@pytest.fixture
def mock_browser_client():
    client = MagicMock(spec=BrowserClient)
    client.action = AsyncMock(
        return_value={
            "ok": True,
            "url": "http://localhost:5000",
            "title": "Eltanix Coder IDE App",
            "status": 200,
            "engine_used": "lightpanda",
            "duration_ms": 25,
            "console_errors": [],
            "page_errors": [],
        }
    )
    return client


@pytest.mark.asyncio
async def test_browser_action_passes_engine_to_client(mock_browser_client):
    ctx = ToolContext(
        session_id="test-session",
        workspace_root="/tmp/test",
        fs=MagicMock(),
        browser=mock_browser_client,
    )

    result = await browser_action.handler(
        ctx,
        {
            "action": "navigate",
            "url": "http://localhost:5000",
            "engine": "lightpanda",
        },
    )

    assert result.ok is True
    assert "motor: lightpanda" in result.content
    mock_browser_client.action.assert_awaited_once_with(
        {
            "action": "navigate",
            "url": "http://localhost:5000",
            "selector": None,
            "x": None,
            "y": None,
            "text": None,
            "engine": "lightpanda",
        }
    )


@pytest.mark.asyncio
async def test_browser_action_auto_engine_defaults_gracefully(mock_browser_client):
    ctx = ToolContext(
        session_id="test-session",
        workspace_root="/tmp/test",
        fs=MagicMock(),
        browser=mock_browser_client,
    )

    result = await browser_action.handler(
        ctx,
        {
            "action": "content",
        },
    )

    assert result.ok is True
    mock_browser_client.action.assert_awaited_once_with(
        {
            "action": "content",
            "url": None,
            "selector": None,
            "x": None,
            "y": None,
            "text": None,
            "engine": "auto",
        }
    )


@pytest.mark.asyncio
async def test_browser_action_blocks_external_url(mock_browser_client):
    ctx = ToolContext(
        session_id="test-session",
        workspace_root="/tmp/test",
        fs=MagicMock(),
        browser=mock_browser_client,
    )

    result = await browser_action.handler(
        ctx,
        {
            "action": "navigate",
            "url": "https://example.com/malicious",
        },
    )

    # `ok=False` de propósito: URL externa deve contar como falha de
    # tool-call para o guard de repetição em `agent/graph.py`, não escapar
    # dele via um resultado "bem-sucedido" que só avisa o modelo.
    assert result.ok is False
    assert result.data["blocked"] is True
    mock_browser_client.action.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_client_start_includes_engine():
    mock_http = MagicMock()
    mock_http.post = AsyncMock(
        return_value=MagicMock(status_code=200, json=lambda: {"session_id": "s1", "created": True})
    )
    config = BrowserConfig(base_url="http://browser:5406", token="test-token")
    client = BrowserClient(session_id="s1", config=config, client=mock_http)

    await client.start(engine="lightpanda")

    mock_http.post.assert_awaited_once_with(
        "http://browser:5406/sessions",
        json={"session_id": "s1", "engine": "lightpanda"},
        headers={"Authorization": "Bearer test-token"},
        timeout=10.0,
    )
