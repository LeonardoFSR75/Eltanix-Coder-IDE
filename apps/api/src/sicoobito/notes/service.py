"""Orquestração de notas: resolução de `[[wikilinks]]`, fatiamento, embedding e busca."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from sicoobito.config import Settings
from sicoobito.db.models import Note
from sicoobito.db.session import session_scope
from sicoobito.documents.chunker import chunk_text
from sicoobito.logging_setup import get_logger
from sicoobito.notes import store
from sicoobito.notes.store import NoteSearchHit
from sicoobito.router.engine import RouterEngine

log = get_logger(__name__)

# Mesmo padrão que o frontend já usava em `second-brain/page.tsx` — movido
# para o servidor para ser a fonte de verdade única (o agente também precisa
# gravar notas com links corretos via `save_note`).
_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")


class NoteService:
    def __init__(
        self, *, settings: Settings, engine: RouterEngine, trace_recorder: Any | None = None
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.trace_recorder = trace_recorder

    async def _resolve_links(self, session: Any, content: str) -> list[str]:
        titles = _WIKILINK_RE.findall(content)
        if not titles:
            return []
        by_title = await store.list_titles(session)
        links: list[str] = []
        for raw in titles:
            note_id = by_title.get(raw.strip().lower())
            if note_id and note_id not in links:
                links.append(note_id)
        return links

    async def _embed_and_index(self, session: Any, note_id: uuid.UUID, content: str) -> None:
        chunks = chunk_text(
            content,
            chunk_tokens=self.settings.documents_chunk_tokens,
            overlap_tokens=self.settings.documents_chunk_overlap_tokens,
        )
        vectors: list[list[float] | None] = [None] * len(chunks)
        if chunks:
            try:
                result = await self.engine.embed(
                    requested_model=self.settings.embedding_profile,
                    inputs=[c.content for c in chunks],
                    source="notes",
                )
                data = result.payload.get("data") or []
                by_index = {
                    int(item.get("index", idx)): item.get("embedding")
                    for idx, item in enumerate(data)
                }
                vectors = [by_index.get(i) for i in range(len(chunks))]
            except Exception as exc:
                log.warning("notes.embed.failed", error=str(exc)[:200])
        await store.replace_chunks(session, note_id, chunks=chunks, embeddings=vectors)

    async def create(
        self, *, title: str, content: str, tags: list[str], project_slug: str | None = None
    ) -> Note:
        async with session_scope() as session:
            links = await self._resolve_links(session, content)
            note = await store.create_note(
                session, title=title, content=content, tags=tags, project_slug=project_slug
            )
            note.links = links
            await self._embed_and_index(session, note.id, content)
            # `_embed_and_index` grava chunks depois do INSERT da nota, o que
            # dispara um segundo flush (a mudança em `links`) e deixa
            # `updated_at` (onupdate) pendente de um round-trip — sem o
            # refresh explícito, ler o atributo fora do `async with` estoura
            # `DetachedInstanceError`.
            await session.refresh(note)
        return note

    async def update(
        self, note_id: uuid.UUID, *, title: str, content: str, tags: list[str]
    ) -> Note | None:
        async with session_scope() as session:
            links = await self._resolve_links(session, content)
            note = await store.update_note(
                session, note_id, title=title, content=content, tags=tags, links=links
            )
            if note is None:
                return None
            await self._embed_and_index(session, note_id, content)
            await session.refresh(note)
        return note

    async def upsert_by_title(
        self,
        *,
        title: str,
        content: str,
        tags: list[str] | None = None,
        project_slug: str | None = None,
    ) -> Note:
        """Cria ou atualiza por título — é o que sustenta a ferramenta `save_note`
        do agente: perguntar "existe uma nota com esse título" e decidir
        criar/atualizar fica implícito, sem o chamador precisar saber o id."""
        async with session_scope() as session:
            existing = await store.get_note_by_title(session, title)
        if existing is not None:
            updated = await self.update(
                existing.id, title=title, content=content, tags=tags or list(existing.tags)
            )
            assert updated is not None
            return updated
        return await self.create(
            title=title, content=content, tags=tags or [], project_slug=project_slug
        )

    async def delete(self, note_id: uuid.UUID) -> bool:
        async with session_scope() as session:
            note = await store.delete_note(session, note_id)
        return note is not None

    async def list_all(self, *, project_slug: str | None = None) -> list[Note]:
        async with session_scope() as session:
            return await store.list_notes(session, project_slug=project_slug)

    async def get(self, note_id: uuid.UUID) -> Note | None:
        async with session_scope() as session:
            return await store.get_note(session, note_id)

    async def search(
        self, query: str, *, limit: int = 8, project_slug: str | None = None
    ) -> list[NoteSearchHit]:
        inicio = time.perf_counter()
        query_embedding: list[float] | None = None
        try:
            result = await self.engine.embed(
                requested_model=self.settings.embedding_profile,
                inputs=[query],
                source="notes_search",
            )
            data = result.payload.get("data") or []
            if data:
                query_embedding = data[0].get("embedding")
        except Exception as exc:
            log.warning("notes.search.embed_failed", error=str(exc)[:200])

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
                    name="notes",
                    latency_ms=(time.perf_counter() - inicio) * 1000.0,
                    status=status,
                )
