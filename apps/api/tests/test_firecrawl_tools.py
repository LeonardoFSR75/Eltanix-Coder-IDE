"""Testes unitários das ferramentas de agente do Firecrawl."""

from __future__ import annotations

import pytest

from sicoobito.agent.tools import RiskClass, ToolContext, registry
from sicoobito.config import Settings
from sicoobito.firecrawl.service import FirecrawlService
from sicoobito.workspace.fs import WorkspaceFS


@pytest.fixture
def dummy_ctx(tmp_path):
    settings = Settings(FIRECRAWL_API_KEY="test-key")
    service = FirecrawlService(settings=settings)
    return ToolContext(
        session_id="test-session",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        firecrawl=service,
    )


def test_firecrawl_tools_registered_with_correct_risks():
    scrape_tool = registry.get("web_scrape")
    assert scrape_tool is not None
    assert scrape_tool.risk is RiskClass.READ
    assert scrape_tool.risk.requires_approval is False

    search_tool = registry.get("web_search")
    assert search_tool is not None
    assert search_tool.risk is RiskClass.READ
    assert search_tool.risk.requires_approval is False

    crawl_tool = registry.get("crawl_and_index_docs")
    assert crawl_tool is not None
    assert crawl_tool.risk is RiskClass.WRITE
    assert crawl_tool.risk.requires_approval is True

    clone_tool = registry.get("clone_web_ui")
    assert clone_tool is not None
    assert clone_tool.risk is RiskClass.READ
    assert clone_tool.risk.requires_approval is False

    research_tool = registry.get("deep_research")
    assert research_tool is not None
    assert research_tool.risk is RiskClass.READ
    assert research_tool.risk.requires_approval is False


@pytest.mark.asyncio
async def test_web_scrape_tool_success(dummy_ctx, monkeypatch):
    tool = registry.get("web_scrape")
    assert tool is not None

    async def mock_scrape(url, **kwargs):
        return {
            "markdown": "## Documentação da Biblioteca\n\nInstruções de uso.",
            "metadata": {"title": "Doc Lib", "sourceURL": url},
        }

    monkeypatch.setattr(dummy_ctx.firecrawl, "scrape_url", mock_scrape)

    result = await tool.handler(dummy_ctx, {"url": "https://example.com/docs"})
    assert result.ok is True
    assert "Documentação da Biblioteca" in result.content
    assert "Doc Lib" in result.content


@pytest.mark.asyncio
async def test_web_search_tool_success(dummy_ctx, monkeypatch):
    tool = registry.get("web_search")
    assert tool is not None

    async def mock_search(query, **kwargs):
        return [
            {
                "title": "Tutorial Python",
                "url": "https://python.org/tutorial",
                "markdown": "Aprenda Python do zero.",
            }
        ]

    monkeypatch.setattr(dummy_ctx.firecrawl, "search", mock_search)

    result = await tool.handler(dummy_ctx, {"query": "python tutorial"})
    assert result.ok is True
    assert "Tutorial Python" in result.content
    assert "https://python.org/tutorial" in result.content


@pytest.mark.asyncio
async def test_crawl_and_index_docs_tool_success(dummy_ctx, monkeypatch):
    tool = registry.get("crawl_and_index_docs")
    assert tool is not None

    async def mock_crawl(url, **kwargs):
        return {
            "crawl_id": "job-1",
            "pages_indexed": 3,
            "total_chunks": 12,
        }

    monkeypatch.setattr(dummy_ctx.firecrawl, "crawl_and_ingest", mock_crawl)

    result = await tool.handler(dummy_ctx, {"url": "https://example.com/docs"})
    assert result.ok is True
    assert "Páginas indexadas" in result.content
    assert "12" in result.content


@pytest.mark.asyncio
async def test_tool_fails_gracefully_when_service_is_none(tmp_path):
    ctx_no_service = ToolContext(
        session_id="test",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        firecrawl=None,
    )
    scrape_tool = registry.get("web_scrape")
    assert scrape_tool is not None
    result = await scrape_tool.handler(ctx_no_service, {"url": "https://example.com"})
    assert result.ok is False
    assert "Serviço Firecrawl indisponível" in result.content


@pytest.mark.asyncio
async def test_clone_web_ui_success(dummy_ctx, monkeypatch):
    tool = registry.get("clone_web_ui")
    assert tool is not None

    async def mock_scrape(url, **kwargs):
        return {
            "markdown": "# Stripe Payments\n\nFinancial infrastructure for the internet.",
            "html": "<html><body><h1>Stripe Payments</h1></body></html>",
            "metadata": {
                "title": "Stripe | Payment Processing Platform",
                "description": "Financial infrastructure for the internet.",
                "sourceURL": url,
            },
        }

    monkeypatch.setattr(dummy_ctx.firecrawl, "scrape_url", mock_scrape)

    result = await tool.handler(
        dummy_ctx,
        {
            "url": "https://stripe.com",
            "target_framework": "react-tailwind",
            "component_scope": "full-page",
        },
    )
    assert result.ok is True
    assert "UI Blueprint para Recriação em React" in result.content
    assert "Stripe Payments" in result.content
    assert "Navbar" in result.content
    assert "HeroSection" in result.content
    assert result.data["target_framework"] == "react-tailwind"


@pytest.mark.asyncio
async def test_clone_web_ui_ssrf_blocked(dummy_ctx):
    tool = registry.get("clone_web_ui")
    assert tool is not None
    result = await tool.handler(dummy_ctx, {"url": "http://127.0.0.1:8000"})
    assert result.ok is False
    assert "bloqueada" in result.content


@pytest.mark.asyncio
async def test_deep_research_success(dummy_ctx, monkeypatch):
    tool = registry.get("deep_research")
    assert tool is not None

    async def mock_search(query, **kwargs):
        return [
            {
                "title": f"Result for {query[:20]}",
                "url": f"https://example.com/res-{abs(hash(query)) % 1000}",
                "markdown": f"Comprehensive analysis on {query}.",
            }
        ]

    monkeypatch.setattr(dummy_ctx.firecrawl, "search", mock_search)

    result = await tool.handler(
        dummy_ctx,
        {
            "topic": "DuckDB vs ClickHouse",
            "depth": "standard",
        },
    )
    assert result.ok is True
    assert "Relatório de Deep Research: DuckDB vs ClickHouse" in result.content
    assert "Resumo Executivo" in result.content
    assert "Referências & Links Citados" in result.content
    assert result.data["sources_count"] > 0


@pytest.mark.asyncio
async def test_deep_research_empty_topic(dummy_ctx):
    tool = registry.get("deep_research")
    assert tool is not None
    result = await tool.handler(dummy_ctx, {"topic": ""})
    assert result.ok is False
    assert "obrigatório" in result.content
