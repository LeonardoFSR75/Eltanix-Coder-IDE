"""Orquestração da indexação.

O embedding sai pelo próprio router (perfil `embedding`), não por um SDK
separado — a mesma regra do ADR 0001. Por padrão isso significa
`nomic-embed-text` no Ollama: custo zero e nenhum trecho do código saindo da
máquina.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from sicoobito.config import Settings
from sicoobito.context import store
from sicoobito.context.chunker import Chunk, FileChunks, chunk_file
from sicoobito.context.scanner import ScannedFile, read_text, scan
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger
from sicoobito.router.engine import RouterEngine

log = get_logger(__name__)


def _read_and_chunk(scanned: ScannedFile) -> FileChunks | None:
    """Leitura e parse — bloqueantes, executados fora do event loop."""
    content = read_text(scanned.absolute)
    if content is None:
        return None
    result = chunk_file(scanned.path, content, scanned.language)
    return result if result.chunks else None


@dataclass(slots=True)
class IndexReport:
    workspace: str
    scanned: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    removed: int = 0
    chunks: int = 0
    embedded: int = 0
    embedding_failures: int = 0
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)


class ContextIndexer:
    def __init__(self, *, settings: Settings, engine: RouterEngine) -> None:
        self.settings = settings
        self.engine = engine

    def workspace_key(self, root: Path) -> str:
        """Chave estável do workspace no banco.

        É o caminho absoluto normalizado: um índice por diretório raiz, sem
        depender de um id gerado que se perderia entre execuções.
        """
        return str(root.resolve()).replace("\\", "/")

    async def _embed(self, chunks: list[Chunk]) -> tuple[list[list[float] | None], int]:
        """Gera embeddings em lote. Falha degrada para chunk sem vetor."""
        if not chunks:
            return [], 0

        vectors: list[list[float] | None] = []
        failures = 0
        batch_size = max(1, self.settings.embedding_batch_size)

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            inputs = [chunk.as_embedding_text() for chunk in batch]
            try:
                result = await self.engine.embed(
                    requested_model=self.settings.embedding_profile,
                    inputs=inputs,
                    source="indexer",
                )
            except Exception as exc:
                # Sem vetor o chunk ainda é encontrável por full-text; perder o
                # arquivo inteiro seria pior.
                log.warning("indexer.embed.failed", error=str(exc)[:200], batch=len(batch))
                vectors.extend([None] * len(batch))
                failures += len(batch)
                continue

            data = result.payload.get("data") or []
            by_index = {
                int(item.get("index", i)): item.get("embedding")
                for i, item in enumerate(data)
            }
            for position in range(len(batch)):
                vector = by_index.get(position)
                if vector is None:
                    failures += 1
                vectors.append(vector)

        return vectors, failures

    async def index_workspace(self, root: Path, *, force: bool = False) -> IndexReport:
        started = time.perf_counter()
        # Varredura, leitura e parse são bloqueantes: indexar um repositório
        # grande no event loop deixaria o gateway sem responder enquanto isso.
        root = await asyncio.to_thread(root.resolve)
        workspace = self.workspace_key(root)
        report = IndexReport(workspace=workspace)

        if not await asyncio.to_thread(root.is_dir):
            report.errors.append(f"workspace não é um diretório: {root}")
            return report

        async with session_scope() as session:
            previous = {} if force else await store.known_hashes(session, workspace)

        scanned_files: list[ScannedFile] = await asyncio.to_thread(lambda: list(scan(root)))
        present: set[str] = set()

        for scanned in scanned_files:
            report.scanned += 1
            present.add(scanned.path)

            if previous.get(scanned.path) == scanned.content_hash:
                report.skipped_unchanged += 1
                continue

            result = await asyncio.to_thread(_read_and_chunk, scanned)
            if result is None:
                continue

            vectors, failures = await self._embed(result.chunks)
            report.embedding_failures += failures
            report.embedded += sum(1 for v in vectors if v is not None)

            try:
                async with session_scope() as session:
                    await store.upsert_file(
                        session,
                        workspace=workspace,
                        path=scanned.path,
                        content_hash=scanned.content_hash,
                        language=scanned.language,
                        size_bytes=scanned.size_bytes,
                        mtime=scanned.mtime,
                        chunks=result.chunks,
                        embeddings=vectors,
                        fallback_chunking=result.fallback_used,
                    )
            except Exception as exc:
                message = f"{scanned.path}: {exc}"
                log.warning("indexer.upsert.failed", path=scanned.path, error=str(exc)[:200])
                report.errors.append(message[:300])
                continue

            report.indexed += 1
            report.chunks += len(result.chunks)

        async with session_scope() as session:
            report.removed = await store.delete_missing(
                session, workspace=workspace, present_paths=present
            )

        report.duration_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "indexer.finished",
            workspace=workspace,
            scanned=report.scanned,
            indexed=report.indexed,
            skipped=report.skipped_unchanged,
            removed=report.removed,
            chunks=report.chunks,
            duration_ms=report.duration_ms,
        )
        return report

    async def search(
        self,
        *,
        root: Path,
        query: str,
        limit: int = 12,
        path_prefix: str | None = None,
    ) -> list[store.SearchHit]:
        workspace = self.workspace_key(root)

        query_embedding: list[float] | None = None
        try:
            result = await self.engine.embed(
                requested_model=self.settings.embedding_profile,
                inputs=[query],
                source="search",
            )
            data = result.payload.get("data") or []
            if data:
                query_embedding = data[0].get("embedding")
        except Exception as exc:
            log.warning("indexer.query_embed.failed", error=str(exc)[:200])

        async with session_scope() as session:
            return await store.hybrid_search(
                session,
                workspace=workspace,
                query_text=query,
                query_embedding=query_embedding,
                limit=limit,
                path_prefix=path_prefix,
            )

    async def stats(self, root: Path) -> dict[str, object]:
        async with session_scope() as session:
            return await store.index_stats(session, self.workspace_key(root))
