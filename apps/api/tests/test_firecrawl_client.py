"""Testes unitários do cliente HTTP do Firecrawl."""

from __future__ import annotations

import httpx
import pytest

from novaai_studio.firecrawl.client import (
    FirecrawlAuthError,
    FirecrawlClient,
    FirecrawlConfig,
    FirecrawlRateLimitError,
)


@pytest.mark.asyncio
async def test_scrape_success():
    fake_data = {
        "success": True,
        "data": {
            "markdown": "# Título\n\nConteúdo da página",
            "metadata": {"title": "Título", "sourceURL": "https://example.com"},
            "links": ["https://example.com/sub"],
        },
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/scrape"
        assert request.headers.get("authorization") == "Bearer test-key"
        return httpx.Response(200, json=fake_data)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(
        FirecrawlConfig(api_key="test-key", api_url="https://api.firecrawl.dev"),
        http_client=http_client,
    )

    data = await client.scrape("https://example.com")
    assert data["markdown"] == "# Título\n\nConteúdo da página"
    assert data["metadata"]["title"] == "Título"


@pytest.mark.asyncio
async def test_scrape_auth_error():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized: invalid api key")

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(
        FirecrawlConfig(api_key="bad-key"),
        http_client=http_client,
    )

    with pytest.raises(FirecrawlAuthError):
        await client.scrape("https://example.com")


@pytest.mark.asyncio
async def test_scrape_rate_limit_error():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(
        FirecrawlConfig(api_key="key"),
        http_client=http_client,
    )

    with pytest.raises(FirecrawlRateLimitError):
        await client.scrape("https://example.com")


@pytest.mark.asyncio
async def test_search_success():
    fake_results = {
        "success": True,
        "data": [
            {
                "title": "FastAPI Docs",
                "url": "https://fastapi.tiangolo.com",
                "description": "FastAPI framework",
                "markdown": "# FastAPI\n\nModern web framework",
            }
        ],
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/search"
        return httpx.Response(200, json=fake_results)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(
        FirecrawlConfig(api_key="test-key"),
        http_client=http_client,
    )

    results = await client.search("fastapi tutorial", limit=1)
    assert len(results) == 1
    assert results[0]["title"] == "FastAPI Docs"


@pytest.mark.asyncio
async def test_map_urls_success():
    fake_map = {
        "success": True,
        "links": ["https://example.com/a", "https://example.com/b"],
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/map"
        return httpx.Response(200, json=fake_map)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(http_client=http_client)

    links = await client.map_urls("https://example.com")
    assert links == ["https://example.com/a", "https://example.com/b"]


@pytest.mark.asyncio
async def test_crawl_and_poll_status():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/crawl":
            return httpx.Response(200, json={"success": True, "id": "crawl-123", "url": "https://api.firecrawl.dev/v1/crawl/crawl-123"})
        if request.method == "GET" and request.url.path == "/v1/crawl/crawl-123":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "total": 1,
                    "completed": 1,
                    "data": [
                        {
                            "markdown": "# Pagina 1",
                            "metadata": {"title": "Pagina 1", "sourceURL": "https://example.com/1"},
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = FirecrawlClient(http_client=http_client)

    init_res = await client.crawl("https://example.com")
    assert init_res["id"] == "crawl-123"

    poll_res = await client.poll_crawl("crawl-123", poll_interval=0.01, max_wait=1.0)
    assert poll_res["status"] == "completed"
    assert len(poll_res["data"]) == 1
