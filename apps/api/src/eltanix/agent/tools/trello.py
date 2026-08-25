"""Ferramentas do Quadro Trello (Kanban por Projeto) — consulta e gravação real de tarefas."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from eltanix.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


@tool(
    name="trello_manage",
    description=(
        "Gerencia o Quadro Trello/Kanban do projeto em tempo real: cria novos cartões "
        "('create'), lista tarefas do quadro ('list'), move o status das tarefas ('move') "
        "ou exclui cartões ('delete'). Permite que o agente acompanhe o progresso das "
        "sprints e tarefas do projeto."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "move", "delete"],
                "description": "Ação a realizar no quadro Trello/Kanban do projeto",
            },
            "card_id": {"type": "string", "description": "ID do cartão (para move ou delete)"},
            "title": {
                "type": "string",
                "description": "Título do cartão (para create ou referência)",
            },
            "description": {"type": "string", "description": "Descrição detalhada da tarefa"},
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "review", "done"],
                "description": (
                    "Coluna/Status da tarefa: todo (A Fazer), in_progress (Em Progresso), "
                    "review (Em Revisão), done (Concluído)"
                ),
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Prioridade da tarefa",
            },
        },
        "required": ["action"],
    },
    summarize=lambda a: (
        f"trello: {a.get('action')} {a.get('title', '') or a.get('card_id', '')!r}".strip()
    ),
)
async def trello_manage(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from eltanix.api.routes.trello import load_kanban_cards, save_kanban_cards

    action = args["action"]
    project_path = Path(ctx.workspace_root)
    cards = load_kanban_cards(project_path)
    now = time.strftime("%Y-%m-%d %H:%M")

    if action == "list":
        status_filter = args.get("status")
        filtered_cards = [c for c in cards if not status_filter or c.get("status") == status_filter]
        count = len(filtered_cards)

        summary_lines = [
            f"=== Quadro Trello ({project_path.name}) ===",
            f"Total de Cartões: {count}",
        ]
        for c in filtered_cards:
            agent_tag = " [🤖 Agente]" if c.get("created_by_agent") else ""
            summary_lines.append(
                f"- [{c.get('id')}] [{c.get('status', 'todo').upper()}] {c.get('title')}"
                f"{agent_tag} (Prioridade: {c.get('priority')})"
            )

        return ToolResult(
            ok=True,
            content="\n".join(summary_lines),
            data={
                "project": project_path.name,
                "action": "list",
                "count": count,
                "cards": filtered_cards,
            },
        )

    elif action == "create":
        title = (args.get("title") or "Nova Tarefa").strip()
        desc = (args.get("description") or "").strip()
        status_val = args.get("status", "todo")
        priority_val = args.get("priority", "medium")

        card_id = f"card-{int(time.time() * 1000)}"
        new_card = {
            "id": card_id,
            "title": title,
            "description": desc,
            "status": status_val,
            "priority": priority_val,
            "created_at": now,
            "updated_at": now,
            "created_by_agent": True,
        }

        cards.append(new_card)
        save_kanban_cards(project_path, cards)

        return ToolResult(
            ok=True,
            content=(
                f"Cartão '{title}' [{card_id}] criado com sucesso na coluna "
                f"'{status_val}' (Prioridade: {priority_val})."
            ),
            data={"action": "create", "card": new_card},
        )

    elif action == "move":
        move_id = args.get("card_id")
        title = args.get("title")
        status_val = args.get("status", "in_progress")

        target = None
        for c in cards:
            if (move_id and c.get("id") == move_id) or (
                title and title.lower() in c.get("title", "").lower()
            ):
                target = c
                break

        if not target:
            return ToolResult.failure(
                f"Cartão não encontrado para mover (ID: {move_id}, Título: {title})."
            )

        old_status = target.get("status")
        target["status"] = status_val
        target["updated_at"] = now
        save_kanban_cards(project_path, cards)

        return ToolResult(
            ok=True,
            content=(
                f"Cartão '{target['title']}' [{target['id']}] movido de '{old_status}' "
                f"para '{status_val}'."
            ),
            data={"action": "move", "card": target},
        )

    elif action == "delete":
        del_id = args.get("card_id")
        title = args.get("title")

        new_cards = [
            c
            for c in cards
            if not (
                (del_id and c.get("id") == del_id)
                or (title and title.lower() in c.get("title", "").lower())
            )
        ]

        if len(new_cards) == len(cards):
            return ToolResult.failure(
                f"Cartão não encontrado para exclusão (ID: {del_id}, Título: {title})."
            )

        save_kanban_cards(project_path, new_cards)
        return ToolResult(
            ok=True,
            content="Cartão removido do Quadro Trello do projeto.",
            data={"action": "delete", "card_id": del_id},
        )

    return ToolResult.failure(f"Ação desconhecida: {action}")
