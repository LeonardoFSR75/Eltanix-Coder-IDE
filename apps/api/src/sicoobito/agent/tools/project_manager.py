"""Ferramenta de gestão e inspeção de projetos para o Agente."""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.db.session import session_scope
from sicoobito.workspace.projects import (
    ProjectError,
    get_project_summary,
)
from sicoobito.workspace.projects import (
    list_projects as list_disk_projects,
)


@tool(
    name="manage_project",
    description=(
        "Consulte, liste ou inspecione o resumo consolidado 360° do projeto (métricas de "
        "Git, IDE, custos de LLM $, notas do Segundo Cérebro, nós do Graphify e auditoria). "
        "Permite ao agente compreender o estado global e governança do projeto atual."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["summary", "list"],
                "description": "'summary' para obter a métrica 360° de um projeto ou 'list' para listar todos os projetos.",
            },
            "project_slug": {
                "type": "string",
                "description": "Slug/nome do projeto (opcional se action='list'; usa o projeto da sessão por padrão)",
            },
        },
        "required": ["action"],
    },
    summarize=lambda a: f"projeto ({a.get('action')}, slug={a.get('project_slug')})",
)
async def manage_project(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    action = args.get("action", "summary")
    slug = args.get("project_slug") or ctx.project

    if action == "list":
        projects = list_disk_projects(ctx.projects_root)
        items = [{"slug": p.slug or p.name, "name": p.name, "is_git": p.is_git, "branch": p.branch} for p in projects]
        return ToolResult(
            ok=True,
            content=f"Encontrados {len(items)} projetos disponíveis.",
            data={"projects": items},
        )

    if not slug:
        return ToolResult.failure("Nenhum project_slug fornecido nem detectado na sessão.")

    async with session_scope() as session:
        try:
            summary = await get_project_summary(session, slug, ctx.projects_root)
            data = {
                "slug": summary.slug,
                "name": summary.name,
                "description": summary.description,
                "local_path": summary.local_path,
                "git": {"is_git": summary.is_git, "branch": summary.branch, "remote_url": summary.git_url},
                "costs": {
                    "total_usd": summary.total_cost_usd,
                    "budget_limit_usd": summary.budget_limit_usd,
                    "total_tokens": summary.total_tokens,
                },
                "second_brain": {"notes_count": summary.notes_count},
                "graphify": {
                    "nodes_count": summary.graph_nodes_count,
                    "edges_count": summary.graph_edges_count,
                },
                "audit": {"events_count": summary.audit_events_count},
                "sessions": {"active_count": summary.active_sessions_count},
                "settings": summary.settings,
            }
            content_str = (
                f"=== Resumo do Projeto {summary.name} ({summary.slug}) ===\n"
                f"Caminho: {summary.local_path}\n"
                f"Git: Branch={summary.branch or 'N/A'}\n"
                f"Custos: ${summary.total_cost_usd:.4f} USD (Orçamento: {summary.budget_limit_usd or 'Sem limite'})\n"
                f"Tokens Consumidos: {summary.total_tokens:,}\n"
                f"Segundo Cérebro: {summary.notes_count} nota(s)\n"
                f"Graphify: {summary.graph_nodes_count} nó(s) | {summary.graph_edges_count} aresta(s)\n"
                f"Eventos de Auditoria: {summary.audit_events_count}\n"
                f"Sessões Ativas: {summary.active_sessions_count}\n"
            )
            return ToolResult(ok=True, content=content_str, data=data)
        except ProjectError as exc:
            return ToolResult.failure(f"Erro ao obter resumo do projeto: {exc}")
