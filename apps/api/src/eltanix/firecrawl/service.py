"""Serviço de alto nível do Firecrawl integrado ao RAG e ao Agente.

Gerencia o ciclo de vida do cliente Firecrawl, validação de segurança contra SSRF,
e rotinas para raspar, buscar e indexar conteúdos da web na base vetorial (pgvector).
"""

from __future__ import annotations

from typing import Any

from eltanix.config import Settings
from eltanix.db.models import Document, DocumentChunk
from eltanix.db.session import session_scope
from eltanix.documents.chunker import TextChunk, chunk_text
from eltanix.firecrawl.client import (
    FirecrawlClient,
    FirecrawlConfig,
    FirecrawlError,
)
from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine
from eltanix.security.url_safety import validate_target_url

log = get_logger(__name__)

__all__ = ["FirecrawlService", "validate_target_url"]


class FirecrawlService:
    """Serviço central de integração com o Firecrawl."""

    def __init__(
        self,
        settings: Settings,
        engine: RouterEngine | None = None,
        client: FirecrawlClient | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self._cached_client: FirecrawlClient | None = client

    @property
    def client(self) -> FirecrawlClient:
        if self._cached_client is None:
            self._cached_client = FirecrawlClient(
                FirecrawlConfig(
                    api_key=self.settings.firecrawl_api_key,
                    api_url=self.settings.firecrawl_api_url,
                )
            )
        return self._cached_client

    @property
    def is_available(self) -> bool:
        """Verifica se há chave configurada ou se a URL aponta para self-hosted."""
        is_self_hosted = bool(
            self.settings.firecrawl_api_url
            and "api.firecrawl.dev" not in self.settings.firecrawl_api_url
        )
        return bool(self.settings.firecrawl_api_key or is_self_hosted)

    async def scrape_url(
        self,
        url: str,
        *,
        formats: list[str] | None = None,
        only_main_content: bool = True,
        wait_for: int = 0,
    ) -> dict[str, Any]:
        """Valida e raspa uma URL, retornando o conteúdo e metadados."""
        validate_target_url(url)
        return await self.client.scrape(
            url,
            formats=formats,
            only_main_content=only_main_content,
            wait_for=wait_for,
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Executa busca na web via Firecrawl."""
        if not query or not query.strip():
            return []
        return await self.client.search(query.strip(), limit=limit)

    async def map_site(self, url: str, *, search: str | None = None, limit: int = 100) -> list[str]:
        """Mapeia URLs de um site."""
        validate_target_url(url)
        return await self.client.map_urls(url, search=search, limit=limit)

    async def _embed_chunks(self, chunks: list[TextChunk]) -> list[list[float] | None]:
        """Gera embeddings para os chunks através do RouterEngine."""
        if not chunks or self.engine is None:
            return [None] * len(chunks)

        vectors: list[list[float] | None] = []
        batch_size = max(1, self.settings.embedding_batch_size)

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            inputs = [c.content for c in batch]
            try:
                result = await self.engine.embed(
                    requested_model=self.settings.embedding_profile,
                    inputs=inputs,
                    source="firecrawl",
                )
                data = result.payload.get("data") or []
                by_index = {
                    int(item.get("index", i)): item.get("embedding") for i, item in enumerate(data)
                }
                for pos in range(len(batch)):
                    vectors.append(by_index.get(pos))
            except Exception as exc:
                log.warning("firecrawl.embed.failed", error=str(exc)[:200], batch=len(batch))
                vectors.extend([None] * len(batch))

        return vectors

    async def ingest_page_content(
        self,
        *,
        url: str,
        markdown: str,
        metadata: dict[str, Any] | None = None,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        """Indexa o conteúdo de uma página web diretamente na tabela Document e DocumentChunk."""
        if not markdown or not markdown.strip():
            raise FirecrawlError(f"Nenhum conteúdo obtido para a URL: {url}")

        meta = metadata or {}
        title = str(meta.get("title") or meta.get("ogTitle") or url).strip()
        filename = f"[Web] {title[:180]}" if title else f"[Web] {url[:180]}"

        chunks = chunk_text(
            markdown,
            chunk_tokens=self.settings.documents_chunk_tokens,
            overlap_tokens=self.settings.documents_chunk_overlap_tokens,
        )

        vectors = await self._embed_chunks(chunks)

        async with session_scope() as session:
            doc = Document(
                filename=filename[:512],
                content_type="text/markdown",
                size_bytes=len(markdown.encode("utf-8")),
                minio_bucket="firecrawl",
                minio_object=url[:512],
                project_slug=project_slug,
                status="processing",
                chunk_count=len(chunks),
            )
            session.add(doc)
            await session.flush()

            for chunk, vector in zip(chunks, vectors, strict=False):
                doc_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number or 1,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=vector,
                )
                session.add(doc_chunk)

            doc.status = "ready"
            await session.flush()
            doc_id = str(doc.id)

        log.info("firecrawl.ingested.page", url=url, document_id=doc_id, chunks=len(chunks))
        return {
            "document_id": doc_id,
            "filename": filename,
            "url": url,
            "chunk_count": len(chunks),
            "status": "ready",
        }

    async def scrape_and_ingest(
        self,
        url: str,
        *,
        project_slug: str | None = None,
        only_main_content: bool = True,
    ) -> dict[str, Any]:
        """Raspa uma URL via Firecrawl e indexa na base vetorial RAG."""
        validate_target_url(url)
        data = await self.client.scrape(
            url,
            formats=["markdown"],
            only_main_content=only_main_content,
        )
        markdown = data.get("markdown") or ""
        metadata = data.get("metadata") or {}
        return await self.ingest_page_content(
            url=url,
            markdown=markdown,
            metadata=metadata,
            project_slug=project_slug,
        )

    async def crawl_and_ingest(
        self,
        url: str,
        *,
        project_slug: str | None = None,
        max_depth: int = 2,
        limit: int = 10,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        poll_interval: float = 2.0,
        max_wait: float = 120.0,
    ) -> dict[str, Any]:
        """Rastreia um site/docs via Firecrawl e indexa todas as páginas encontradas."""
        validate_target_url(url)
        crawl_init = await self.client.crawl(
            url,
            max_depth=max_depth,
            limit=limit,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            scrape_options={"formats": ["markdown"], "onlyMainContent": True},
        )
        crawl_id = crawl_init.get("id")
        if not crawl_id:
            raise FirecrawlError("Firecrawl não retornou o identificador do crawl job.")

        result = await self.client.poll_crawl(
            crawl_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
        pages = result.get("data") or []

        indexed_docs: list[dict[str, Any]] = []
        total_chunks = 0

        for page in pages:
            page_md = page.get("markdown") or ""
            page_meta = page.get("metadata") or {}
            page_url = page_meta.get("sourceURL") or page_meta.get("url") or url
            if not page_md.strip():
                continue
            try:
                res = await self.ingest_page_content(
                    url=page_url,
                    markdown=page_md,
                    metadata=page_meta,
                    project_slug=project_slug,
                )
                indexed_docs.append(res)
                total_chunks += res.get("chunk_count", 0)
            except Exception as exc:
                log.warning("firecrawl.crawl.page_ingest_failed", url=page_url, error=str(exc))

        return {
            "crawl_id": crawl_id,
            "status": "completed",
            "pages_indexed": len(indexed_docs),
            "total_chunks": total_chunks,
            "documents": indexed_docs,
        }
