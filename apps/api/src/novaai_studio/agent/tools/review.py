"""Revisão de código como segunda opinião — não o mesmo modelo se autoavaliando
na mesma conversa, mas uma chamada nova ao router, sem o histórico da sessão.

Usada pelo modo `orchestra` (ver `agent/prompts.py`), mas disponível em
qualquer modo que libere ferramentas de leitura — pedir uma revisão de
alterações feitas manualmente também é um uso legítimo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sicoobito.agent.review_common import request_review_verdict
from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError


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
        veredito = await request_review_verdict(
            ctx.engine, summary=resumo, diff=diff, source="agent:code_review",
            session_id=ctx.session_id,
        )
    except Exception as exc:
        return ToolResult.failure(f"Falha ao chamar o revisor: {exc}")

    if veredito.unparseable:
        # Fail closed: resposta fora do formato esperado nunca aprova por
        # omissão — mesmo espírito da recusa por omissão em graph.py::approve.
        return ToolResult(
            ok=False,
            content=(
                "O revisor não respondeu no formato esperado — tratando como "
                "PRECISA_REVISAO por segurança.\n\n" + veredito.text
            ),
            data={"verdict": "needs_revision"},
        )

    return ToolResult(
        ok=veredito.approved,
        content=veredito.text,
        data={"verdict": "approved" if veredito.approved else "needs_revision"},
    )
