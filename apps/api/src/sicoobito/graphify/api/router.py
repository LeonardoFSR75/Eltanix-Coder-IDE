"""Endpoints FastAPI para o Módulo Graphify (/api/graphify/*)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from sicoobito.api.deps import DbSessionDep, SettingsDep
from sicoobito.graphify.metrics.analytics import GraphAnalytics
from sicoobito.graphify.pipeline.indexer import GraphIndexer
from sicoobito.graphify.rag.graph_rag import GraphRAGQueryEngine
from sicoobito.graphify.schema import (
    GraphMetricsSummary,
    GraphNodeRead,
    GraphRAGQueryRequest,
    GraphRAGResult,
    SubgraphResponse,
)
from sicoobito.graphify.store import GraphStore

router = APIRouter(prefix="/api/graphify", tags=["graphify"])


@router.post("/index", response_model=dict[str, Any])
async def index_content(
    payload: dict[str, Any],
    db: DbSessionDep,
    settings: SettingsDep,
):
    """Indexa uma nota, documento, arquivo ou diretório inteiro no Grafo de Conhecimento."""
    store = GraphStore(db)
    indexer = GraphIndexer(store)

    content = payload.get("content")
    scan_requested = payload.get("scan_workspace") or not content

    if scan_requested:
        workspace_name = payload.get("workspace", "default")
        project_name = payload.get("project") or "SicoobitoCode"

        root = settings.effective_projects_root
        if root and (root / project_name).exists():
            target_path = root / project_name
        elif root and root.exists():
            target_path = root
        else:
            target_path = Path("/projects") / project_name

        if target_path.exists():
            result = await indexer.index_directory(target_path, workspace=workspace_name)
            await db.commit()
            return result

    source_type = payload.get("source_type", "note")
    result = await indexer.run_pipeline(source_type, payload)
    await db.commit()
    return result


@router.post("/query", response_model=GraphRAGResult)
async def query_graph_rag(req: GraphRAGQueryRequest, db: DbSessionDep):
    """Executa busca GraphRAG combinando RRF e expansão multi-hop de grafos."""
    store = GraphStore(db)
    rag_engine = GraphRAGQueryEngine(store)
    return await rag_engine.search(
        query=req.query,
        workspace=req.workspace,
        top_k=req.top_k,
        max_hops=req.max_hops,
    )


@router.get("/nodes", response_model=list[GraphNodeRead])
async def list_workspace_nodes(
    db: DbSessionDep,
    workspace: str = Query("default"),
    limit: int = Query(100, ge=1, le=500),
):
    """Lista todos os nós do grafo em um determinado workspace."""
    store = GraphStore(db)
    nodes = await store.get_workspace_nodes(workspace=workspace, limit=limit)
    return [
        GraphNodeRead(
            id=n.id,
            workspace=n.workspace,
            entity_type=n.entity_type,
            name=n.name,
            canonical_id=n.canonical_id,
            properties=n.properties,
            summary=n.summary,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes
    ]


@router.get("/edges")
async def list_workspace_edges(
    db: DbSessionDep,
    workspace: str = Query("default"),
    limit: int = Query(500, ge=1, le=2000),
):
    """Lista todas as arestas/conexões do grafo em um determinado workspace."""
    store = GraphStore(db)
    edges = await store.get_workspace_edges(workspace=workspace, limit=limit)
    return [
        {
            "id": str(e.id),
            "workspace": e.workspace,
            "source_id": str(e.source_id),
            "target_id": str(e.target_id),
            "relation_type": e.relation_type,
            "layer": e.layer,
            "weight": float(e.weight),
            "evidence": e.evidence,
        }
        for e in edges
    ]


@router.get("/nodes/{node_id}/ego", response_model=SubgraphResponse)
async def get_ego_subgraph(
    node_id: UUID,
    db: DbSessionDep,
    workspace: str = Query("default"),
    max_hops: int = Query(2, ge=1, le=4),
):
    """Retorna o subgrafo ego de vizinhança a N hops a partir de um nó."""
    store = GraphStore(db)
    nodes, edges = await store.get_ego_subgraph(node_id, max_hops=max_hops)
    return SubgraphResponse(
        nodes=[
            GraphNodeRead(
                id=n.id,
                workspace=n.workspace,
                entity_type=n.entity_type,
                name=n.name,
                canonical_id=n.canonical_id,
                properties=n.properties,
                summary=n.summary,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
            for n in nodes
        ],
        edges=[
            {
                "id": e.id,
                "workspace": e.workspace,
                "source_id": e.source_id,
                "target_id": e.target_id,
                "relation_type": e.relation_type,
                "layer": e.layer,
                "weight": float(e.weight),
                "evidence": e.evidence,
                "edge_metadata": e.edge_metadata,
                "created_at": e.created_at,
            }
            for e in edges
        ],
    )


@router.get("/metrics", response_model=GraphMetricsSummary)
async def get_graph_metrics(
    db: DbSessionDep,
    workspace: str = Query("default"),
):
    """Calcula e retorna métricas de saúde, densidade e notas órfãs do grafo."""
    store = GraphStore(db)
    analytics = GraphAnalytics(store)
    res = await analytics.compute_all(workspace)
    await db.commit()

    nodes = await store.get_workspace_nodes(workspace, limit=5)
    hotspots = [
        GraphNodeRead(
            id=n.id,
            workspace=n.workspace,
            entity_type=n.entity_type,
            name=n.name,
            canonical_id=n.canonical_id,
            properties=n.properties,
            summary=n.summary,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes
    ]

    return GraphMetricsSummary(
        workspace=workspace,
        total_nodes=res["total_nodes"],
        total_edges=res["total_edges"],
        orphan_nodes_count=res["orphan_nodes_count"],
        orphan_percentage=res["orphan_percentage"],
        density=res["density"],
        top_hotspots=hotspots,
    )
