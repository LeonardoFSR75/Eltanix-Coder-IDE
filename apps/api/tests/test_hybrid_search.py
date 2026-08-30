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
from eltanix.context import git_aware
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


async def test_git_aware_graph_expansion_reads_code_edge(pg_session):
    """Fase 4: a expansão de 1 hop (`_graph_neighbors`) resolve a aresta
    `imports` no `code_edge` real e devolve o chunk do arquivo importado como
    vizinho, com score derivado do hit de origem (< score da origem)."""
    workspace = f"test-gitaware-{uuid.uuid4().hex[:8]}"

    origem = Chunk(
        path="zzqrk_origem.py",
        content="import zzqrk_vizinho\n\ndef zzqrkorigem():\n    return zzqrk_vizinho.helper()\n",
        start_line=1,
        end_line=4,
        kind="module",
        symbol=None,
    )
    vizinho = Chunk(
        path="zzqrk_vizinho.py",
        content="def helper():\n    return 'resultado do vizinho'\n",
        start_line=1,
        end_line=2,
        kind="function",
        symbol="helper",
    )
    for c in (origem, vizinho):
        _, persisted = await context_store.upsert_file(
            pg_session,
            workspace=workspace,
            path=c.path,
            content_hash=f"hash-{c.path}",
            language="python",
            size_bytes=100,
            mtime=time.time(),
            chunks=[c],
            embeddings=[_VECTOR],
            fallback_chunking=False,
        )
        if c is origem:
            origem_chunk_id = persisted[0].id

    await context_store.insert_edges(
        pg_session,
        workspace=workspace,
        contains=[],
        imports=[(origem_chunk_id, "zzqrk_vizinho.py")],
    )

    parent_hit = context_store.SearchHit(
        path="zzqrk_origem.py",
        symbol=None,
        parent=None,
        kind="module",
        start_line=1,
        end_line=4,
        content="",
        language="python",
        token_count=10,
        score=0.5,
    )
    neighbors = await git_aware._graph_neighbors(
        pg_session, workspace=workspace, base=[parent_hit]
    )
    assert "zzqrk_vizinho.py" in {n.path for n in neighbors}
    assert all(n.score < parent_hit.score for n in neighbors)

    # E o fluxo completo roda contra Postgres sem erro, com a origem no topo.
    expanded = await git_aware.git_aware_search(
        pg_session,
        root=None,
        workspace=workspace,
        query_text="zzqrkorigem",
        query_embedding=_VECTOR,
        limit=8,
        recency=False,
    )
    assert expanded[0].path == "zzqrk_origem.py"


async def test_git_aware_search_without_edges_matches_plain_hybrid(pg_session):
    """Sem aresta no grafo, `git_aware_search` devolve os mesmos caminhos que
    `hybrid_search` — a expansão não inventa vizinho."""
    workspace = f"test-gitaware-noedge-{uuid.uuid4().hex[:8]}"
    chunk = Chunk(
        path="zzqrk_solo.py",
        content="def zzqrksolo():\n    return 42\n",
        start_line=1,
        end_line=2,
        kind="function",
        symbol="zzqrksolo",
    )
    await context_store.upsert_file(
        pg_session,
        workspace=workspace,
        path=chunk.path,
        content_hash="hash-solo",
        language="python",
        size_bytes=50,
        mtime=time.time(),
        chunks=[chunk],
        embeddings=[_VECTOR],
        fallback_chunking=False,
    )
    plain = await context_store.hybrid_search(
        pg_session, workspace=workspace, query_text="zzqrksolo", query_embedding=_VECTOR
    )
    expanded = await git_aware.git_aware_search(
        pg_session,
        root=None,
        workspace=workspace,
        query_text="zzqrksolo",
        query_embedding=_VECTOR,
        limit=8,
        recency=False,
    )
    assert [h.path for h in expanded] == [h.path for h in plain] == ["zzqrk_solo.py"]


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
