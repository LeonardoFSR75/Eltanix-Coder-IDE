"""Ferramentas de leitura do Grafo de Conhecimento (Graphify) — só a parte
que não toca banco: formatação e guardas de validação. A busca de verdade
(via `GraphifyEngine`) já é coberta em `test_graphify.py`.
"""

from __future__ import annotations

from eltanix.agent.tools import graphify

_format_result = graphify._format_result
knowledge_graph_search_cross_project = graphify.knowledge_graph_search_cross_project.handler


def test_format_result_empty():
    assert "Nenhum" in _format_result({"nodes": []})


def test_format_result_lists_nodes():
    result = _format_result(
        {
            "nodes": [
                {"entity_type": "Note", "name": "Autenticação", "summary": "Fluxo de login"},
                {"entity_type": "Concept", "name": "RAG"},
            ]
        }
    )
    assert "Autenticação" in result
    assert "Fluxo de login" in result
    assert "RAG" in result


async def test_cross_project_search_rejects_empty_workspaces():
    resultado = await knowledge_graph_search_cross_project(None, {"query": "x", "workspaces": []})
    assert resultado.ok is False
    assert "pelo menos um projeto" in resultado.content


async def test_cross_project_search_rejects_too_many_workspaces():
    workspaces = [f"projeto-{i}" for i in range(15)]
    resultado = await knowledge_graph_search_cross_project(
        None, {"query": "x", "workspaces": workspaces}
    )
    assert resultado.ok is False
    assert "Máximo" in resultado.content
