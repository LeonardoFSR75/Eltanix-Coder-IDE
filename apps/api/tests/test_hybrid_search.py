"""Teste de integração real para as três `hybrid_search` (RRF) — código,
documentos, notas.

A duplicação entre as três seções abaixo é deliberada, mesmo espírito da
duplicação entre os três `hybrid_search` reais (ver docstring de
`notes/store.py`): são pequenas e a leitura direta vale mais que uma fixture
genérica compartilhada entre domínios diferentes.

Pulado por padrão — ver a fixture `pg_session` em `conftest.py` e
`apps/api/CLAUDE.md` para como rodar isto localmente contra Postgres real.
Vetores de embedding são fixos, não vêm de um provedor: pgvector só faz a
matemática de distância de cosseno, não precisa de significado semântico
verdadeiro para o teste validar a query SQL e o RRF.
"""

from __future__ import annotations

import time
import uuid

from eltanix.config import get_settings
from eltanix.context import store as context_store
from eltanix.context.chunker import Chunk
from eltanix.documents import store as documents_store
from eltanix.documents.chunker import TextChunk
from eltanix.notes import store as notes_store

_VECTOR = [0.1] * get_settings().embedding_dim


async def test_context_hybrid_search_finds_the_indexed_chunk(pg_session):
    workspace = f"test-hybrid-{uuid.uuid4().hex[:8]}"
    chunk = Chunk(
        path="zzqrk_context.py",
        content="def zzqrktestcontext():\n    return 'RRF de código'\n",
        start_line=1,
        end_line=2,
        kind="function",
        symbol="zzqrktestcontext",
    )
    await context_store.upsert_file(
        pg_session,
        workspace=workspace,
        path=chunk.path,
        content_hash="hash-context-1",
        language="python",
        size_bytes=100,
        mtime=time.time(),
        chunks=[chunk],
        embeddings=[_VECTOR],
        fallback_chunking=False,
    )

    hits = await context_store.hybrid_search(
        pg_session, workspace=workspace, query_text="zzqrktestcontext", query_embedding=_VECTOR
    )
    assert [h.path for h in hits] == [chunk.path]
    assert hits[0].vector_rank == 1
    assert hits[0].text_rank == 1

    # Embedding indisponível (modelo local fora do ar) — degrada para
    # full-text puro em vez de devolver vazio.
    hits_sem_embedding = await context_store.hybrid_search(
        pg_session, workspace=workspace, query_text="zzqrktestcontext", query_embedding=None
    )
    assert [h.path for h in hits_sem_embedding] == [chunk.path]
    assert hits_sem_embedding[0].vector_rank is None
    assert hits_sem_embedding[0].text_rank == 1


async def test_documents_hybrid_search_finds_the_indexed_chunk(pg_session):
    document = await documents_store.create_document(
        pg_session,
        filename="zzqrk_documento.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        bucket="test-bucket",
        object_key="test-object",
    )
    chunk = TextChunk(
        content="Relatório sobre zzqrktestdocuments e a fusão RRF.",
        chunk_index=0,
        token_count=10,
        page_number=1,
    )
    await documents_store.mark_indexed(
        pg_session, document.id, page_count=1, chunks=[chunk], embeddings=[_VECTOR]
    )

    hits = await documents_store.hybrid_search(
        pg_session, query_text="zzqrktestdocuments", query_embedding=_VECTOR
    )
    alvo = next((h for h in hits if h.document_id == str(document.id)), None)
    assert alvo is not None, "chunk indexado não apareceu na busca híbrida"
    assert alvo.vector_rank is not None
    assert alvo.text_rank is not None

    hits_sem_embedding = await documents_store.hybrid_search(
        pg_session, query_text="zzqrktestdocuments", query_embedding=None
    )
    alvo_sem_embedding = next(
        (h for h in hits_sem_embedding if h.document_id == str(document.id)), None
    )
    assert alvo_sem_embedding is not None
    assert alvo_sem_embedding.vector_rank is None
    assert alvo_sem_embedding.text_rank is not None


async def test_notes_hybrid_search_finds_the_indexed_chunk(pg_session):
    note = await notes_store.create_note(
        pg_session,
        title="Nota de teste RRF",
        content="Ideia sobre zzqrktestnotes e busca híbrida.",
        tags=["teste"],
    )
    chunk = TextChunk(
        content="Ideia sobre zzqrktestnotes e busca híbrida.", chunk_index=0, token_count=8
    )
    await notes_store.replace_chunks(pg_session, note.id, chunks=[chunk], embeddings=[_VECTOR])

    hits = await notes_store.hybrid_search(
        pg_session, query_text="zzqrktestnotes", query_embedding=_VECTOR
    )
    alvo = next((h for h in hits if h.note_id == str(note.id)), None)
    assert alvo is not None, "chunk indexado não apareceu na busca híbrida"
    assert alvo.vector_rank is not None
    assert alvo.text_rank is not None

    hits_sem_embedding = await notes_store.hybrid_search(
        pg_session, query_text="zzqrktestnotes", query_embedding=None
    )
    alvo_sem_embedding = next((h for h in hits_sem_embedding if h.note_id == str(note.id)), None)
    assert alvo_sem_embedding is not None
    assert alvo_sem_embedding.vector_rank is None
    assert alvo_sem_embedding.text_rank is not None
