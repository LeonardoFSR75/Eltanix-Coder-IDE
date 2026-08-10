"""Persistência do índice semântico do cache — consulta de vizinho mais
próximo sobre `cached_response_embedding`, mesmo estilo de
`context/store.py::hybrid_search` (SQL cru, pgvector).

Linhas expiradas são filtradas na própria consulta (`expires_at > now()`) —
sem job de limpeza em background nesta v1; uma linha expirada só ocupa espaço
até o próximo `VACUUM`, nunca é lida de volta.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import CachedResponseEmbedding


async def find_nearest(
    session: AsyncSession,
    *,
    model_id: str,
    embedding: list[float],
    max_distance: float,
) -> str | None:
    """Devolve `redis_cache_key` da linha mais próxima dentro de
    `max_distance` (distância de cosseno, `<=>` do pgvector — menor é mais
    parecido), ou `None` sem candidato dentro do limite. Só considera o
    MESMO `model_id`: respostas de modelos diferentes não são intercambiáveis
    (mesmo racional de `ResponseCache.key()` incluir o modelo resolvido)."""
    sql = text(
        """
        SELECT redis_cache_key
        FROM cached_response_embedding
        WHERE model_id = :model_id
          AND expires_at > now()
          AND embedding <=> CAST(:embedding AS vector) < :max_distance
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT 1
        """
    )
    result = await session.execute(
        sql,
        {
            "model_id": model_id,
            "embedding": str(embedding),
            "max_distance": max_distance,
        },
    )
    row = result.first()
    return row[0] if row else None


async def insert(
    session: AsyncSession,
    *,
    model_id: str,
    redis_cache_key: str,
    embedding: list[float],
    expires_at: datetime,
) -> None:
    session.add(
        CachedResponseEmbedding(
            id=uuid.uuid4(),
            model_id=model_id,
            redis_cache_key=redis_cache_key,
            embedding=embedding,
            expires_at=expires_at,
        )
    )
    await session.flush()
