"""Testes unitários e de segurança para FirecrawlService."""

from __future__ import annotations

import pytest

from sicoobito.config import Settings
from sicoobito.firecrawl.service import FirecrawlService, validate_target_url


def test_validate_target_url_valid():
    validate_target_url("https://docs.python.org/3/library/asyncio.html")
    validate_target_url("http://example.com/api/v1")


def test_validate_target_url_blocks_invalid_and_ssrf():
    with pytest.raises(ValueError, match="vazia"):
        validate_target_url("")

    with pytest.raises(ValueError, match="http:// ou https://"):
        validate_target_url("ftp://example.com")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://localhost:8000/secret")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://127.0.0.1:5401/api/v1")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://169.254.169.254/latest/meta-data")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://postgres:5432")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://192.168.1.1/admin")

    with pytest.raises(ValueError, match="bloqueado por política de segurança"):
        validate_target_url("http://10.0.0.5:8080")


@pytest.mark.asyncio
async def test_service_scrape_and_search_delegation(monkeypatch):
    settings = Settings(FIRECRAWL_API_KEY="dummy", FIRECRAWL_API_URL="https://api.firecrawl.dev")
    service = FirecrawlService(settings=settings)

    async def mock_scrape(url, **kwargs):
        return {"markdown": f"# Content from {url}", "metadata": {"title": "Test Title"}}

    async def mock_search(query, **kwargs):
        return [{"title": "Search Result", "url": "https://example.com", "markdown": "Sample"}]

    monkeypatch.setattr(service.client, "scrape", mock_scrape)
    monkeypatch.setattr(service.client, "search", mock_search)

    res = await service.scrape_url("https://example.com")
    assert res["markdown"] == "# Content from https://example.com"

    search_res = await service.search("query")
    assert len(search_res) == 1
    assert search_res[0]["title"] == "Search Result"
