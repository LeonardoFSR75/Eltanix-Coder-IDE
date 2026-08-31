"""Persistência e busca de documentos (RAG).

Busca híbrida no mesmo espírito de `context/store.py::hybrid_search` — vetor
sozinho erra em termos exatos, texto sozinho erra em busca conceitual, RRF
funde os dois sem precisar calibrar pesos entre escalas incomparáveis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.db.models import Document, DocumentChunk
from eltanix.documents.chunker import TextChunk
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

# Mesma constante de RRF usada em context/store.py — 60 é o valor do artigo
# original (Cormack et al.), amortece a diferença entre as primeiras posições
# sem precisar de calibração.
RRF_K = 60


@dataclass(slots=True)
class DocumentSearchHit:
    document_id: str
    filename: str
    chunk_index: int
    page_number: int | None
    content: str
    token_count: int
    score: float
    vector_rank: int | None = None
    text_rank: int | None = None


async def create_document(
    session: AsyncSession,
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
    bucket: str,
    object_key: str,
    project_slug: str | None = None,
) -> Document:
    document = Document(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        minio_bucket=bucket,
        minio_object=object_key,
        status="pending",
        project_slug=project_slug,
    )
    session.add(document)
    await session.flush()
    return document


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


# Teto de segurança para o `list_documents` sem paginação — evita que uma
# base muito grande vire uma resposta HTTP sem limite (e uma query sem teto).
_LIST_HARD_CAP = 2000


async def list_documents(
    session: AsyncSession, *, project_slug: str | None = None
) -> list[Document]:
    """Sem `project_slug`, lista tudo (até `_LIST_HARD_CAP`). Com ele,
    documentos do projeto mais os "globais" (sem projeto) — mesmo fallback de
    `hybrid_search`."""
    stmt = select(Document).order_by(Document.uploaded_at.desc()).limit(_LIST_HARD_CAP)
    if project_slug:
        stmt = stmt.where(
            (Document.project_slug == project_slug) | (Document.project_slug.is_(None))
        )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def set_status(
    session: AsyncSession, document_id: uuid.UUID, *, status: str, error: str | None = None
) -> None:
    document = await session.get(Document, document_id)
    if document is None:
        return
    document.status = status
    document.error = error


async def mark_indexed(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    page_count: int | None,
    chunks: list[TextChunk],
    embeddings: list[list[float] | None],
    embedding_model: str | None = None,
) -> Document | None:
    """Substitui todos os chunks do documento — mesma lógica de `upsert_file`:
    reindexar do zero é mais simples que fazer diff e não deixa chunk órfão."""
    document = await session.get(Document, document_id)
    if document is None:
        return None

    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    for chunk, embedding in zip(chunks, embeddings, strict=True):
        session.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                content=chunk.content,
                token_count=chunk.token_count,
                embedding=embedding,
                embedding_model=embedding_model if embedding is not None else None,
            )
        )

    document.page_count = page_count
    document.chunk_count = len(chunks)
    document.status = "ready"
    document.error = None
    document.indexed_at = datetime.now(UTC)

    await session.flush()
    return document


async def delete_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    document = await session.get(Document, document_id)
    if document is None:
        return None
    await session.delete(document)  # chunks caem por ON DELETE CASCADE
    return document


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
) -> list[DocumentSearchHit]:
    """Busca vetorial + full-text fundidas por RRF, sobre todos os documentos.

    Sem embedding disponível (modelo local fora do ar), degrada para
    full-text puro, igual à busca de código.

    Com `project_slug`, restringe aos documentos daquele projeto mais os
    "globais" (sem projeto) — documento sem projeto continua visível em
    qualquer busca, é a exceção documentada, não um vazamento.

    `embedding_model` e `ef_search`: mesma semântica de
    `context/store.py::hybrid_search` — proveniência do vetor e tamanho da
    lista de vizinhos do HNSW.
    """
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
        project_filter = "AND (d.project_slug = :project_slug OR d.project_slug IS NULL)"

    # `ORDER BY ... LIMIT` na subquery e `ROW_NUMBER()` por fora: declara o
    # top-k em vez de depender da ordem em que o `WindowAgg` emite as linhas.
    # Não é ganho de plano — medido, a forma anterior também usava o índice
    # HNSW. Ver a nota longa em `context/store.py::hybrid_search`.
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
                FROM document_chunk c
                JOIN document d ON d.id = c.document_id
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
                    FROM document_chunk c
                    JOIN document d ON d.id = c.document_id
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
            SELECT c.document_id, d.filename, c.chunk_index, c.page_number,
                   c.content, c.token_count,
                   f.score, f.vector_rank, f.text_rank
            FROM fusao f
            JOIN document_chunk c ON c.id = f.id
            JOIN document d ON d.id = c.document_id
            ORDER BY f.score DESC
            LIMIT :limit
        """
    else:
        log.warning("documents.search.no_embedding", detail="degradando para full-text puro")
        sql = f"""
            WITH {text_cte}
            SELECT c.document_id, d.filename, c.chunk_index, c.page_number,
                   c.content, c.token_count,
                   :w_text / (:k + t.rank) AS score,
                   NULL::bigint AS vector_rank,
                   t.rank AS text_rank
            FROM texto t
            JOIN document_chunk c ON c.id = t.id
            JOIN document d ON d.id = c.document_id
            ORDER BY score DESC
            LIMIT :limit
        """

    rows = (await session.execute(text(sql), params)).mappings().all()

    return [
        DocumentSearchHit(
            document_id=str(row["document_id"]),
            filename=row["filename"],
            chunk_index=row["chunk_index"],
            page_number=row["page_number"],
            content=row["content"],
            token_count=row["token_count"],
            score=float(row["score"]),
            vector_rank=int(row["vector_rank"]) if row["vector_rank"] is not None else None,
            text_rank=int(row["text_rank"]) if row["text_rank"] is not None else None,
        )
        for row in rows
    ]
