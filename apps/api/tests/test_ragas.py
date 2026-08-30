"""Parte pura das métricas de geração do RAG (`evals/ragas.py`) — parsing do
juiz e montagem dos prompts. A execução ponta-a-ponta (juiz LLM real) fica no
`eltanix-eval-rag --judge`, fora do pytest."""

from __future__ import annotations

from eltanix.evals.ragas import (
    build_answer_messages,
    build_judge_messages,
    parse_judge_response,
)


def test_parse_plain_json():
    score = parse_judge_response(
        '{"faithfulness": 0.8, "answer_relevance": 1.0, "rationale": "ok"}'
    )
    assert score.faithfulness == 0.8
    assert score.answer_relevance == 1.0
    assert score.rationale == "ok"
    assert score.unparseable is False


def test_parse_tolerates_json_code_fence():
    raw = '```json\n{"faithfulness": 0.5, "answer_relevance": 0.5, "rationale": "x"}\n```'
    score = parse_judge_response(raw)
    assert score.faithfulness == 0.5
    assert score.unparseable is False


def test_parse_clamps_out_of_range_scores():
    score = parse_judge_response(
        '{"faithfulness": 1.7, "answer_relevance": -0.3, "rationale": ""}'
    )
    assert score.faithfulness == 1.0
    assert score.answer_relevance == 0.0


def test_parse_fails_closed_on_garbage():
    score = parse_judge_response("desculpe, não consegui avaliar")
    assert score.unparseable is True
    assert score.faithfulness == 0.0
    assert score.answer_relevance == 0.0
    assert "desculpe" in score.rationale


def test_parse_fails_closed_on_non_object_json():
    score = parse_judge_response("[1, 2, 3]")
    assert score.unparseable is True


def test_parse_missing_keys_default_to_zero():
    score = parse_judge_response('{"rationale": "faltando notas"}')
    assert score.faithfulness == 0.0
    assert score.answer_relevance == 0.0
    assert score.unparseable is False  # é um objeto JSON válido, só incompleto


def test_answer_messages_carry_query_and_numbered_context():
    msgs = build_answer_messages("como funciona X?", ["trecho A", "trecho B"])
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "como funciona X?" in user
    assert "[1] trecho A" in user and "[2] trecho B" in user


def test_judge_messages_carry_query_answer_and_context():
    msgs = build_judge_messages("q?", "resposta gerada", ["ctx1"])
    user = msgs[1]["content"]
    assert "q?" in user and "resposta gerada" in user and "[1] ctx1" in user
