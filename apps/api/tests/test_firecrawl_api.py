"""Testes automatizados das rotas HTTP do Firecrawl (/api/firecrawl/*)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ["NOVAAI_STUDIO_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from novaai_studio.config import Settings, get_settings
from novaai_studio.firecrawl.service import FirecrawlService
from novaai_studio.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def test_firecrawl_scrape_endpoint(client):
    service = FirecrawlService(settings=Settings(FIRECRAWL_API_KEY="test"))
    service.scrape_url = AsyncMock(
        return_value={
            "markdown": "# Conteúdo raspado",
            "metadata": {"title": "Página Teste", "sourceURL": "https://example.com"},
        }
    )
    client.app.state.firecrawl = service

    res = client.post(
        "/api/firecrawl/scrape",
        json={"url": "https://example.com"},
        headers=AUTH,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["markdown"] == "# Conteúdo raspado"


def test_firecrawl_search_endpoint(client):
    service = FirecrawlService(settings=Settings(FIRECRAWL_API_KEY="test"))
    service.search = AsyncMock(
        return_value=[
            {"title": "FastAPI", "url": "https://fastapi.tiangolo.com", "markdown": "Docs"}
        ]
    )
    client.app.state.firecrawl = service

    res = client.post(
        "/api/firecrawl/search",
        json={"query": "fastapi", "limit": 1},
        headers=AUTH,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "FastAPI"


def test_firecrawl_crawl_endpoint(client):
    service = FirecrawlService(settings=Settings(FIRECRAWL_API_KEY="test"))
    service.client.crawl = AsyncMock(
        return_value={"success": True, "id": "job-abc", "url": "https://api.firecrawl.dev/job-abc"}
    )
    client.app.state.firecrawl = service

    res = client.post(
        "/api/firecrawl/crawl",
        json={"url": "https://example.com", "max_depth": 2, "limit": 5},
        headers=AUTH,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["id"] == "job-abc"


def test_firecrawl_ingest_endpoint(client):
    service = FirecrawlService(settings=Settings(FIRECRAWL_API_KEY="test"))
    service.scrape_and_ingest = AsyncMock(
        return_value={
            "document_id": "doc-123",
            "filename": "[Web] Example",
            "chunk_count": 4,
            "status": "ready",
        }
    )
    client.app.state.firecrawl = service

    res = client.post(
        "/api/firecrawl/ingest",
        json={"url": "https://example.com", "crawl": False},
        headers=AUTH,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["result"]["document_id"] == "doc-123"
