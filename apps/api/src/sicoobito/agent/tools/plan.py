"""Ferramenta de plano/checklist do agente.

Sem isto, "Modo Planejar" produzia só um parágrafo de texto que ninguém
conseguia acompanhar turno a turno. `write_todos` é `RiskClass.READ` de
propósito — não toca em arquivo nenhum, então o modelo pode atualizar a
lista livremente a cada turno, sem fricção de aprovação.
"""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool

_VALID_STATUS = {"pending", "in_progress", "completed"}


@tool(
    name="write_todos",
    description=(
        "Cria ou substitui o checklist de tarefas da sessão. Chame no início de uma "
        "tarefa com várias etapas e atualize os status conforme avança — a lista "
        "enviada substitui a anterior por completo, então reenvie todos os itens, "
        "não só os que mudaram de status."
    ),
    risk=RiskClass.READ,
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
async def write_todos(_ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    brutos = args.get("items") or []
    todos: list[dict[str, Any]] = []
    for item in brutos:
        if not isinstance(item, dict):
            continue
        conteudo = str(item.get("content", "")).strip()
        if not conteudo:
            continue
        status = item.get("status")
        if status not in _VALID_STATUS:
            status = "pending"
        todos.append({"content": conteudo, "status": status})

    resumo = "\n".join(f"[{t['status']}] {t['content']}" for t in todos) or "(lista vazia)"
    return ToolResult(ok=True, content=f"Plano atualizado:\n{resumo}", data={"todos": todos})
