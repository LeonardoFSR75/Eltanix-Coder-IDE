"""Ferramenta de gestão e inspeção de projetos para o Agente."""

from __future__ import annotations

from typing import Any

from novaai_studio.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from novaai_studio.db.session import session_scope
from novaai_studio.workspace.projects import (
    ProjectError,
    get_project_summary,
)
from novaai_studio.workspace.projects import (
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
                "description": (
                    "'summary' para métrica 360° do projeto ou 'list' para listar os projetos."
                ),
            },
            "project_slug": {
                "type": "string",
                "description": (
                    "Slug/nome do projeto (opcional se action='list'; usa o projeto da sessão"
                    " por padrão)"
                ),
            },
        },
        "required": ["action"],
    },
    summarize=lambda a: f"projeto ({a.get('action')}, slug={a.get('project_slug')})",
)
async def manage_project(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    action = args.get("action", "summary")
    slug = args.get("project_slug") or ctx.project_slug

    if action == "list":
        projects = list_disk_projects(ctx.projects_root)
        items = [
            {"slug": p.slug or p.name, "name": p.name, "is_git": p.is_git, "branch": p.branch}
            for p in projects
        ]
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
                "git": {
                    "is_git": summary.is_git,
                    "branch": summary.branch,
                    "remote_url": summary.git_url,
                },
                "costs": {
                    "total_usd": summary.total_cost_usd,
                    "budget_limit_usd": summary.budget_limit_usd,
                    "total_tokens": summary.total_tokens,
                },
                "second_brain": {"notes_count": summary.notes_count},
                "documents": {"count": summary.documents_count},
                "graphify": {
                    "nodes_count": summary.graph_nodes_count,
                    "edges_count": summary.graph_edges_count,
                },
                "audit": {"events_count": summary.audit_events_count},
                "sessions": {"active_count": summary.active_sessions_count},
                "recent_commits": summary.recent_commits,
                "settings": summary.settings,
            }
            budget_str = summary.budget_limit_usd or "Sem limite"
            graph_info = f"{summary.graph_nodes_count} nós | {summary.graph_edges_count} arestas"
            content_str = (
                f"=== Resumo do Projeto {summary.name} ({summary.slug}) ===\n"
                f"Caminho: {summary.local_path}\n"
                f"Git: Branch={summary.branch or 'N/A'}\n"
                f"Custos: ${summary.total_cost_usd:.4f} USD (Orçamento: {budget_str})\n"
                f"Tokens Consumidos: {summary.total_tokens:,}\n"
                f"Segundo Cérebro: {summary.notes_count} nota(s)\n"
                f"Documentos: {summary.documents_count}\n"
                f"Graphify: {graph_info}\n"
                f"Eventos de Auditoria: {summary.audit_events_count}\n"
                f"Sessões Ativas: {summary.active_sessions_count}\n"
                f"Commits recentes: {len(summary.recent_commits)}\n"
            )
            return ToolResult(ok=True, content=content_str, data=data)
        except ProjectError as exc:
            return ToolResult.failure(f"Erro ao obter resumo do projeto: {exc}")
