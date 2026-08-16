"""`request_review_verdict`: núcleo compartilhado da segunda opinião — extraído
de `agent/tools/review.py` para ser reaproveitado por `agent/graph.py`. Sem
Postgres/Redis, engine falso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sicoobito.agent.review_common import request_review_verdict


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)


class _FakeEngine:
    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source, session_id=None):
        self.chamadas.append(
            {"requested_model": requested_model, "params": params, "source": source}
        )
        return _FakeCompletionResult(payload={"choices": [{"message": {"content": self.resposta}}]})


async def test_approved_verdict():
    engine = _FakeEngine("VEREDITO: APROVADO\nTudo certo.")
    veredito = await request_review_verdict(
        engine, summary="corrige bug", diff="- a\n+ b", source="teste"
    )
    assert veredito.approved is True
    assert veredito.unparseable is False
    assert "Tudo certo" in veredito.text


async def test_needs_revision_verdict():
    engine = _FakeEngine("VEREDITO: PRECISA_REVISAO\nFalta teste.")
    veredito = await request_review_verdict(
        engine, summary="corrige bug", diff="- a\n+ b", source="teste"
    )
    assert veredito.approved is False
    assert veredito.unparseable is False


async def test_unparseable_response_maps_to_not_approved():
    engine = _FakeEngine("Parece bom.")
    veredito = await request_review_verdict(
        engine, summary="x", diff="diff", source="teste"
    )
    assert veredito.approved is False
    assert veredito.unparseable is True


async def test_calls_engine_with_isolated_messages_no_session_history():
    engine = _FakeEngine("VEREDITO: APROVADO\nok")
    await request_review_verdict(
        engine, summary="resumo x", diff="diff y", source="agent:pre_approval_review"
    )
    chamada = engine.chamadas[0]
    assert chamada["requested_model"] == "coding"
    assert chamada["source"] == "agent:pre_approval_review"
    mensagens = chamada["params"]["messages"]
    assert mensagens[0]["role"] == "system"
    assert "resumo x" in mensagens[1]["content"]
    assert "diff y" in mensagens[1]["content"]
