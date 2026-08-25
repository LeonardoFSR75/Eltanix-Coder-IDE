"""Endpoints FastAPI para o Módulo Graphify (/api/graphify/*)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from sicoobito.api.deps import AuthDep, DbSessionDep, SettingsDep
from sicoobito.graphify.engine import GraphifyEngine
from sicoobito.graphify.metrics.analytics import GraphAnalytics
from sicoobito.graphify.pipeline.indexer import GraphIndexer
from sicoobito.graphify.rag.graph_rag import GraphRAGQueryEngine
from sicoobito.graphify.schema import (
    GraphMetricsSummary,
    GraphNodeRead,
    GraphRAGQueryRequest,
    GraphRAGResult,
    MultiWorkspaceQueryRequest,
    SubgraphResponse,
)
from sicoobito.graphify.store import GraphStore
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.projects import ProjectError, ensure_project_slug_exists

router = APIRouter(prefix="/api/graphify", tags=["graphify"], dependencies=[AuthDep])


def _resolve_scan_target(root: Path | None, project_name: str) -> Path | None:
    """Resolve o alvo de scan sempre dentro de uma raiz conhecida — nunca
    aceita `project_name` como caminho literal (evita path traversal)."""
    candidate_roots = [r for r in (root, Path("/projects")) if r is not None]
    for candidate_root in candidate_roots:
        if not candidate_root.exists():
            continue
        try:
            return project_ops.resolve(candidate_root, project_name)
        except ProjectError:
            continue
    # Nenhum projeto com esse nome — como fallback, escaneia a raiz inteira
    # (comportamento anterior), nunca um caminho derivado do input do usuário.
    if root and root.exists():
        return root
    return None


def _derive_workspace(payload: dict[str, Any]) -> str:
    """`workspace` é sempre derivado de `project` — não são campos
    independentes. Sem essa checagem, um caller poderia escanear os arquivos
    do projeto A para dentro do workspace do projeto B, corrompendo o grafo
    de B. Levanta 400 se o caller mandar um `workspace` explícito que diverge
    do `project` (em vez de sobrescrever silenciosamente)."""
    project_name = payload.get("project") or "SicoobitoCode"
    requested_workspace = payload.get("workspace")
    if requested_workspace and requested_workspace != project_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"workspace ({requested_workspace!r}) deve ser igual a project "
                f"({project_name!r}) — o workspace é sempre derivado do projeto."
            ),
        )
    return project_name


@router.post("/index", response_model=dict[str, Any])
async def index_content(
    payload: dict[str, Any],
    db: DbSessionDep,
    settings: SettingsDep,
):
    """Indexa uma nota, documento, arquivo ou diretório inteiro no Grafo de Conhecimento."""
    store = GraphStore(db)
    indexer = GraphIndexer(store)

    project_name = _derive_workspace(payload)
    workspace_name = project_name
    payload["workspace"] = workspace_name

    content = payload.get("content")
    scan_requested = payload.get("scan_workspace") or not content

    if scan_requested:
        root = settings.effective_projects_root
        target_path = _resolve_scan_target(root, project_name)

        if target_path and target_path.exists():
            result = await indexer.index_directory(target_path, workspace=workspace_name)
            await db.commit()
            return result

    # Chegou aqui sem varredura de diretório — `workspace` não passou pelo
    # `resolve()` de `_resolve_scan_target` (que garante que aponta para uma
    # pasta real dentro de uma raiz conhecida). Sem esta checagem, um
    # `project` inventado no payload gravaria `GraphNode`/`GraphEdge` numa
    # partição de workspace fantasma, sem relação com nenhum projeto real.
    try:
        await ensure_project_slug_exists(db, workspace_name)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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


@router.post("/query/multi")
async def query_graph_rag_multi(
    req: MultiWorkspaceQueryRequest, db: DbSessionDep
) -> dict[str, dict[str, Any]]:
    """Busca GraphRAG opt-in através de múltiplos workspaces (projetos) — sem
    fundir score entre eles, ver `GraphifyEngine.search_multi_workspace`."""
    engine = GraphifyEngine(db)
    return await engine.search_multi_workspace(
        req.query, req.workspaces, top_k=req.top_k, max_hops=req.max_hops
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
    nodes, edges = await store.get_ego_subgraph(node_id, workspace=workspace, max_hops=max_hops)
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
