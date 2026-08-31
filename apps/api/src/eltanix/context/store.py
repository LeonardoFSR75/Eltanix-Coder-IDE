"""Persistência e busca do índice de contexto.

A busca é híbrida por necessidade, não por moda. Vetor sozinho erra quando a
pergunta cita um identificador exato (`RoutingPolicy`, `AZURE_API_BASE`):
embedding aproxima significado, não string. Texto sozinho erra quando a pergunta
é conceitual ("onde decidimos qual modelo usar"). Fundir os dois cobre os dois
casos, e o Reciprocal Rank Fusion faz isso sem precisar calibrar pesos entre
escalas incomparáveis (distância de cosseno vs. ts_rank).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.context.chunker import Chunk
from eltanix.db.models import CodeChunk, CodeEdge, IndexedFile
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

# Constante do RRF. 60 é o valor do artigo original (Cormack et al.) e funciona
# bem sem ajuste: amortece a diferença entre as primeiras posições.
RRF_K = 60

# Prefixo do `content_hash` de um arquivo cujo embedding falhou. O hash real
# nunca começa assim (hexadecimal só tem a-f), então o marcador não colide —
# e faz a próxima indexação reprocessar o arquivo em vez de pulá-lo por
# "inalterado". Ver `ContextIndexer.index_workspace`.
PENDING_HASH_PREFIX = "pendente:"


def _escape_like(value: str) -> str:
    """Escapa `%`/`_` antes de virar operador LIKE — sem isto, um
    `path_prefix` contendo esses caracteres filtra mais do que o caminho
    literal pretendido (ex.: `path_prefix="%"` casaria tudo)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(slots=True)
class SearchHit:
    path: str
    symbol: str | None
    parent: str | None
    kind: str
    start_line: int
    end_line: int
    content: str
    language: str | None
    token_count: int
    score: float
    vector_rank: int | None = None
    text_rank: int | None = None
    # Posição na perna de trigrama (pg_trgm sobre `symbol`/`path`). `None`
    # quando o chunk entrou só pelas outras pernas — é o caso comum.
    trigram_rank: int | None = None

    @property
    def citation(self) -> str:
        location = f"{self.path}:{self.start_line}"
        if self.symbol:
            return f"{location} ({self.symbol})"
        return location


async def upsert_file(
    session: AsyncSession,
    *,
    workspace: str,
    path: str,
    content_hash: str,
    language: str | None,
    size_bytes: int,
    mtime: float,
    chunks: list[Chunk],
    embeddings: list[list[float] | None],
    fallback_chunking: bool,
    embedding_model: str | None = None,
) -> tuple[IndexedFile, list[CodeChunk]]:
    """Substitui o arquivo e todos os seus chunks.

    Substituir em vez de fazer diff de chunk é deliberado: editar uma função no
    meio do arquivo desloca as linhas de tudo abaixo, então quase todos os
    chunks mudariam de qualquer forma. Reindexar o arquivo inteiro é mais
    simples e não deixa chunk órfão apontando para linha errada.
    """
    existing = await session.scalar(
        select(IndexedFile).where(IndexedFile.workspace == workspace, IndexedFile.path == path)
    )

    if existing is None:
        existing = IndexedFile(workspace=workspace, path=path)
        session.add(existing)
    else:
        await session.execute(delete(CodeChunk).where(CodeChunk.file_id == existing.id))

    existing.content_hash = content_hash
    existing.language = language
    existing.size_bytes = size_bytes
    existing.mtime = mtime
    existing.chunk_count = len(chunks)
    existing.fallback_chunking = fallback_chunking

    # O flush vem **depois** de preencher os campos obrigatórios: antes disso o
    # INSERT sairia com content_hash nulo. Ele é necessário aqui para que
    # `existing.id` exista antes de virar chave estrangeira dos chunks.
    await session.flush()

    persisted: list[CodeChunk] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        row = CodeChunk(
            file_id=existing.id,
            workspace=workspace,
            path=chunk.path,
            language=chunk.language,
            symbol=chunk.symbol[:256] if chunk.symbol else None,
            parent=chunk.parent[:256] if chunk.parent else None,
            kind=chunk.kind,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content=chunk.content,
            token_count=chunk.token_count,
            embedding=embedding,
            # Só etiqueta o que tem vetor: `embedding_model` preenchido com
            # `embedding` nulo seria mentira sobre um chunk que ficou de fora
            # do ramo vetorial.
            embedding_model=embedding_model if embedding is not None else None,
        )
        session.add(row)
        persisted.append(row)

    # Flush para os chunks ganharem `id` — `context/edges.py` precisa deles
    # para montar as arestas do Code Knowledge Graph logo em seguida.
    await session.flush()
    return existing, persisted


async def delete_missing(session: AsyncSession, *, workspace: str, present_paths: set[str]) -> int:
    """Remove do índice arquivos que sumiram do disco."""
    rows = (
        await session.execute(
            select(IndexedFile.id, IndexedFile.path).where(IndexedFile.workspace == workspace)
        )
    ).all()

    stale = [row.id for row in rows if row.path not in present_paths]
    if not stale:
        return 0

    # Os chunks caem por ON DELETE CASCADE.
    await session.execute(delete(IndexedFile).where(IndexedFile.id.in_(stale)))
    return len(stale)


async def known_hashes(session: AsyncSession, workspace: str) -> dict[str, str]:
    rows = (
        await session.execute(
            select(IndexedFile.path, IndexedFile.content_hash).where(
                IndexedFile.workspace == workspace
            )
        )
    ).all()
    return {row.path: row.content_hash for row in rows}


async def hybrid_search(
    session: AsyncSession,
    *,
    workspace: str,
    query_text: str,
    query_embedding: list[float] | None,
    limit: int = 12,
    candidate_pool: int = 50,
    path_prefix: str | None = None,
    embedding_model: str | None = None,
    ef_search: int | None = None,
    vector_weight: float = 1.0,
    text_weight: float = 1.0,
    trigram_weight: float = 0.5,
    rrf_k: int = RRF_K,
) -> list[SearchHit]:
    """Busca vetorial + full-text + trigrama, fundidas por Reciprocal Rank Fusion.

    Sem embedding disponível (modelo local fora do ar), degrada para as pernas
    lexicais em vez de não devolver nada.

    **Três sinais, não dois.** Vetor aproxima significado e erra o
    identificador exato; full-text acerta o identificador e erra a pergunta
    conceitual; trigrama sobre `symbol`/`path` cobre o que os dois erram —
    nome parcial e erro de digitação (`extract_failed_call` achando
    `extract_failed_tool_call`). O peso menor do trigrama é deliberado: ele é
    sinal de apoio, não par dos outros dois.

    **Pesos por sinal.** O RRF clássico soma `1/(k+rank)` com peso igual. Aqui
    cada perna tem peso próprio, para que a calibração seja medida
    (`eltanix-eval-rag`) em vez de herdada do artigo original.

    `embedding_model` restringe o ramo vetorial aos chunks gerados pelo mesmo
    modelo que produziu `query_embedding` — comparar vetores de modelos
    diferentes devolve ruído com cara de resultado. Chunks de outro modelo (ou
    anteriores à coluna de proveniência) continuam achaveis pelas pernas
    lexicais.

    `ef_search` ajusta `hnsw.ef_search` só nesta transação: o default do
    pgvector devolve menos vizinhos do que `candidate_pool` pede.
    """
    if ef_search is not None and session.bind is not None:
        # `set_config` em vez de `SET LOCAL` porque só ele aceita parâmetro
        # ligado; `SET LOCAL hnsw.ef_search = :ef` não é interpolável.
        # `is_local=true` mantém o efeito preso à transação corrente.
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(int(ef_search))},
            )

    filters = ["workspace = :workspace"]
    params: dict[str, object] = {
        "workspace": workspace,
        "pool": candidate_pool,
        "limit": limit,
        "k": rrf_k,
        "q": query_text,
        "w_vector": float(vector_weight),
        "w_text": float(text_weight),
        "w_trigram": float(trigram_weight),
    }
    if path_prefix:
        filters.append(r"path LIKE :path_prefix ESCAPE '\'")
        params["path_prefix"] = f"{_escape_like(path_prefix)}%"
    where_clause = " AND ".join(filters)

    # `websearch_to_tsquery` tolera aspas e operadores digitados pelo usuário
    # sem estourar erro de sintaxe, ao contrário de `to_tsquery`.
    #
    # O `ORDER BY ... LIMIT` fica na subquery e o `ROW_NUMBER()` por fora, nas
    # duas pernas.
    #
    # Isto NÃO é otimização: medido com EXPLAIN ANALYZE contra pgvector, a
    # forma anterior (janela na mesma consulta do `LIMIT`) também usava o
    # índice HNSW — o planner empurra o `LIMIT` através do `WindowAgg` e para
    # o Index Scan cedo. Os dois planos custam o mesmo.
    #
    # O motivo é de correção: `LIMIT` depois de uma função de janela, sem
    # `ORDER BY` externo, devolve as linhas na ordem em que o `WindowAgg` as
    # emitiu. Na prática ele emite ordenado, mas isso é detalhe de execução,
    # não garantia da linguagem. Aqui o top-k está declarado.
    #
    # A tsquery é a união de duas: a literal e a com identificadores separados
    # por `eltanix_split_identifiers` (migração 0032). A função é a **mesma**
    # que gera a coluna `tsv`, de propósito — se a consulta separasse de um
    # jeito e o índice de outro, o casamento dependeria de coincidência.
    # Com as duas: `getUserById` acha `get_user_by_id`, e quem colar
    # `getuserbyid` inteiro continua achando.
    tsquery = (
        "(websearch_to_tsquery('simple', :q)"
        " || websearch_to_tsquery('simple', eltanix_split_identifiers(:q)))"
    )
    text_cte = f"""
        texto AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY relevancia DESC) AS rank
            FROM (
                SELECT id, ts_rank_cd(tsv, {tsquery}) AS relevancia
                FROM code_chunk
                WHERE {where_clause}
                  AND tsv @@ {tsquery}
                ORDER BY relevancia DESC
                LIMIT :pool
            ) AS candidatos_texto
        )
    """

    # `%` é o operador de similaridade do pg_trgm e usa os índices GIN trigram
    # criados na 0032; `similarity()` só ordena o que ele já filtrou.
    trigram_cte = f"""
        trigrama AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY semelhanca DESC) AS rank
            FROM (
                SELECT id,
                       GREATEST(
                           similarity(COALESCE(symbol, ''), :q),
                           similarity(path, :q)
                       ) AS semelhanca
                FROM code_chunk
                WHERE {where_clause}
                  AND (COALESCE(symbol, '') % :q OR path % :q)
                ORDER BY semelhanca DESC
                LIMIT :pool
            ) AS candidatos_trigrama
        )
    """

    if query_embedding is not None:
        params["embedding"] = str(query_embedding)
        modelo_filtro = ""
        if embedding_model:
            params["embedding_model"] = embedding_model
            modelo_filtro = "AND embedding_model = :embedding_model"
        sql = f"""
            WITH vetor AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY distancia) AS rank
                FROM (
                    SELECT id, embedding <=> CAST(:embedding AS vector) AS distancia
                    FROM code_chunk
                    WHERE {where_clause} AND embedding IS NOT NULL {modelo_filtro}
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :pool
                ) AS candidatos_vetor
            ),
            {text_cte},
            {trigram_cte},
            fusao AS (
                SELECT COALESCE(v.id, t.id, g.id) AS id,
                       v.rank AS vector_rank,
                       t.rank AS text_rank,
                       g.rank AS trigram_rank,
                       COALESCE(:w_vector / (:k + v.rank), 0.0)
                     + COALESCE(:w_text / (:k + t.rank), 0.0)
                     + COALESCE(:w_trigram / (:k + g.rank), 0.0) AS score
                FROM vetor v
                FULL OUTER JOIN texto t ON v.id = t.id
                FULL OUTER JOIN trigrama g ON g.id = COALESCE(v.id, t.id)
            )
            SELECT c.path, c.symbol, c.parent, c.kind, c.start_line, c.end_line,
                   c.content, c.language, c.token_count,
                   f.score, f.vector_rank, f.text_rank, f.trigram_rank
            FROM fusao f
            JOIN code_chunk c ON c.id = f.id
            ORDER BY f.score DESC
            LIMIT :limit
        """
    else:
        log.warning("context.search.no_embedding", detail="degradando para pernas lexicais")
        sql = f"""
            WITH {text_cte},
            {trigram_cte},
            fusao AS (
                SELECT COALESCE(t.id, g.id) AS id,
                       t.rank AS text_rank,
                       g.rank AS trigram_rank,
                       COALESCE(:w_text / (:k + t.rank), 0.0)
                     + COALESCE(:w_trigram / (:k + g.rank), 0.0) AS score
                FROM texto t
                FULL OUTER JOIN trigrama g ON g.id = t.id
            )
            SELECT c.path, c.symbol, c.parent, c.kind, c.start_line, c.end_line,
                   c.content, c.language, c.token_count,
                   f.score,
                   NULL::bigint AS vector_rank,
                   f.text_rank, f.trigram_rank
            FROM fusao f
            JOIN code_chunk c ON c.id = f.id
            ORDER BY f.score DESC
            LIMIT :limit
        """

    rows = (await session.execute(text(sql), params)).mappings().all()

    return [
        SearchHit(
            path=row["path"],
            symbol=row["symbol"],
            parent=row["parent"],
            kind=row["kind"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            content=row["content"],
            language=row["language"],
            token_count=row["token_count"],
            score=float(row["score"]),
            vector_rank=int(row["vector_rank"]) if row["vector_rank"] is not None else None,
            text_rank=int(row["text_rank"]) if row["text_rank"] is not None else None,
            trigram_rank=int(row["trigram_rank"]) if row["trigram_rank"] is not None else None,
        )
        for row in rows
    ]


async def index_stats(session: AsyncSession, workspace: str) -> dict[str, object]:
    files, fallback = (
        await session.execute(
            select(
                func.count(IndexedFile.id),
                func.coalesce(
                    func.sum(case((IndexedFile.fallback_chunking.is_(True), 1), else_=0)), 0
                ),
            ).where(IndexedFile.workspace == workspace)
        )
    ).one()

    chunks, tokens, embedded = (
        await session.execute(
            select(
                func.count(CodeChunk.id),
                func.coalesce(func.sum(CodeChunk.token_count), 0),
                func.coalesce(func.sum(case((CodeChunk.embedding.is_not(None), 1), else_=0)), 0),
            ).where(CodeChunk.workspace == workspace)
        )
    ).one()

    by_language = (
        await session.execute(
            select(IndexedFile.language, func.count(IndexedFile.id))
            .where(IndexedFile.workspace == workspace)
            .group_by(IndexedFile.language)
            .order_by(func.count(IndexedFile.id).desc())
        )
    ).all()

    # Proveniência: mais de um modelo aqui significa índice com espaços
    # vetoriais misturados — a busca vai filtrar por um só e o resto vira
    # invisível ao ramo vetorial até reindexar.
    by_model = (
        await session.execute(
            select(CodeChunk.embedding_model, func.count(CodeChunk.id))
            .where(CodeChunk.workspace == workspace, CodeChunk.embedding.is_not(None))
            .group_by(CodeChunk.embedding_model)
            .order_by(func.count(CodeChunk.id).desc())
        )
    ).all()

    pendentes = await session.scalar(
        select(func.count(IndexedFile.id)).where(
            IndexedFile.workspace == workspace,
            IndexedFile.content_hash.like(f"{PENDING_HASH_PREFIX}%"),
        )
    )

    total_chunks = int(chunks or 0)
    return {
        "files": int(files or 0),
        "chunks": total_chunks,
        "total_tokens": int(tokens or 0),
        "chunks_with_embedding": int(embedded or 0),
        # Sem isto, "chunks_with_embedding" sozinho não diz se o índice está
        # 99% ou 40% vetorizado — é o número que o reaper de backfill persegue.
        "embedding_coverage": round(int(embedded or 0) / total_chunks, 4) if total_chunks else 0.0,
        "files_pending_embedding": int(pendentes or 0),
        "files_line_chunked": int(fallback or 0),
        "by_language": [
            {"language": language or "desconhecida", "files": int(count)}
            for language, count in by_language
        ],
        "by_embedding_model": [
            {"model": model or "desconhecido", "chunks": int(count)} for model, count in by_model
        ],
    }


async def workspaces_pending_embedding(session: AsyncSession) -> list[tuple[str, int]]:
    """Workspaces com arquivo marcado `pendente:` — embedding indisponível na
    hora da indexação (ver `ContextIndexer.index_workspace`).

    O arquivo não fica perdido: como o hash gravado não é o real, a próxima
    passagem de indexação o reprocessa. O que faltava era alguém *disparar*
    essa passagem — é o que `run_embedding_backfill_reaper` faz com esta lista.
    """
    rows = (
        await session.execute(
            select(IndexedFile.workspace, func.count(IndexedFile.id))
            .where(IndexedFile.content_hash.like(f"{PENDING_HASH_PREFIX}%"))
            .group_by(IndexedFile.workspace)
            .order_by(func.count(IndexedFile.id).desc())
        )
    ).all()
    return [(str(workspace), int(count)) for workspace, count in rows]


# --- Code Knowledge Graph -------------------------------------------------
#
# `contains` liga chunk a chunk (classe → método) e some sozinho via CASCADE
# quando o chunk de origem é reindexado. `imports` liga arquivo a arquivo por
# `to_path` — não há chunk representando "o arquivo inteiro", então a aresta
# não tem `to_chunk_id`, e por isso não desaparece com CASCADE quando o
# arquivo *destino* é reindexado (o que é o comportamento certo: quem importa
# esse arquivo continua importando, os chunks dele é que trocaram de id).


async def insert_edges(
    session: AsyncSession,
    *,
    workspace: str,
    contains: list[tuple[uuid.UUID, uuid.UUID]],
    imports: list[tuple[uuid.UUID, str]],
) -> None:
    for from_id, to_id in contains:
        session.add(
            CodeEdge(workspace=workspace, from_chunk_id=from_id, to_chunk_id=to_id, kind="contains")
        )
    for from_id, to_path in imports:
        session.add(
            CodeEdge(workspace=workspace, from_chunk_id=from_id, to_path=to_path, kind="imports")
        )
    if contains or imports:
        await session.flush()


async def find_chunk(
    session: AsyncSession,
    *,
    workspace: str,
    path: str,
    symbol: str | None = None,
    line: int | None = None,
) -> CodeChunk | None:
    """Localiza o chunk a partir do qual explorar o grafo.

    `symbol` é preciso; `line` é aproximado (o primeiro chunk cuja faixa
    cobre a linha); sem nenhum dos dois, devolve o primeiro chunk do arquivo
    — normalmente o chunk `module` com os imports do topo.
    """
    stmt = select(CodeChunk).where(CodeChunk.workspace == workspace, CodeChunk.path == path)
    if symbol:
        stmt = stmt.where(CodeChunk.symbol == symbol)
    elif line is not None:
        stmt = stmt.where(CodeChunk.start_line <= line, CodeChunk.end_line >= line)
    stmt = stmt.order_by(CodeChunk.start_line).limit(1)
    return await session.scalar(stmt)


async def children_of(
    session: AsyncSession, *, workspace: str, chunk_id: uuid.UUID
) -> list[CodeChunk]:
    rows = await session.execute(
        select(CodeChunk)
        .join(CodeEdge, CodeEdge.to_chunk_id == CodeChunk.id)
        .where(
            CodeEdge.workspace == workspace,
            CodeEdge.kind == "contains",
            CodeEdge.from_chunk_id == chunk_id,
        )
        .order_by(CodeChunk.start_line)
    )
    return list(rows.scalars().all())


async def container_of(
    session: AsyncSession, *, workspace: str, chunk_id: uuid.UUID
) -> CodeChunk | None:
    return await session.scalar(
        select(CodeChunk)
        .join(CodeEdge, CodeEdge.from_chunk_id == CodeChunk.id)
        .where(
            CodeEdge.workspace == workspace,
            CodeEdge.kind == "contains",
            CodeEdge.to_chunk_id == chunk_id,
        )
    )


async def imports_of(session: AsyncSession, *, workspace: str, path: str) -> list[str]:
    """Arquivos que `path` importa e que resolveram para dentro do índice."""
    rows = await session.execute(
        select(CodeEdge.to_path)
        .join(CodeChunk, CodeChunk.id == CodeEdge.from_chunk_id)
        .where(
            CodeEdge.workspace == workspace,
            CodeEdge.kind == "imports",
            CodeChunk.path == path,
        )
        .distinct()
    )
    return sorted(p for p in rows.scalars().all() if p)


async def imported_by(session: AsyncSession, *, workspace: str, path: str) -> list[str]:
    """Arquivos que importam `path` (aresta reversa — não passa por chunk_id
    porque o alvo de `imports` é sempre um caminho, nunca um chunk)."""
    rows = await session.execute(
        select(CodeChunk.path)
        .join(CodeEdge, CodeEdge.from_chunk_id == CodeChunk.id)
        .where(
            CodeEdge.workspace == workspace,
            CodeEdge.kind == "imports",
            CodeEdge.to_path == path,
        )
        .distinct()
    )
    return sorted(rows.scalars().all())


async def import_graph(session: AsyncSession, *, workspace: str) -> dict[str, set[str]]:
    """Adjacência arquivo → arquivos que ele importa, só `kind='imports'`.

    Base para `edges.find_cycles` — devolvida como dict simples porque quem
    chama vai rodar um algoritmo de grafo em Python, não outra query SQL.
    """
    rows = await session.execute(
        select(CodeChunk.path, CodeEdge.to_path)
        .join(CodeEdge, CodeEdge.from_chunk_id == CodeChunk.id)
        .where(
            CodeEdge.workspace == workspace,
            CodeEdge.kind == "imports",
            CodeEdge.to_path.is_not(None),
        )
        .distinct()
    )
    graph: dict[str, set[str]] = {}
    for from_path, to_path in rows.all():
        graph.setdefault(from_path, set()).add(to_path)
    return graph


async def orphan_modules(session: AsyncSession, *, workspace: str) -> list[str]:
    """Arquivos indexados que nenhum outro arquivo importa.

    Inclui pontos de entrada legítimos (`main.py`, `__init__.py`, testes) —
    isso não é uma lista de código morto pronta, é o ponto de partida para
    uma investigação (ver o aviso equivalente no prompt do modo `explore`).
    """
    all_paths = set(
        (await session.execute(select(IndexedFile.path).where(IndexedFile.workspace == workspace)))
        .scalars()
        .all()
    )
    imported_paths = set(
        (
            await session.execute(
                select(CodeEdge.to_path).where(
                    CodeEdge.workspace == workspace,
                    CodeEdge.kind == "imports",
                    CodeEdge.to_path.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return sorted(all_paths - imported_paths)


@dataclass(slots=True)
class CodeGraphResult:
    chunk: CodeChunk | None
    contains: list[CodeChunk]
    contained_by: CodeChunk | None
    imports: list[str]
    imported_by: list[str]


async def code_graph(
    session: AsyncSession,
    *,
    workspace: str,
    path: str,
    symbol: str | None = None,
    line: int | None = None,
) -> CodeGraphResult:
    """Vizinhança de 1 hop em torno de um símbolo: quem ele contém, quem o
    contém, o que o arquivo dele importa e quem importa esse arquivo."""
    chunk = await find_chunk(session, workspace=workspace, path=path, symbol=symbol, line=line)
    if chunk is None:
        return CodeGraphResult(
            chunk=None, contains=[], contained_by=None, imports=[], imported_by=[]
        )

    contains = await children_of(session, workspace=workspace, chunk_id=chunk.id)
    contained_by = await container_of(session, workspace=workspace, chunk_id=chunk.id)
    imports = await imports_of(session, workspace=workspace, path=path)
    imported = await imported_by(session, workspace=workspace, path=path)
    return CodeGraphResult(
        chunk=chunk,
        contains=contains,
        contained_by=contained_by,
        imports=imports,
        imported_by=imported,
    )
