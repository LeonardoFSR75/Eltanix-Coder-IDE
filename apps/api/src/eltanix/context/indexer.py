"""Orquestração da indexação.

O embedding sai pelo próprio router (perfil `embedding`), não por um SDK
separado — a mesma regra do ADR 0001. Por padrão isso significa
`nomic-embed-text` no Ollama: custo zero e nenhum trecho do código saindo da
máquina.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.config import Settings
from eltanix.context import edges, store
from eltanix.context import git_aware as _git_aware
from eltanix.context.chunker import Chunk, FileChunks, chunk_file
from eltanix.context.scanner import ScannedFile, read_text, scan
from eltanix.db.models import CodeChunk
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine

log = get_logger(__name__)


def _read_and_chunk(scanned: ScannedFile) -> tuple[FileChunks, str] | None:
    """Leitura e parse — bloqueantes, executados fora do event loop.

    Devolve o texto junto com os chunks porque `edges.import_targets` precisa
    reparsear o arquivo para achar os imports — sem isso, precisaríamos ler o
    arquivo do disco duas vezes.
    """
    content = read_text(scanned.absolute)
    if content is None:
        return None
    result = chunk_file(scanned.path, content, scanned.language)
    return (result, content) if result.chunks else None


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
    def __init__(
        self, *, settings: Settings, engine: RouterEngine, trace_recorder: Any | None = None
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.trace_recorder = trace_recorder

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
                int(item.get("index", i)): item.get("embedding") for i, item in enumerate(data)
            }
            for position in range(len(batch)):
                vector = by_index.get(position)
                if vector is None:
                    failures += 1
                vectors.append(vector)

        return vectors, failures

    async def _insert_edges(
        self,
        session: AsyncSession,
        *,
        workspace: str,
        path: str,
        language: str | None,
        content: str,
        chunks: list[Chunk],
        persisted: list[CodeChunk],
        known_paths: set[str],
    ) -> None:
        """`contains` + `imports` do arquivo recém-(re)indexado.

        `contains` sai direto de `symbol`/`parent`, sem reparsear nada.
        `imports` precisa de um chunk de origem — usamos o chunk `module`
        (onde o chunker já isola os imports do topo do arquivo) ou, na
        ausência dele, o primeiro chunk do arquivo por linha.
        """
        pairs = list(zip(chunks, (row.id for row in persisted), strict=True))
        contains = edges.contains_edges(pairs)

        anchor_id: uuid.UUID | None = None
        module_pairs = sorted(
            (p for p in pairs if p[0].kind == "module"), key=lambda p: p[0].start_line
        )
        if module_pairs:
            anchor_id = module_pairs[0][1]
        elif pairs:
            anchor_id = min(pairs, key=lambda p: p[0].start_line)[1]

        imports: list[tuple[uuid.UUID, str]] = []
        if anchor_id is not None:
            targets = edges.import_targets(path, content, language or "", known_paths)
            imports = [(anchor_id, target) for target in targets if target != path]

        await store.insert_edges(session, workspace=workspace, contains=contains, imports=imports)

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
        # Universo de resolução para `imports`: import que não aponta para um
        # destes caminhos é pacote externo (ou alias não suportado) e não vira
        # aresta — ver `context/edges.py`.
        known_paths: set[str] = {sf.path for sf in scanned_files}

        for scanned in scanned_files:
            report.scanned += 1
            present.add(scanned.path)

            if previous.get(scanned.path) == scanned.content_hash:
                report.skipped_unchanged += 1
                continue

            outcome = await asyncio.to_thread(_read_and_chunk, scanned)
            if outcome is None:
                continue
            result, content = outcome

            vectors, failures = await self._embed(result.chunks)
            report.embedding_failures += failures
            report.embedded += sum(1 for v in vectors if v is not None)

            # Um arquivo cujo embedding falhou não pode ser marcado como em dia.
            # Gravar o hash real faria a próxima passagem pulá-lo — e os chunks
            # ficariam sem vetor **para sempre**, encontráveis só por full-text,
            # sem nada na saída indicando isso.
            #
            # O corte em 64 é o tamanho da coluna, que o sha256 já ocupa
            # inteira. Não há colisão possível: um hash hexadecimal nunca começa
            # com letras fora de a-f, então o marcador jamais casa com um hash
            # de verdade — que é a única propriedade de que este valor precisa.
            hash_registrado = (
                scanned.content_hash if failures == 0 else f"pendente:{scanned.content_hash}"[:64]
            )

            try:
                async with session_scope() as session:
                    _, persisted = await store.upsert_file(
                        session,
                        workspace=workspace,
                        path=scanned.path,
                        content_hash=hash_registrado,
                        language=scanned.language,
                        size_bytes=scanned.size_bytes,
                        mtime=scanned.mtime,
                        chunks=result.chunks,
                        embeddings=vectors,
                        fallback_chunking=result.fallback_used,
                    )
                    await self._insert_edges(
                        session,
                        workspace=workspace,
                        path=scanned.path,
                        language=scanned.language,
                        content=content,
                        chunks=result.chunks,
                        persisted=persisted,
                        known_paths=known_paths,
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
        git_aware: bool = False,
    ) -> list[store.SearchHit]:
        """`git_aware=True` (Fase 4): expande os hits por vizinhança no Code
        Knowledge Graph e re-rankeia com recência/co-mudança do git. Degrada
        para o `hybrid_search` puro se o grafo ou o git não colaborarem."""
        workspace = self.workspace_key(root)
        inicio = time.perf_counter()

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

        status = "ok"
        try:
            async with session_scope() as session:
                if git_aware:
                    return await _git_aware.git_aware_search(
                        session,
                        root=root,
                        workspace=workspace,
                        query_text=query,
                        query_embedding=query_embedding,
                        limit=limit,
                        path_prefix=path_prefix,
                    )
                return await store.hybrid_search(
                    session,
                    workspace=workspace,
                    query_text=query,
                    query_embedding=query_embedding,
                    limit=limit,
                    path_prefix=path_prefix,
                )
        except Exception:
            status = "error"
            raise
        finally:
            if self.trace_recorder is not None:
                self.trace_recorder.record(
                    kind="rag",
                    name="context",
                    latency_ms=(time.perf_counter() - inicio) * 1000.0,
                    status=status,
                )

    async def stats(self, root: Path) -> dict[str, object]:
        async with session_scope() as session:
            return await store.index_stats(session, self.workspace_key(root))
