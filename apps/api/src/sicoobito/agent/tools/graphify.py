"""Ferramentas de leitura do Grafo de Conhecimento do Graphify (Segundo Cérebro).

Não confundir com `agent/tools/graph.py` — aquele é o Code Knowledge Graph
(`context/edges.py`: imports, ciclos, módulo órfão), um grafo totalmente
diferente. Este fala com `graphify/store.py::GraphNode`/`GraphEdge` via
`GraphifyEngine`.
"""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.db.session import session_scope
from sicoobito.graphify.engine import MAX_MULTI_WORKSPACE_FANOUT, GraphifyEngine


def _format_result(result: dict[str, Any]) -> str:
    nodes = result.get("nodes") or []
    if not nodes:
        return "Nenhum nó encontrado no grafo de conhecimento para essa busca."
    linhas = [f"{len(nodes)} nó(s) encontrado(s):"]
    linhas.extend(
        f"  {n.get('entity_type', '?')} · {n.get('name', '?')}"
        + (f" — {n.get('summary')}" if n.get("summary") else "")
        for n in nodes
    )
    return "\n".join(linhas)


@tool(
    name="knowledge_graph_search",
    description=(
        "Busca no Grafo de Conhecimento (Graphify/Segundo Cérebro) do projeto atual — "
        "notas, conceitos e documentos conectados por wikilinks/tags/menções, com "
        "expansão multi-hop. Diferente de `code_graph`, que é sobre estrutura de código."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto da busca"},
            "top_k": {"type": "integer", "description": "Máximo de nós a retornar (padrão 10)"},
            "max_hops": {
                "type": "integer",
                "description": "Expansão do grafo em saltos (padrão 2)",
            },
        },
        "required": ["query"],
    },
    summarize=lambda a: f"buscar no grafo de conhecimento: {a.get('query', '')[:70]}",
)
async def knowledge_graph_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    workspace = ctx.project_slug or "default"
    async with session_scope() as session:
        engine = GraphifyEngine(session)
        result = await engine.search_graph_rag(
            args["query"],
            workspace=workspace,
            top_k=int(args.get("top_k") or 10),
            max_hops=int(args.get("max_hops") or 2),
        )
    return ToolResult(ok=True, content=_format_result(result), data=result)


@tool(
    name="knowledge_graph_search_cross_project",
    description=(
        "Busca no Grafo de Conhecimento através de VÁRIOS projetos ao mesmo tempo "
        "(até 10) — útil para achar entidades/conceitos compartilhados entre "
        "projetos diferentes. Cada projeto é buscado independentemente, sem "
        "ranking global entre eles (relevância não é comparável entre workspaces "
        "independentes)."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto da busca"},
            "workspaces": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Slugs dos projetos a buscar (máx. 10)",
            },
            "top_k": {"type": "integer", "description": "Máximo de nós por projeto (padrão 10)"},
            "max_hops": {
                "type": "integer",
                "description": "Expansão do grafo em saltos (padrão 2)",
            },
        },
        "required": ["query", "workspaces"],
    },
    summarize=lambda a: (
        f"buscar no grafo de conhecimento cross-project ({len(a.get('workspaces') or [])} "
        f"projetos): {a.get('query', '')[:50]}"
    ),
)
async def knowledge_graph_search_cross_project(
    ctx: ToolContext, args: dict[str, Any]
) -> ToolResult:
    workspaces = list(args.get("workspaces") or [])
    if not workspaces:
        return ToolResult.failure("Informe pelo menos um projeto em `workspaces`.")
    if len(workspaces) > MAX_MULTI_WORKSPACE_FANOUT:
        return ToolResult.failure(
            f"Máximo de {MAX_MULTI_WORKSPACE_FANOUT} projetos por busca cross-project."
        )

    async with session_scope() as session:
        engine = GraphifyEngine(session)
        results = await engine.search_multi_workspace(
            args["query"],
            workspaces,
            top_k=int(args.get("top_k") or 10),
            max_hops=int(args.get("max_hops") or 2),
        )

    if not results:
        return ToolResult(
            ok=True,
            content="Nenhum projeto respondeu à busca (ver logs para detalhes de falha).",
            data={"results": {}},
        )

    linhas = [f"Resultados de {len(results)} projeto(s):"]
    for workspace, result in results.items():
        linhas.append(f"\n## {workspace}")
        linhas.append(_format_result(result))
    return ToolResult(ok=True, content="\n".join(linhas), data={"results": results})
