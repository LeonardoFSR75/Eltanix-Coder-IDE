"""Orquestração de documentos: ingestão (extrai, fatia, embeda, persiste) e busca.

O embedding sai pelo próprio router, igual ao `ContextIndexer` — mesma regra
do ADR 0001, nenhum SDK de embedding separado.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from typing import Any

from pypdf import PdfReader

from sicoobito.config import Settings
from sicoobito.db.session import session_scope
from sicoobito.documents import store
from sicoobito.documents.chunker import TextChunk, chunk_text
from sicoobito.documents.store import DocumentSearchHit
from sicoobito.logging_setup import get_logger
from sicoobito.router.engine import RouterEngine
from sicoobito.storage.blob import BlobStore

log = get_logger(__name__)


def _extract_pages(data: bytes) -> list[str]:
    """Leitura/parse do PDF — bloqueante, roda fora do event loop."""
    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text() or "" for page in reader.pages]


class DocumentService:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: RouterEngine,
        blob: BlobStore,
        trace_recorder: Any | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.blob = blob
        self.trace_recorder = trace_recorder

    async def _embed(self, chunks: list[TextChunk]) -> tuple[list[list[float] | None], int]:
        """Espelha `ContextIndexer._embed`: falha degrada para chunk sem vetor,
        em vez de perder o documento inteiro."""
        if not chunks:
            return [], 0

        vectors: list[list[float] | None] = []
        failures = 0
        batch_size = max(1, self.settings.embedding_batch_size)

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            inputs = [c.content for c in batch]
            try:
                result = await self.engine.embed(
                    requested_model=self.settings.embedding_profile,
                    inputs=inputs,
                    source="documents",
                )
            except Exception as exc:
                log.warning("documents.embed.failed", error=str(exc)[:200], batch=len(batch))
                vectors.extend([None] * len(batch))
                failures += len(batch)
                continue

            data = result.payload.get("data") or []
            by_index = {
                int(item.get("index", i)): item.get("embedding") for i, item in enumerate(data)
            }
            for position in range(len(batch)):
                vector = by_index.get(position)
                if vector is None:
                    failures += 1
                vectors.append(vector)

        return vectors, failures

    async def ingest(self, document_id: uuid.UUID) -> None:
        """Roda como BackgroundTask: extrai texto, fatia, embeda, persiste.

        Não bloqueia a resposta de `/confirm` — um PDF de várias dezenas de
        páginas leva segundos para embeddar, tempo demais para uma requisição
        HTTP síncrona.
        """
        async with session_scope() as session:
            document = await store.get_document(session, document_id)
            if document is None:
                return
            bucket_key = document.minio_object

        try:
            data = await self.blob.get_object(bucket_key)
            pages = await asyncio.to_thread(_extract_pages, data)
        except Exception as exc:
            log.warning(
                "documents.ingest.extract_failed", document=str(document_id), error=str(exc)[:200]
            )
            async with session_scope() as session:
                await store.set_status(session, document_id, status="failed", error=str(exc)[:500])
            return

        all_chunks: list[TextChunk] = []
        for page_number, page_text in enumerate(pages, start=1):
            all_chunks.extend(
                chunk_text(
                    page_text,
                    chunk_tokens=self.settings.documents_chunk_tokens,
                    overlap_tokens=self.settings.documents_chunk_overlap_tokens,
                    page_number=page_number,
                )
            )

        if not all_chunks:
            async with session_scope() as session:
                await store.set_status(
                    session, document_id, status="failed", error="Nenhum texto extraído do PDF."
                )
            return

        # `chunk_index` sai por página do chunker (reinicia em 0 a cada
        # página); renumerar globalmente evita colisão entre chunks de
        # páginas diferentes na mesma posição.
        for position, chunk in enumerate(all_chunks):
            chunk.chunk_index = position

        vectors, failures = await self._embed(all_chunks)
        if failures:
            log.warning(
                "documents.ingest.embed_partial", document=str(document_id), failures=failures
            )

        async with session_scope() as session:
            await store.mark_indexed(
                session,
                document_id,
                page_count=len(pages),
                chunks=all_chunks,
                embeddings=vectors,
            )

        log.info(
            "documents.ingest.finished",
            document=str(document_id),
            pages=len(pages),
            chunks=len(all_chunks),
            embed_failures=failures,
        )

    async def search(self, query: str, *, limit: int = 8) -> list[DocumentSearchHit]:
        inicio = time.perf_counter()
        query_embedding: list[float] | None = None
        try:
            result = await self.engine.embed(
                requested_model=self.settings.embedding_profile,
                inputs=[query],
                source="documents_search",
            )
            data = result.payload.get("data") or []
            if data:
                query_embedding = data[0].get("embedding")
        except Exception as exc:
            log.warning("documents.search.embed_failed", error=str(exc)[:200])

        status = "ok"
        try:
            async with session_scope() as session:
                return await store.hybrid_search(
                    session, query_text=query, query_embedding=query_embedding, limit=limit
                )
        except Exception:
            status = "error"
            raise
        finally:
            if self.trace_recorder is not None:
                self.trace_recorder.record(
                    kind="rag",
                    name="documents",
                    latency_ms=(time.perf_counter() - inicio) * 1000.0,
                    status=status,
                )
