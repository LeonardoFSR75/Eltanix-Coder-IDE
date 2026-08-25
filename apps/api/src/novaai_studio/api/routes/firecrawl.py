"""Rotas da API para operações do Firecrawl (scrape, search, crawl, ingestão RAG)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from novaai_studio.api.deps import AuthDep
from novaai_studio.firecrawl.client import (
    FirecrawlAuthError,
    FirecrawlError,
    FirecrawlRateLimitError,
    FirecrawlUnavailableError,
)
from novaai_studio.firecrawl.service import FirecrawlService
from novaai_studio.logging_setup import get_logger

router = APIRouter(prefix="/api/firecrawl", tags=["firecrawl"], dependencies=[AuthDep])

log = get_logger(__name__)


def _service(request: Request) -> FirecrawlService:
    service: FirecrawlService | None = getattr(request.app.state, "firecrawl", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço Firecrawl indisponível.",
        )
    return service


class ScrapeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    only_main_content: bool = True
    wait_for: int = Field(default=0, ge=0, le=30_000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


class MapRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    search: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=100, ge=1, le=500)


class CrawlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    max_depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=10, ge=1, le=100)
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None


class IngestRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    project: str | None = Field(default=None, max_length=128)
    crawl: bool = False
    max_depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/scrape")
async def scrape_url(payload: ScrapeRequest, request: Request) -> dict[str, Any]:
    """Raspa uma página web usando o Firecrawl."""
    service = _service(request)
    try:
        data = await service.scrape_url(
            payload.url,
            only_main_content=payload.only_main_content,
            wait_for=payload.wait_for,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FirecrawlAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Autenticação no Firecrawl falhou: {exc}",
        ) from exc
    except FirecrawlRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite do Firecrawl atingido: {exc}",
        ) from exc
    except FirecrawlUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Firecrawl indisponível: {exc}",
        ) from exc
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/search")
async def search_web(payload: SearchRequest, request: Request) -> dict[str, Any]:
    """Pesquisa na web via Firecrawl e extrai conteúdo dos resultados."""
    service = _service(request)
    try:
        results = await service.search(payload.query, limit=payload.limit)
        return {"ok": True, "results": results}
    except FirecrawlAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Autenticação no Firecrawl falhou: {exc}",
        ) from exc
    except FirecrawlUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Firecrawl indisponível: {exc}",
        ) from exc
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/map")
async def map_site(payload: MapRequest, request: Request) -> dict[str, Any]:
    """Mapeia links de um domínio via Firecrawl."""
    service = _service(request)
    try:
        links = await service.map_site(payload.url, search=payload.search, limit=payload.limit)
        return {"ok": True, "links": links}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/crawl")
async def start_crawl(payload: CrawlRequest, request: Request) -> dict[str, Any]:
    """Inicia um job de crawl no Firecrawl."""
    service = _service(request)
    try:
        data = await service.client.crawl(
            payload.url,
            max_depth=payload.max_depth,
            limit=payload.limit,
            include_paths=payload.include_paths,
            exclude_paths=payload.exclude_paths,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/crawl/{crawl_id}")
async def get_crawl_status(crawl_id: str, request: Request) -> dict[str, Any]:
    """Consulta o status de um job de crawl."""
    service = _service(request)
    try:
        data = await service.client.get_crawl_status(crawl_id)
        return {"ok": True, "data": data}
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest_web(payload: IngestRequest, request: Request) -> dict[str, Any]:
    """Raspa ou rastreia uma página/site e indexa diretamente na base RAG."""
    service = _service(request)
    try:
        if payload.crawl:
            result = await service.crawl_and_ingest(
                payload.url,
                project_slug=payload.project,
                max_depth=payload.max_depth,
                limit=payload.limit,
            )
        else:
            result = await service.scrape_and_ingest(
                payload.url,
                project_slug=payload.project,
            )
        return {"ok": True, "result": result}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FirecrawlAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Autenticação no Firecrawl falhou: {exc}",
        ) from exc
    except FirecrawlUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Firecrawl indisponível: {exc}",
        ) from exc
    except FirecrawlError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
