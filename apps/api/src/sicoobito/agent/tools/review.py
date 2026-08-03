"""Revisão de código como segunda opinião — não o mesmo modelo se autoavaliando
na mesma conversa, mas uma chamada nova ao router, sem o histórico da sessão.

Usada pelo modo `orchestra` (ver `agent/prompts.py`), mas disponível em
qualquer modo que libere ferramentas de leitura — pedir uma revisão de
alterações feitas manualmente também é um uso legítimo.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.logging_setup import get_logger
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError

log = get_logger(__name__)

_REVIEW_SYSTEM_PROMPT = """Você é um revisor de código sênior, independente de quem \
escreveu a mudança. Receberá um resumo do que foi implementado e o diff correspondente.

Avalie: a mudança faz o que o resumo diz, sem quebrar nada óbvio? Há cobertura de teste \
para o comportamento novo? Há complexidade ou efeito colateral desnecessário?

Responda EXATAMENTE neste formato, começando pela primeira linha:
VEREDITO: APROVADO
ou
VEREDITO: PRECISA_REVISAO

seguido de um parágrafo curto explicando a decisão. Se pedir revisão, seja específico \
sobre o que precisa mudar — quem vai ler não tem mais contexto que o diff em mãos."""

_VERDICT_RE = re.compile(r"^VEREDITO:\s*(APROVADO|PRECISA_REVISAO)", re.IGNORECASE)


@tool(
    name="request_code_review",
    description=(
        "Pede uma revisão independente das alterações não commitadas — uma segunda "
        "chamada de modelo, sem o histórico desta conversa, que aprova ou pede ajustes. "
        "Use antes de commitar cada etapa do plano."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "O que foi implementado nesta etapa, para dar contexto ao revisor",
            }
        },
        "required": ["summary"],
    },
    summarize=lambda a: f"pedir revisão: {a.get('summary', '')[:70]}",
)
async def request_code_review(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.engine is None:
        return ToolResult.failure("Revisão indisponível: router não conectado a esta sessão.")

    try:
        diff = git_ops.diff(Path(ctx.workspace_root), staged=False)
    except GitError as exc:
        return ToolResult.failure(str(exc))

    if not diff:
        return ToolResult.failure(
            "Nada para revisar ainda — não há alterações não commitadas no worktree."
        )

    resumo = args.get("summary", "")
    try:
        resultado = await ctx.engine.complete(
            requested_model="coding",
            params={
                "messages": [
                    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Resumo: {resumo}\n\nDiff:\n{diff}"},
                ],
                "temperature": 0,
            },
            source="agent:code_review",
        )
    except Exception as exc:
        return ToolResult.failure(f"Falha ao chamar o revisor: {exc}")

    escolha = (resultado.payload.get("choices") or [{}])[0]
    texto = (escolha.get("message") or {}).get("content") or ""

    match = _VERDICT_RE.match(texto.strip())
    if match is None:
        # Fail closed: resposta fora do formato esperado nunca aprova por
        # omissão — mesmo espírito da recusa por omissão em graph.py::approve.
        log.warning("agent.code_review.unparseable", preview=texto[:200])
        return ToolResult(
            ok=False,
            content=(
                "O revisor não respondeu no formato esperado — tratando como "
                "PRECISA_REVISAO por segurança.\n\n" + texto
            ),
            data={"verdict": "needs_revision"},
        )

    aprovado = match.group(1).upper() == "APROVADO"
    return ToolResult(
        ok=aprovado,
        content=texto,
        data={"verdict": "approved" if aprovado else "needs_revision"},
    )
