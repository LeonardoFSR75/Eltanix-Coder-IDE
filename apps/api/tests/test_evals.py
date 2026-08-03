"""Só a lógica de score (hit@k / MRR) — busca real precisa de Postgres+pgvector
e fica fora do pytest padrão (ver `sicoobito-eval-rag` para a execução ponta-a-ponta)."""

from __future__ import annotations

from sicoobito.evals.dataset import EvalCase
from sicoobito.evals.runner import score_case


def _case(**kwargs) -> EvalCase:
    kwargs.setdefault("source", "documents")
    kwargs.setdefault("query", "consulta de teste")
    return EvalCase(**kwargs)


def test_hit_by_keyword_at_first_rank():
    case = _case(expected_keywords=["reciprocal"])
    hits = [("Explica o Reciprocal Rank Fusion.", "doc1#0"), ("Outro conteúdo.", "doc1#1")]

    result = score_case(hits, case)

    assert result["hit"] is True
    assert result["rank"] == 1
    assert result["reciprocal_rank"] == 1.0


def test_hit_by_id_at_second_rank():
    case = _case(expected_ids=["doc1#1"])
    hits = [("Irrelevante.", "doc1#0"), ("O que importa.", "doc1#1")]

    result = score_case(hits, case)

    assert result["hit"] is True
    assert result["rank"] == 2
    assert result["reciprocal_rank"] == 0.5


def test_no_hit_when_nothing_matches():
    case = _case(expected_keywords=["inexistente"])
    hits = [("Nada a ver.", "doc1#0")]

    result = score_case(hits, case)

    assert result["hit"] is False
    assert result["rank"] is None
    assert result["reciprocal_rank"] == 0.0


def test_no_hit_on_empty_results():
    case = _case(expected_keywords=["qualquer"])
    result = score_case([], case)
    assert result["hit"] is False
    assert result["reciprocal_rank"] == 0.0


def test_case_requires_keywords_or_ids():
    import pytest

    with pytest.raises(ValueError):
        _case()


def test_context_source_requires_root():
    import pytest

    with pytest.raises(ValueError):
        _case(source="context", expected_keywords=["x"])
