"""Orquestração de documentos: ingestão (extrai, fatia, embeda, persiste) e busca.

O embedding sai pelo próprio router, igual ao `ContextIndexer` — mesma regra
do ADR 0001, nenhum SDK de embedding separado.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

from novaai_studio.config import Settings
from novaai_studio.db.session import session_scope
from novaai_studio.documents import store
from novaai_studio.documents.chunker import TextChunk, chunk_text
from novaai_studio.documents.store import DocumentSearchHit
from novaai_studio.logging_setup import get_logger
from novaai_studio.router.engine import RouterEngine
from novaai_studio.storage.blob import BlobStore

log = get_logger(__name__)

# Um PDF pequeno mas adversarial (streams/objetos aninhados propositalmente)
# pode fazer o parser gastar minutos numa única extração — o teto de upload
# limita o tamanho do arquivo, não o tempo de parsing. `asyncio.wait_for` não
# mata a thread por baixo (stdlib não tem timeout de thread multiplataforma),
# mas garante que a ingestão marca `failed` em vez de travar para sempre.
_PDF_EXTRACT_TIMEOUT_SECONDS = 120


@dataclass
class PdfExtractionResult:
    pages: list[str]
    pdf_type: str  # "text_based", "scanned", "image_based", "mixed", "unknown"
    page_count: int
    engine: str  # "pdf_inspector" ou "pypdf"
    pages_needing_ocr: list[int] = field(default_factory=list)
    title: str | None = None


@dataclass
class DocumentExtractionResult:
    pages: list[str]
    doc_type: str  # "pdf:text_based", "docx", "xlsx", "pptx", "csv", "markdown", etc.
    page_count: int
    engine: str  # "pdf_inspector", "pypdf", "anydoc", "text"
    pages_needing_ocr: list[int] = field(default_factory=list)
    title: str | None = None


def _extract_pdf(data: bytes) -> PdfExtractionResult:
    """Leitura, classificação e extração de PDF — roda fora do event loop.

    1. Tenta usar `pdf_inspector` (Rust de alta performance com detecção de scan e Markdown).
    2. Se for documento 100% escaneado sem texto extraído, levanta ValueError explícito.
    3. Em caso de falha ou indisponibilidade, faz fallback transparente para `pypdf`.
    """
    # 1. Tentativa primária: pdf_inspector
    try:
        import pdf_inspector

        proc_result = pdf_inspector.process_pdf_bytes(data)
        pdf_type = getattr(proc_result, "pdf_type", "unknown")
        pages_needing_ocr = getattr(proc_result, "pages_needing_ocr", []) or []
        title = getattr(proc_result, "title", None)

        pages_extracted: list[str] = []
        try:
            pages_res = pdf_inspector.extract_pages_markdown_bytes(data)
            if hasattr(pages_res, "pages"):
                pages_extracted = [p.markdown or "" for p in pages_res.pages]
        except Exception:
            pass

        if not pages_extracted and proc_result.markdown:
            pages_extracted = [proc_result.markdown]

        has_text = any(p.strip() for p in pages_extracted)

        if pdf_type in ("scanned", "image_based") and not has_text:
            raise ValueError(
                "Documento digitalizado/escaneado sem camada de texto vetorial. "
                "Requer OCR prévio para indexação."
            )

        if has_text:
            return PdfExtractionResult(
                pages=pages_extracted,
                pdf_type=pdf_type,
                page_count=getattr(proc_result, "page_count", len(pages_extracted)),
                engine="pdf_inspector",
                pages_needing_ocr=pages_needing_ocr,
                title=title,
            )
    except ValueError:
        raise
    except Exception as exc:
        log.warning("documents.pdf_inspector.fallback", error=str(exc)[:200], engine="pypdf")

    # 2. Fallback resiliente: pypdf
    try:
        reader = PdfReader(io.BytesIO(data))
        fallback_pages = [page.extract_text() or "" for page in reader.pages]
        return PdfExtractionResult(
            pages=fallback_pages,
            pdf_type="unknown",
            page_count=len(fallback_pages),
            engine="pypdf",
        )
    except Exception as exc:
        raise ValueError(f"Falha ao ler o PDF com o parser de fallback: {exc}") from exc


def _detect_format_from_filename_or_content_type(
    filename: str, content_type: str | None
) -> str | None:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    ext_map = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "doc",
        ".docm": "docm",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".xlsm": "xlsm",
        ".xlsb": "xlsb",
        ".pptx": "pptx",
        ".ppt": "ppt",
        ".pps": "pps",
        ".ppsx": "ppsx",
        ".odt": "odt",
        ".ods": "ods",
        ".odp": "odp",
        ".rtf": "rtf",
        ".epub": "epub",
        ".csv": "csv",
        ".tsv": "csv",
        ".txt": "txt",
        ".md": "md",
        ".markdown": "md",
    }
    if ext in ext_map:
        return ext_map[ext]
    if content_type:
        ct = content_type.lower()
        if "pdf" in ct:
            return "pdf"
        if "wordprocessingml" in ct or "msword" in ct:
            return "docx"
        if "spreadsheetml" in ct or "ms-excel" in ct:
            return "xlsx"
        if "presentationml" in ct or "ms-powerpoint" in ct:
            return "pptx"
        if "opendocument.text" in ct:
            return "odt"
        if "opendocument.spreadsheet" in ct:
            return "ods"
        if "opendocument.presentation" in ct:
            return "odp"
        if "rtf" in ct:
            return "rtf"
        if "epub" in ct:
            return "epub"
        if "csv" in ct:
            return "csv"
        if "markdown" in ct:
            return "md"
        if "text/plain" in ct:
            return "txt"
    return None


def _extract_document_content(
    data: bytes, filename: str = "", content_type: str = ""
) -> DocumentExtractionResult:
    """Extrai conteúdo e metadados de documentos em múltiplos formatos."""
    fmt = _detect_format_from_filename_or_content_type(filename, content_type)

    # 1. Se for PDF, usa o pipeline especializado do PDF Inspector
    if fmt == "pdf":
        pdf_res = _extract_pdf(data)
        return DocumentExtractionResult(
            pages=pdf_res.pages,
            doc_type=f"pdf:{pdf_res.pdf_type}",
            page_count=pdf_res.page_count,
            engine=pdf_res.engine,
            pages_needing_ocr=pdf_res.pages_needing_ocr,
            title=pdf_res.title,
        )

    # 2. Se for texto puro ou Markdown
    if fmt in ("txt", "md"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        return DocumentExtractionResult(
            pages=[text],
            doc_type=fmt,
            page_count=1,
            engine="text",
        )

    # 3. Formato de escritório (Word, Excel, PowerPoint, ODF, RTF, EPUB, CSV): AnyDoc
    try:
        import anydoc

        markdown = anydoc.to_markdown_bytes(data, format=fmt)
        if not markdown or not markdown.strip():
            raise ValueError(f"Nenhum texto pôde ser extraído do arquivo '{filename}'.")

        return DocumentExtractionResult(
            pages=[markdown],
            doc_type=fmt or "anydoc",
            page_count=1,
            engine="anydoc",
            title=filename,
        )
    except ValueError:
        raise
    except Exception as exc:
        log.warning("documents.anydoc.failed", filename=filename, error=str(exc)[:200])
        # Fallback de decodificação direta de texto se aplicável
        try:
            text = data.decode("utf-8")
            if text.strip():
                return DocumentExtractionResult(
                    pages=[text],
                    doc_type="text:fallback",
                    page_count=1,
                    engine="text",
                )
        except Exception:
            pass
        raise ValueError(f"Falha ao processar o documento '{filename}': {exc}") from exc


def _extract_pages(data: bytes) -> list[str]:
    """Leitura/parse do PDF — mantido para compatibilidade retroativa."""
    return _extract_pdf(data).pages


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
            extraction = await asyncio.wait_for(
                asyncio.to_thread(
                    _extract_document_content,
                    data,
                    filename=document.filename,
                    content_type=document.content_type,
                ),
                timeout=_PDF_EXTRACT_TIMEOUT_SECONDS,
            )
            pages = extraction.pages
        except TimeoutError:
            log.warning(
                "documents.ingest.extract_timeout",
                document=str(document_id),
                timeout_s=_PDF_EXTRACT_TIMEOUT_SECONDS,
            )
            async with session_scope() as session:
                await store.set_status(
                    session,
                    document_id,
                    status="failed",
                    error=f"Extração excedeu {_PDF_EXTRACT_TIMEOUT_SECONDS}s.",
                )
            return
        except ValueError as exc:
            log.warning(
                "documents.ingest.extract_rejected",
                document=str(document_id),
                error=str(exc),
            )
            async with session_scope() as session:
                await store.set_status(
                    session,
                    document_id,
                    status="failed",
                    error=str(exc)[:300],
                )
            return
        except Exception as exc:
            log.warning(
                "documents.ingest.extract_failed", document=str(document_id), error=str(exc)[:200]
            )
            async with session_scope() as session:
                await store.set_status(session, document_id, status="failed", error=str(exc)[:300])
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
                    session,
                    document_id,
                    status="failed",
                    error="Nenhum texto extraído do documento.",
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
            engine=extraction.engine,
            doc_type=extraction.doc_type,
            pages=len(pages),
            chunks=len(all_chunks),
            embed_failures=failures,
        )

    async def search(
        self, query: str, *, limit: int = 8, project_slug: str | None = None
    ) -> list[DocumentSearchHit]:
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
                    session,
                    query_text=query,
                    query_embedding=query_embedding,
                    limit=limit,
                    project_slug=project_slug,
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
