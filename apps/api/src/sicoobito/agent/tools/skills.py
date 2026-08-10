"""Ferramentas de skills — deixam o agente descobrir e aplicar convenções da
casa sozinho, em vez de depender só do usuário escolher um preset na UI."""

from __future__ import annotations

import uuid
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


@tool(
    name="list_skills",
    description=(
        "Lista as skills (presets de prompt de sistema) cadastradas e habilitadas pelo "
        "usuário. Use para descobrir se existe uma convenção ou rotina já registrada "
        "antes de decidir como abordar a tarefa."
    ),
    risk=RiskClass.READ,
    parameters={"type": "object", "properties": {}},
    summarize=lambda a: "listar skills disponíveis",
)
async def list_skills(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.skills is None:
        return ToolResult.failure("Skills indisponíveis.")

    skills = await ctx.skills.list_all(only_enabled=True)
    if not skills:
        return ToolResult(ok=True, content="Nenhuma skill cadastrada.", data={"skills": []})

    linhas = [f"- {s.id} · {s.name} ({s.category}): {s.description}" for s in skills]
    return ToolResult(
        ok=True,
        content="\n".join(linhas),
        data={
            "skills": [{"id": str(s.id), "name": s.name, "category": s.category} for s in skills]
        },
    )


@tool(
    name="get_skill",
    description=(
        "Busca o system_prompt e os parâmetros completos de uma skill pelo id (obtido "
        "via list_skills). Use o resultado para orientar sua própria resposta ou ação."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {"type": "string", "description": "id retornado por list_skills"}
        },
        "required": ["skill_id"],
    },
    summarize=lambda a: f"ler skill {a.get('skill_id')}",
)
async def get_skill(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.skills is None:
        return ToolResult.failure("Skills indisponíveis.")

    try:
        skill_id = uuid.UUID(args["skill_id"])
    except (KeyError, ValueError):
        return ToolResult.failure("skill_id inválido.")

    skill = await ctx.skills.get_and_record_usage(skill_id)
    if skill is None:
        return ToolResult.failure("Skill não encontrada.")

    content = (
        f"System prompt de {skill.name!r}:\n\n{skill.system_prompt}\n\n"
        f"Parâmetros: {skill.parameters_json}"
    )
    return ToolResult(
        ok=True,
        content=content,
        data={"id": str(skill.id), "name": skill.name, "system_prompt": skill.system_prompt},
    )
