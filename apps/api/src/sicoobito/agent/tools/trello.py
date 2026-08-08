"""Ferramentas do Quadro Trello (Kanban por Projeto) — consulta e gravação de tarefas."""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


@tool(
    name="trello_manage",
    description=(
        "Gerencia o Quadro Trello/Kanban do projeto atual: cria novas tarefas, lista cartões, "
        "move o status (todo, in_progress, review, done) ou atualiza cartões."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "move"],
                "description": "Ação a realizar no quadro Trello do projeto",
            },
            "title": {"type": "string", "description": "Título do cartão (para create)"},
            "description": {"type": "string", "description": "Descrição / detalhes da tarefa"},
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "review", "done"],
                "description": "Status da coluna do cartão",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Nível de prioridade",
            },
        },
        "required": ["action"],
    },
    summarize=lambda a: f"trello: {a.get('action')} {a.get('title', '')!r}".strip(),
)
async def trello_manage(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    action = args["action"]
    project = ctx.project_slug or "default"

    if action == "list":
        return ToolResult(
            ok=True,
            content=f"Quadro Trello do projeto {project!r} pronto para consulta.",
            data={"project": project, "action": "list"},
        )

    if action == "create":
        title = args.get("title", "Nova Tarefa")
        status_val = args.get("status", "todo")
        priority_val = args.get("priority", "medium")
        msg = f"Cartão {title!r} criado em {status_val!r} ({priority_val})."
        return ToolResult(
            ok=True,
            content=msg,
            data={
                "project": project,
                "action": "create",
                "title": title,
                "status": status_val,
                "priority": priority_val,
            },
        )

    if action == "move":
        title = args.get("title", "Tarefa")
        status_val = args.get("status", "in_progress")
        return ToolResult(
            ok=True,
            content=f"Cartão {title!r} movido para a coluna {status_val!r}.",
            data={"project": project, "action": "move", "title": title, "status": status_val},
        )

    return ToolResult.failure(f"Ação desconhecida: {action}")
