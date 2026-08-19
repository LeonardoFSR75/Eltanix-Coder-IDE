"""Ferramenta de plano/checklist do agente.

Sem isto, "Modo Planejar" produzia só um parágrafo de texto que ninguém
conseguia acompanhar turno a turno. `write_todos` é `RiskClass.READ` na
maioria das chamadas — não toca em arquivo nenhum, então o modelo pode
atualizar a lista livremente a cada turno, sem fricção de aprovação.

**Exceção (Fase 3 do upgrade do agente, estilo Antigravity)**: em modo
`plan`/`orchestra`, a primeira chamada que de fato registra um plano (a
lista deixa de estar vazia) vira `RiskClass.WRITE` — o usuário revisa e
aprova o plano antes de qualquer ferramenta de escrita/execução ser
liberada, em vez de só confiar no texto do prompt pedindo isso. Ver
`_todos_risk` e `ToolContext.session_state.plan_registered`.
"""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool

_VALID_STATUS = {"pending", "in_progress", "completed"}
_GATED_MODES = {"plan", "orchestra"}


def _todos_risk(args: dict[str, Any], context: ToolContext | None) -> RiskClass:
    if context is None or context.mode not in _GATED_MODES:
        return RiskClass.READ
    if context.session_state.plan_registered:
        return RiskClass.READ
    itens = args.get("items") or []
    tem_conteudo = any(
        isinstance(item, dict) and str(item.get("content", "")).strip() for item in itens
    )
    return RiskClass.WRITE if tem_conteudo else RiskClass.READ


@tool(
    name="write_todos",
    description=(
        "Cria ou substitui o checklist de tarefas da sessão. Chame no início de uma "
        "tarefa com várias etapas e atualize os status conforme avança — a lista "
        "enviada substitui a anterior por completo, então reenvie todos os itens, "
        "não só os que mudaram de status."
    ),
    risk=_todos_risk,
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Descrição curta e concreta do passo",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["items"],
    },
    summarize=lambda a: f"atualizar plano ({len(a.get('items') or [])} itens)",
)
async def write_todos(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    brutos = args.get("items") or []
    todos: list[dict[str, Any]] = []
    rebaixados: list[str] = []
    concluidos_anteriores = {
        str(t.get("content", "")).strip()
        for t in (
            ctx.session_state.current_todos
            if hasattr(ctx, "session_state")
            else getattr(ctx, "current_todos", []) or []
        )
        if isinstance(t, dict) and t.get("status") == "completed"
    }
    for item in brutos:
        if not isinstance(item, dict):
            continue
        conteudo = str(item.get("content", "")).strip()
        if not conteudo:
            continue
        status = item.get("status")
        if status not in _VALID_STATUS:
            status = "pending"
        # A ferramenta WRITE/EXEC mais recente falhou e ainda não foi seguida
        # de um sucesso — não deixa o modelo marcar NOVO item como "completed" nessa hora
        # (instrução em prompts.py::SYSTEM_PROMPT já pedia isso em texto; aqui
        # é aplicado, não só sugerido). Ver `ToolContext.has_unresolved_failure`.
        # Itens já concluídos antes da falha permanecem concluídos.
        if (
            status == "completed"
            and ctx.has_unresolved_failure
            and conteudo not in concluidos_anteriores
        ):
            status = "in_progress"
            rebaixados.append(conteudo)
        todos.append({"content": conteudo, "status": status})

    # Chega aqui só depois de aprovado quando `_todos_risk` classificou esta
    # chamada como WRITE (a própria que registra o plano) — marca a sessão
    # para que nenhuma atualização seguinte do mesmo plano volte a pedir
    # aprovação, mesmo que a lista fique momentaneamente vazia no meio do
    # trabalho (ex: o modelo reenvia a lista inteira num estado intermediário).
    if ctx.mode in _GATED_MODES and todos and not ctx.session_state.plan_registered:
        ctx.session_state.plan_registered = True

    resumo = "\n".join(f"[{t['status']}] {t['content']}" for t in todos) or "(lista vazia)"
    aviso = ""
    if rebaixados:
        itens = "; ".join(rebaixados)
        aviso = (
            f"\n\nAVISO: {len(rebaixados)} item(ns) mantido(s) em `in_progress` em vez de "
            f"`completed` porque a última ferramenta WRITE/EXEC falhou e ainda não foi "
            f"seguida de um sucesso ({itens}). Corrija o problema (ou confirme com um "
            "comando que passe) antes de marcar como concluído."
        )
    return ToolResult(ok=True, content=f"Plano atualizado:\n{resumo}{aviso}", data={"todos": todos})
