"""Teste de integração real para `optimizer/semantic_cache_store.py` — a
consulta de vizinho mais próximo por pgvector. Vetores fixos, não vêm de um
provedor de verdade: só a matemática de distância de cosseno importa aqui
(mesmo racional de `tests/test_hybrid_search.py`).

Pulado por padrão — ver a fixture `pg_session` em `conftest.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from eltanix.config import get_settings
from eltanix.optimizer import semantic_cache_store

_DIM = get_settings().embedding_dim


def _vector(seed: float) -> list[float]:
    # Vetor quase constante, só a primeira posição varia — controla a
    # distância de cosseno de forma previsível para o teste.
    return [seed] + [1.0] * (_DIM - 1)


async def test_find_nearest_returns_key_within_threshold(pg_session):
    model_id = f"modelo-{uuid.uuid4().hex[:8]}"
    expira_em = datetime.now(UTC) + timedelta(hours=1)
    await semantic_cache_store.insert(
        pg_session,
        model_id=model_id,
        redis_cache_key="chave-perto",
        embedding=_vector(1.0),
        expires_at=expira_em,
    )
    await pg_session.flush()

    chave = await semantic_cache_store.find_nearest(
        pg_session, model_id=model_id, embedding=_vector(1.0), max_distance=0.05
    )
    assert chave == "chave-perto"


async def test_find_nearest_returns_none_outside_threshold(pg_session):
    # Em 768 dimensões, mudar só o primeiro elemento (como `_vector` faz)
    # quase não move a distância de cosseno — "diferente" de verdade aqui é
    # o vetor NEGADO inteiro (similaridade -1, distância 2), bem fora de
    # qualquer `max_distance` razoável.
    model_id = f"modelo-{uuid.uuid4().hex[:8]}"
    expira_em = datetime.now(UTC) + timedelta(hours=1)
    consulta = _vector(1.0)
    oposto = [-v for v in consulta]
    await semantic_cache_store.insert(
        pg_session,
        model_id=model_id,
        redis_cache_key="chave-longe",
        embedding=oposto,
        expires_at=expira_em,
    )
    await pg_session.flush()

    chave = await semantic_cache_store.find_nearest(
        pg_session, model_id=model_id, embedding=consulta, max_distance=0.05
    )
    assert chave is None


async def test_find_nearest_does_not_cross_models(pg_session):
    # Duas respostas quase idênticas em embedding, mas de MODELOS diferentes
    # — não são intercambiáveis (mesmo racional de ResponseCache.key()).
    embedding = _vector(1.0)
    expira_em = datetime.now(UTC) + timedelta(hours=1)
    modelo_a = f"modelo-a-{uuid.uuid4().hex[:8]}"
    modelo_b = f"modelo-b-{uuid.uuid4().hex[:8]}"

    await semantic_cache_store.insert(
        pg_session,
        model_id=modelo_a,
        redis_cache_key="chave-do-a",
        embedding=embedding,
        expires_at=expira_em,
    )
    await pg_session.flush()

    chave = await semantic_cache_store.find_nearest(
        pg_session, model_id=modelo_b, embedding=embedding, max_distance=0.05
    )
    assert chave is None


async def test_find_nearest_excludes_expired_rows(pg_session):
    model_id = f"modelo-{uuid.uuid4().hex[:8]}"
    ja_expirou = datetime.now(UTC) - timedelta(hours=1)
    await semantic_cache_store.insert(
        pg_session,
        model_id=model_id,
        redis_cache_key="chave-expirada",
        embedding=_vector(1.0),
        expires_at=ja_expirou,
    )
    await pg_session.flush()

    chave = await semantic_cache_store.find_nearest(
        pg_session, model_id=model_id, embedding=_vector(1.0), max_distance=0.05
    )
    assert chave is None


async def test_find_nearest_picks_the_closest_of_multiple_candidates(pg_session):
    model_id = f"modelo-{uuid.uuid4().hex[:8]}"
    expira_em = datetime.now(UTC) + timedelta(hours=1)

    await semantic_cache_store.insert(
        pg_session,
        model_id=model_id,
        redis_cache_key="chave-media",
        embedding=_vector(0.9),
        expires_at=expira_em,
    )
    await semantic_cache_store.insert(
        pg_session,
        model_id=model_id,
        redis_cache_key="chave-exata",
        embedding=_vector(1.0),
        expires_at=expira_em,
    )
    await pg_session.flush()

    chave = await semantic_cache_store.find_nearest(
        pg_session, model_id=model_id, embedding=_vector(1.0), max_distance=0.5
    )
    assert chave == "chave-exata"
