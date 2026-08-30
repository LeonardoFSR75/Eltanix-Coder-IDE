"""Métricas de qualidade de *geração* do RAG, no espírito do RAGAS
(`faithfulness` e `answer relevance`) — complementam o hit@k/MRR de
`runner.py`, que só mede *recuperação*.

Toda chamada de LLM passa pelo `RouterEngine` (ADR 0001), isolada do histórico
de qualquer sessão de agente — mesmo padrão de `agent/review_common.py`.

- **faithfulness**: quanto da resposta gerada é sustentado pelos trechos
  recuperados (0 = alucina tudo, 1 = tudo ancorado no contexto).
- **answer_relevance**: quanto a resposta de fato endereça a pergunta
  (0 = evasiva/fora do tópico, 1 = responde direto).

Parsing fail-closed: resposta do juiz fora do formato → score 0.0 e
`unparseable=True`, nunca uma exceção (igual `review_common`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine

log = get_logger(__name__)

# Mesmo perfil de modelo que a "segunda opinião" usa — ver review_common.py.
_JUDGE_MODEL = "coding"
_ANSWER_MODEL = "coding"

_ANSWER_SYSTEM = """Você responde perguntas sobre uma base de código APENAS com base nos \
trechos fornecidos. Se os trechos não contêm a resposta, diga "Não há informação suficiente \
nos trechos.". Não use conhecimento externo. Seja direto e curto."""

_JUDGE_SYSTEM = """Você é um avaliador rigoroso de respostas de RAG. Receberá uma PERGUNTA, \
uma RESPOSTA e os TRECHOS de contexto que a originaram.

Pontue de 0.0 a 1.0:
- "faithfulness": fração das afirmações da RESPOSTA que os TRECHOS sustentam. Se a resposta \
afirma algo que não está nos trechos, isso derruba a nota.
- "answer_relevance": o quanto a RESPOSTA endereça diretamente a PERGUNTA (ignore se está \
correta — só se é sobre o que foi perguntado).

Responda SOMENTE com um objeto JSON, sem cercas de código, exatamente:
{"faithfulness": <0..1>, "answer_relevance": <0..1>, "rationale": "<uma frase>"}"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(slots=True)
class GenerationScore:
    faithfulness: float
    answer_relevance: float
    rationale: str
    unparseable: bool = False


def _clamp01(value: object) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def build_answer_messages(query: str, context_blocks: list[str]) -> list[dict[str, str]]:
    contexto = "\n\n".join(f"[{i + 1}] {b}" for i, b in enumerate(context_blocks))
    return [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {"role": "user", "content": f"PERGUNTA: {query}\n\nTRECHOS:\n{contexto}"},
    ]


def build_judge_messages(
    query: str, answer: str, context_blocks: list[str]
) -> list[dict[str, str]]:
    contexto = "\n\n".join(f"[{i + 1}] {b}" for i, b in enumerate(context_blocks))
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": f"PERGUNTA: {query}\n\nRESPOSTA: {answer}\n\nTRECHOS:\n{contexto}",
        },
    ]


def parse_judge_response(text: str) -> GenerationScore:
    """Extrai o JSON `{faithfulness, answer_relevance, rationale}` — tolera a
    cerca ```json que o modelo às vezes adiciona mesmo instruído a não. Falha
    fechada: qualquer erro → notas 0.0 e `unparseable=True`."""
    limpo = _FENCE_RE.sub("", text or "").strip()
    try:
        data = json.loads(limpo)
        if not isinstance(data, dict):
            raise ValueError("resposta do juiz não é um objeto JSON")
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("evals.ragas.unparseable", error=str(exc), preview=(text or "")[:200])
        return GenerationScore(0.0, 0.0, (text or "")[:500], unparseable=True)
    return GenerationScore(
        faithfulness=_clamp01(data.get("faithfulness")),
        answer_relevance=_clamp01(data.get("answer_relevance")),
        rationale=str(data.get("rationale") or ""),
    )


async def _complete_text(
    engine: RouterEngine, *, model: str, messages: list[dict[str, str]], source: str
) -> str:
    resultado = await engine.complete(
        requested_model=model,
        params={"messages": messages, "temperature": 0},
        source=source,
    )
    escolha = (resultado.payload.get("choices") or [{}])[0]
    return (escolha.get("message") or {}).get("content") or ""


async def generate_answer(
    engine: RouterEngine, *, query: str, context_blocks: list[str], source: str = "eval"
) -> str:
    return await _complete_text(
        engine,
        model=_ANSWER_MODEL,
        messages=build_answer_messages(query, context_blocks),
        source=source,
    )


async def judge_generation(
    engine: RouterEngine,
    *,
    query: str,
    answer: str,
    context_blocks: list[str],
    source: str = "eval",
) -> GenerationScore:
    texto = await _complete_text(
        engine,
        model=_JUDGE_MODEL,
        messages=build_judge_messages(query, answer, context_blocks),
        source=source,
    )
    return parse_judge_response(texto)


async def score_generation(
    engine: RouterEngine, *, query: str, context_blocks: list[str], source: str = "eval"
) -> tuple[str, GenerationScore]:
    """Gera a resposta a partir dos trechos e a julga. Devolve `(resposta, notas)`."""
    answer = await generate_answer(
        engine, query=query, context_blocks=context_blocks, source=source
    )
    score = await judge_generation(
        engine, query=query, answer=answer, context_blocks=context_blocks, source=source
    )
    return answer, score
