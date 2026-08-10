"""Testes unitários para o Módulo Graphify (Store, Indexer, RAG e Router)."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.graphify.api.router import _derive_workspace
from sicoobito.graphify.engine import MAX_MULTI_WORKSPACE_FANOUT, GraphifyEngine
from sicoobito.graphify.pipeline.l1_wikilinks import (
    extract_python_imports,
    extract_tags,
    extract_wikilinks,
)
from sicoobito.graphify.schema import GraphEdgeCreate, GraphNodeCreate
from sicoobito.graphify.store import GraphStore


def test_derive_workspace_defaults_to_project():
    assert _derive_workspace({"project": "meu-projeto"}) == "meu-projeto"


def test_derive_workspace_defaults_when_project_missing():
    assert _derive_workspace({}) == "SicoobitoCode"


def test_derive_workspace_accepts_matching_workspace():
    assert _derive_workspace({"project": "x", "workspace": "x"}) == "x"


def test_derive_workspace_rejects_mismatched_workspace():
    with pytest.raises(HTTPException) as exc_info:
        _derive_workspace({"project": "projeto-a", "workspace": "projeto-b"})
    assert exc_info.value.status_code == 400


def test_extract_wikilinks():
    content = "Esta nota conecta a [[Autenticação]] e [[RAG|Busca Híbrida]]."
    links = extract_wikilinks(content)
    assert links == ["Autenticação", "RAG"]


def test_extract_tags():
    content = "Assunto principal #pkm e #conhecimento-grafo."
    tags = extract_tags(content)
    assert tags == ["pkm", "conhecimento-grafo"]


def test_extract_python_imports():
    code = "import os\nfrom fastapi import FastAPI\nimport sicoobito.db"
    imports = extract_python_imports(code)
    assert "os" in imports
    assert "fastapi" in imports
    assert "sicoobito" in imports


async def test_graph_store_crud(pg_session: AsyncSession):
    store = GraphStore(pg_session)

    node1 = await store.upsert_node(
        GraphNodeCreate(
            workspace="test",
            entity_type="Note",
            name="Nota A",
            canonical_id="note:Nota A",
            summary="Resumo da Nota A",
        )
    )
    assert node1.id is not None

    node2 = await store.upsert_node(
        GraphNodeCreate(
            workspace="test",
            entity_type="Note",
            name="Nota B",
            canonical_id="note:Nota B",
            summary="Resumo da Nota B",
        )
    )

    edge = await store.add_edge(
        GraphEdgeCreate(
            workspace="test",
            source_id=node1.id,
            target_id=node2.id,
            relation_type="REFERENCIA",
            layer=1,
            weight=1.0,
            evidence="[[Nota B]]",
        )
    )
    assert edge.id is not None

    nodes, edges = await store.get_ego_subgraph(node1.id, workspace="test", max_hops=1)
    assert len(nodes) == 2
    assert len(edges) == 1

    metrics = await store.compute_metrics("test")
    assert metrics["total_nodes"] == 2
    assert metrics["total_edges"] == 1
    assert metrics["orphan_nodes_count"] == 0


async def test_get_ego_subgraph_does_not_leak_across_workspaces(pg_session: AsyncSession):
    # Dois projetos, cada um com seu próprio nó "raiz" de mesmo canonical_id
    # relativo — a CTE recursiva não pode atravessar de um workspace pro
    # outro mesmo que (hipoteticamente) houvesse uma edge cruzada.
    store = GraphStore(pg_session)

    node_a = await store.upsert_node(
        GraphNodeCreate(
            workspace="projeto-a",
            entity_type="Note",
            name="Raiz A",
            canonical_id="note:raiz",
        )
    )
    node_b = await store.upsert_node(
        GraphNodeCreate(
            workspace="projeto-b",
            entity_type="Note",
            name="Raiz B",
            canonical_id="note:raiz",
        )
    )

    # Pedir o ego-subgraph do nó de A usando o workspace de B não deve
    # encontrar nada — nem o próprio nó (id existe, mas não nesse workspace).
    nodes, edges = await store.get_ego_subgraph(node_a.id, workspace="projeto-b", max_hops=2)
    assert nodes == []
    assert edges == []

    # E pedindo com o workspace certo, encontra só o nó dele mesmo.
    nodes, edges = await store.get_ego_subgraph(node_a.id, workspace="projeto-a", max_hops=2)
    assert [n.id for n in nodes] == [node_a.id]

    nodes, edges = await store.get_ego_subgraph(node_b.id, workspace="projeto-b", max_hops=2)
    assert [n.id for n in nodes] == [node_b.id]


# ── GraphifyEngine.search_multi_workspace ────────────────────────────────────
#
# Orquestração pura (loop + try/except + teto de fan-out) — testada com
# `search_graph_rag` trocado por um fake, sem precisar de Postgres/RAG real.


def _engine_with_fake_search(monkeypatch, *, fails: set[str] = frozenset()):
    engine = GraphifyEngine.__new__(GraphifyEngine)  # sem tocar __init__/session

    async def _fake_search(query, workspace="default", top_k=10, max_hops=2):
        if workspace in fails:
            raise RuntimeError(f"busca falhou em {workspace}")
        return {"nodes": [{"name": f"{workspace}:{query}"}], "workspace": workspace}

    monkeypatch.setattr(engine, "search_graph_rag", _fake_search)
    return engine


async def test_search_multi_workspace_queries_each_workspace_independently(monkeypatch):
    engine = _engine_with_fake_search(monkeypatch)
    results = await engine.search_multi_workspace("teste", ["projeto-a", "projeto-b"])
    assert set(results.keys()) == {"projeto-a", "projeto-b"}
    assert results["projeto-a"]["nodes"][0]["name"] == "projeto-a:teste"


async def test_search_multi_workspace_omits_failed_workspace_without_raising(monkeypatch):
    engine = _engine_with_fake_search(monkeypatch, fails={"projeto-b"})
    results = await engine.search_multi_workspace("teste", ["projeto-a", "projeto-b"])
    assert set(results.keys()) == {"projeto-a"}


async def test_search_multi_workspace_caps_fanout(monkeypatch):
    engine = _engine_with_fake_search(monkeypatch)
    muitos = [f"projeto-{i}" for i in range(MAX_MULTI_WORKSPACE_FANOUT + 5)]
    results = await engine.search_multi_workspace("teste", muitos)
    assert len(results) == MAX_MULTI_WORKSPACE_FANOUT
