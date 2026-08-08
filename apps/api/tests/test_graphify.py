"""Testes unitários para o Módulo Graphify (Store, Indexer, RAG e Router)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sicoobito.graphify.schema import GraphEdgeCreate, GraphNodeCreate
from sicoobito.graphify.store import GraphStore
from sicoobito.graphify.pipeline.l1_wikilinks import extract_wikilinks, extract_tags, extract_python_imports


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


def test_graph_store_crud(pg_session: Session):
    store = GraphStore(pg_session)
    
    node1 = store.upsert_node(
        GraphNodeCreate(
            workspace="test",
            entity_type="Note",
            name="Nota A",
            canonical_id="note:Nota A",
            summary="Resumo da Nota A",
        )
    )
    assert node1.id is not None

    node2 = store.upsert_node(
        GraphNodeCreate(
            workspace="test",
            entity_type="Note",
            name="Nota B",
            canonical_id="note:Nota B",
            summary="Resumo da Nota B",
        )
    )

    edge = store.add_edge(
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

    nodes, edges = store.get_ego_subgraph(node1.id, max_hops=1)
    assert len(nodes) == 2
    assert len(edges) == 1

    metrics = store.compute_metrics("test")
    assert metrics["total_nodes"] == 2
    assert metrics["total_edges"] == 1
    assert metrics["orphan_nodes_count"] == 0
