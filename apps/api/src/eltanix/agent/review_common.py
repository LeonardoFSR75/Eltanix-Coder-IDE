"""Núcleo compartilhado da "segunda opinião": uma chamada de LLM isolada (sem
o histórico da conversa principal) que aprova ou pede revisão de um diff.

Duas features usam isto:
- `agent/tools/review.py::request_code_review` — o agente PEDE isso,
  voluntariamente, sobre um diff git de alterações já no worktree.
- `agent/graph.py::_attach_review_notes` — chamado automaticamente ANTES da
  aprovação humana, sobre um diff PROPOSTO (nada escrito ainda), só quando o
  projeto liga `second_opinion` em `.eltanix/approval_policy.yaml`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eltanix.logging_setup import get_logger
from eltanix.router.engine import RouterEngine

log = get_logger(__name__)

REVIEW_SYSTEM_PROMPT = """Você é um revisor de código sênior rigoroso e independente. \
Receberá um resumo do que foi implementado e o diff correspondente.

Avalie com atenção aos seguintes critérios:
1. **Completude (Zero Stubs / Zero Placeholders)**: A mudança está completamente implementada? \
Há código solto com `pass`, `// TODO`, métodos não implementados ou rascunhos? Se houver stubs, rejeite.
2. **Correção & Regressão**: O código cumpre exatamente o que o resumo promete sem quebrar contratos, \
APIs ou comportamentos existentes?
3. **Qualidade & Robustez**: Há tratamento adequado de erros, validação de tipos/schemas e boas práticas de segurança?
4. **Testes & Verificabilidade**: Há cobertura de testes para os novos fluxos de execução e cenários de borda?

Responda EXATAMENTE neste formato, começando pela primeira linha:
VEREDITO: APROVADO
ou
VEREDITO: PRECISA_REVISAO

seguido de um parágrafo objetivo explicando a decisão. Se pedir revisão, seja específico \
sobre o que precisa mudar — quem vai ler não tem mais contexto que o diff em mãos."""

_VERDICT_RE = re.compile(r"^VEREDITO:\s*(APROVADO|PRECISA_REVISAO)", re.IGNORECASE)


@dataclass(slots=True)
class ReviewVerdict:
    approved: bool
    text: str
    # True quando a resposta não seguiu o formato `VEREDITO: ...` esperado —
    # `approved` já vem False nesse caso (fail closed), mas o chamador pode
    # querer avisar diferente de um PRECISA_REVISAO de verdade.
    unparseable: bool = False


async def request_review_verdict(
    engine: RouterEngine, *, summary: str, diff: str, source: str, session_id: str | None = None
) -> ReviewVerdict:
    """Uma chamada isolada ao router — não recebe nem contamina o histórico
    da sessão principal. Levanta só se `engine.complete()` levantar (falha de
    rede/modelo); resposta fora do formato esperado NÃO é exceção, mapeia
    para `approved=False` (mesmo espírito de `graph.py::approve` recusar por
    omissão em vez de aprovar por adivinhação)."""
    resultado = await engine.complete(
        requested_model="coding",
        params={
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": f"Resumo: {summary}\n\nDiff:\n{diff}"},
            ],
            "temperature": 0,
        },
        source=source,
        session_id=session_id,
    )

    escolha = (resultado.payload.get("choices") or [{}])[0]
    texto = (escolha.get("message") or {}).get("content") or ""

    match = _VERDICT_RE.match(texto.strip())
    if match is None:
        log.warning("agent.review.unparseable", source=source, preview=texto[:200])
        return ReviewVerdict(approved=False, text=texto, unparseable=True)

    aprovado = match.group(1).upper() == "APROVADO"
    return ReviewVerdict(approved=aprovado, text=texto)
