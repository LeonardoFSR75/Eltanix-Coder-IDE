"""Métricas de recuperação — puras, sem Postgres, sem embedding, sem rede.

São o que o gate de CI compara entre execuções; se elas dependessem de
infraestrutura, o gate não rodaria em CI e a régua não existiria.
"""

from __future__ import annotations

import math

from eltanix.evals import metrics
from eltanix.evals.dataset import EvalCase
from eltanix.evals.runner import score_case


def test_dcg_nao_desconta_a_primeira_posicao() -> None:
    assert metrics.dcg([1]) == 1.0
    assert metrics.dcg([0, 1]) == 1 / math.log2(3)


def test_ndcg_perfeito_quando_os_relevantes_vem_primeiro() -> None:
    assert metrics.ndcg([1, 1, 0, 0]) == 1.0


def test_ndcg_penaliza_relevante_no_fim() -> None:
    bom = metrics.ndcg([1, 0, 0, 0])
    ruim = metrics.ndcg([0, 0, 0, 1])
    assert bom == 1.0
    assert 0 < ruim < bom


def test_ndcg_sem_nenhum_relevante_e_zero_e_nao_estoura() -> None:
    assert metrics.ndcg([0, 0, 0]) == 0.0


def test_aggregate_de_lista_vazia_nao_divide_por_zero() -> None:
    assert metrics.aggregate([]) == {"cases": 0, "hit_rate": 0.0, "mrr": 0.0, "ndcg": 0.0}


def test_aggregate_media_hit_mrr_e_ndcg() -> None:
    resultados = [
        {"hit": True, "reciprocal_rank": 1.0, "ndcg": 1.0},
        {"hit": False, "reciprocal_rank": 0.0, "ndcg": 0.0},
    ]
    agg = metrics.aggregate(resultados)
    assert agg["cases"] == 2
    assert agg["hit_rate"] == 0.5
    assert agg["mrr"] == 0.5
    assert agg["ndcg"] == 0.5


def test_aggregate_by_fatia_por_tag_e_conta_o_caso_em_cada_uma() -> None:
    resultados = [
        {"hit": True, "reciprocal_rank": 1.0, "ndcg": 1.0, "tags": ["rag", "grafo"]},
        {"hit": False, "reciprocal_rank": 0.0, "ndcg": 0.0, "tags": ["rag"]},
    ]
    por_tag = metrics.aggregate_by(resultados, "tags")
    assert por_tag["rag"]["cases"] == 2
    assert por_tag["rag"]["hit_rate"] == 0.5
    # Um caso com duas tags conta nas duas: a fatia responde "como está a
    # recuperação sobre grafo", não "quantos casos são exclusivamente grafo".
    assert por_tag["grafo"]["cases"] == 1
    assert por_tag["grafo"]["hit_rate"] == 1.0


def test_score_case_marca_todas_as_posicoes_relevantes() -> None:
    caso = EvalCase(
        source="context", query="q", expected_keywords=["alvo"], root="/tmp", tags=["x"]
    )
    hits = [("nada aqui", "a"), ("tem o ALVO", "b"), ("alvo de novo", "c")]

    resultado = score_case(hits, caso)

    assert resultado["hit"] is True
    assert resultado["rank"] == 2
    assert resultado["reciprocal_rank"] == 0.5
    assert resultado["relevant_hits"] == 2
    assert resultado["tags"] == ["x"]
    # Dois relevantes nas posições 2 e 3, ideal nas posições 1 e 2.
    assert 0 < resultado["ndcg"] < 1


def test_score_case_sem_acerto_zera_tudo() -> None:
    caso = EvalCase(source="notes", query="q", expected_keywords=["alvo"])
    resultado = score_case([("nada", "a")], caso)

    assert resultado["hit"] is False
    assert resultado["rank"] is None
    assert resultado["reciprocal_rank"] == 0.0
    assert resultado["ndcg"] == 0.0
