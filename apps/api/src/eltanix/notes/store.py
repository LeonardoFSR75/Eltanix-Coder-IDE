"""Persistência e busca de notas (Segundo Cérebro).

Mesma forma de `documents/store.py` — RRF sobre `note_chunk` em vez de
`document_chunk`. A duplicação entre os três `hybrid_search` (código,
documentos, notas) é deliberada: são pequenos e a leitura direta vale mais
que uma abstração compartilhada neste ponto.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.db.models import Note, NoteChunk
from eltanix.documents.chunker import TextChunk
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

RRF_K = 60


@dataclass(slots=True)
class NoteSearchHit:
    note_id: str
    title: str
    chunk_index: int
    content: str
    token_count: int
    score: float
    vector_rank: int | None = None
    text_rank: int | None = None


async def create_note(
    session: AsyncSession,
    *,
    title: str,
    content: str,
    tags: list[str],
    project_slug: str | None = None,
) -> Note:
    note = Note(title=title, content=content, tags=tags, links=[], project_slug=project_slug)
    session.add(note)
    await session.flush()
    return note


async def get_note(session: AsyncSession, note_id: uuid.UUID) -> Note | None:
    return await session.get(Note, note_id)


async def get_note_by_title(session: AsyncSession, title: str) -> Note | None:
    return await session.scalar(select(Note).where(func.lower(Note.title) == title.lower()))


# Teto de segurança para o `list_notes` sem paginação — evita que uma base
# muito grande vire uma resposta HTTP sem limite (e uma query sem teto).
_LIST_HARD_CAP = 2000


async def list_notes(session: AsyncSession, *, project_slug: str | None = None) -> list[Note]:
    """Sem `project_slug`, lista tudo (até `_LIST_HARD_CAP`). Com ele, notas
    do projeto mais as "globais" (sem projeto) — mesmo fallback de
    `hybrid_search`."""
    stmt = select(Note).order_by(Note.updated_at.desc()).limit(_LIST_HARD_CAP)
    if project_slug:
        stmt = stmt.where((Note.project_slug == project_slug) | (Note.project_slug.is_(None)))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def list_titles(session: AsyncSession, *, project_slug: str | None = None) -> dict[str, str]:
    """Mapa `título em minúsculas -> id (str)`, usado para resolver `[[wikilinks]]`.

    Mesmo filtro de projeto de `list_notes`/`hybrid_search` (projeto + notas
    globais) — sem isso, um `[[Título Compartilhado]]` em qualquer nota
    resolvia para a primeira nota de mesmo título encontrada em QUALQUER
    projeto do banco, gravando um link cross-projeto sem o usuário pedir.
    """
    stmt = select(Note.id, Note.title)
    if project_slug:
        stmt = stmt.where((Note.project_slug == project_slug) | (Note.project_slug.is_(None)))
    rows = (await session.execute(stmt)).all()
    return {title.lower(): str(note_id) for note_id, title in rows}


async def update_note(
    session: AsyncSession,
    note_id: uuid.UUID,
    *,
    title: str,
    content: str,
    tags: list[str],
    links: list[str],
) -> Note | None:
    note = await session.get(Note, note_id)
    if note is None:
        return None
    note.title = title
    note.content = content
    note.tags = tags
    note.links = links
    await session.flush()
    return note


async def delete_note(session: AsyncSession, note_id: uuid.UUID) -> Note | None:
    note = await session.get(Note, note_id)
    if note is None:
        return None
    await session.delete(note)  # chunks caem por ON DELETE CASCADE
    return note


async def replace_chunks(
    session: AsyncSession,
    note_id: uuid.UUID,
    *,
    chunks: list[TextChunk],
    embeddings: list[list[float] | None],
    embedding_model: str | None = None,
) -> None:
    """Refatia do zero a cada save — notas são curtas, o custo é baixo, e evita
    chunk órfão apontando para uma versão antiga do texto."""
    await session.execute(delete(NoteChunk).where(NoteChunk.note_id == note_id))
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        session.add(
            NoteChunk(
                note_id=note_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                embedding=embedding,
                embedding_model=embedding_model if embedding is not None else None,
            )
        )
    await session.flush()


async def hybrid_search(
    session: AsyncSession,
    *,
    query_text: str,
    query_embedding: list[float] | None,
    limit: int = 8,
    candidate_pool: int = 50,
    project_slug: str | None = None,
    embedding_model: str | None = None,
    ef_search: int | None = None,
    vector_weight: float = 1.0,
    text_weight: float = 1.0,
    rrf_k: int = RRF_K,
) -> list[NoteSearchHit]:
    """Com `project_slug`, restringe às notas do projeto mais as "globais"
    (sem projeto) — mesmo fallback documentado em `documents/store.py`.

    `embedding_model` e `ef_search`: mesma semântica de
    `context/store.py::hybrid_search`."""
    if ef_search is not None and session.bind is not None:
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(int(ef_search))},
            )

    params: dict[str, object] = {
        "pool": candidate_pool,
        "limit": limit,
        "k": rrf_k,
        "q": query_text,
        "w_vector": float(vector_weight),
        "w_text": float(text_weight),
    }
    project_filter = ""
    if project_slug:
        params["project_slug"] = project_slug
        project_filter = "AND (n.project_slug = :project_slug OR n.project_slug IS NULL)"

    # `ORDER BY ... LIMIT` na subquery e `ROW_NUMBER()` por fora — declara o
    # top-k, não muda o plano. Ver a nota em `context/store.py::hybrid_search`.
    # Mesma tsquery de `context/store.py`: literal unida à versão com
    # identificadores separados (`eltanix_split_identifiers`, migração 0032).
    # Documento técnico cita nome de símbolo tanto quanto código.
    tsquery = (
        "(websearch_to_tsquery('simple', :q)"
        " || websearch_to_tsquery('simple', eltanix_split_identifiers(:q)))"
    )
    text_cte = f"""
        texto AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY relevancia DESC) AS rank
            FROM (
                SELECT c.id AS id,
                       ts_rank_cd(c.tsv, {tsquery}) AS relevancia
                FROM note_chunk c
                JOIN note n ON n.id = c.note_id
                WHERE c.tsv @@ {tsquery}
                {project_filter}
                ORDER BY relevancia DESC
                LIMIT :pool
            ) AS candidatos_texto
        )
    """

    if query_embedding is not None:
        params["embedding"] = str(query_embedding)
        modelo_filtro = ""
        if embedding_model:
            params["embedding_model"] = embedding_model
            modelo_filtro = "AND c.embedding_model = :embedding_model"
        sql = f"""
            WITH vetor AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY distancia) AS rank
                FROM (
                    SELECT c.id AS id,
                           c.embedding <=> CAST(:embedding AS vector) AS distancia
                    FROM note_chunk c
                    JOIN note n ON n.id = c.note_id
                    WHERE c.embedding IS NOT NULL
                    {modelo_filtro}
                    {project_filter}
                    ORDER BY c.embedding <=> CAST(:embedding AS vector)
                    LIMIT :pool
                ) AS candidatos_vetor
            ),
            {text_cte},
            fusao AS (
                SELECT COALESCE(v.id, t.id) AS id,
                       v.rank AS vector_rank,
                       t.rank AS text_rank,
                       COALESCE(:w_vector / (:k + v.rank), 0.0)
                     + COALESCE(:w_text / (:k + t.rank), 0.0) AS score
                FROM vetor v
                FULL OUTER JOIN texto t ON v.id = t.id
            )
            SELECT c.note_id, n.title, c.chunk_index, c.content, c.token_count,
                   f.score, f.vector_rank, f.text_rank
            FROM fusao f
            JOIN note_chunk c ON c.id = f.id
            JOIN note n ON n.id = c.note_id
            ORDER BY f.score DESC
            LIMIT :limit
        """
    else:
        log.warning("notes.search.no_embedding", detail="degradando para full-text puro")
        sql = f"""
            WITH {text_cte}
            SELECT c.note_id, n.title, c.chunk_index, c.content, c.token_count,
                   :w_text / (:k + t.rank) AS score,
                   NULL::bigint AS vector_rank,
                   t.rank AS text_rank
            FROM texto t
            JOIN note_chunk c ON c.id = t.id
            JOIN note n ON n.id = c.note_id
            ORDER BY score DESC
            LIMIT :limit
        """

    rows = (await session.execute(text(sql), params)).mappings().all()

    return [
        NoteSearchHit(
            note_id=str(row["note_id"]),
            title=row["title"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            token_count=row["token_count"],
            score=float(row["score"]),
            vector_rank=int(row["vector_rank"]) if row["vector_rank"] is not None else None,
            text_rank=int(row["text_rank"]) if row["text_rank"] is not None else None,
        )
        for row in rows
    ]
