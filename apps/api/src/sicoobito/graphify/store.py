"""Camada de persistência e operações de Grafo no PostgreSQL (AsyncSession)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import GraphEdge, GraphMetrics, GraphNode
from sicoobito.graphify.schema import GraphEdgeCreate, GraphNodeCreate


class GraphStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_node(self, node_in: GraphNodeCreate) -> GraphNode:
        """Cria ou atualiza um nó pelo seu canonical_id dentro do mesmo workspace."""
        stmt = select(GraphNode).where(
            GraphNode.workspace == node_in.workspace,
            GraphNode.canonical_id == node_in.canonical_id,
        )
        result = await self.session.execute(stmt)
        node = result.scalar_one_or_none()

        if node:
            node.name = node_in.name
            node.entity_type = node_in.entity_type
            node.properties = {**node.properties, **node_in.properties}
            if node_in.summary:
                node.summary = node_in.summary
            if node_in.embedding is not None:
                node.embedding = node_in.embedding
        else:
            node = GraphNode(
                workspace=node_in.workspace,
                entity_type=node_in.entity_type,
                name=node_in.name,
                canonical_id=node_in.canonical_id,
                properties=node_in.properties,
                summary=node_in.summary,
                embedding=node_in.embedding,
            )
            self.session.add(node)

        await self.session.flush()
        return node

    async def add_edge(self, edge_in: GraphEdgeCreate) -> GraphEdge:
        """Adiciona ou atualiza uma aresta no grafo."""
        stmt = select(GraphEdge).where(
            GraphEdge.source_id == edge_in.source_id,
            GraphEdge.target_id == edge_in.target_id,
            GraphEdge.relation_type == edge_in.relation_type,
        )
        result = await self.session.execute(stmt)
        edge = result.scalar_one_or_none()

        if edge:
            edge.weight = edge_in.weight
            edge.layer = edge_in.layer
            if edge_in.evidence:
                edge.evidence = edge_in.evidence
            edge.edge_metadata = {**edge.edge_metadata, **edge_in.edge_metadata}
        else:
            edge = GraphEdge(
                workspace=edge_in.workspace,
                source_id=edge_in.source_id,
                target_id=edge_in.target_id,
                relation_type=edge_in.relation_type,
                layer=edge_in.layer,
                weight=edge_in.weight,
                evidence=edge_in.evidence,
                edge_metadata=edge_in.edge_metadata,
            )
            self.session.add(edge)

        await self.session.flush()
        return edge

    async def get_node_by_canonical(self, workspace: str, canonical_id: str) -> GraphNode | None:
        stmt = select(GraphNode).where(
            GraphNode.workspace == workspace, GraphNode.canonical_id == canonical_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_ego_subgraph(
        self, node_id: UUID, *, workspace: str, max_hops: int = 2
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Retorna o subgrafo ego estendido a até max_hops a partir do nó central.

        `workspace` é obrigatório e filtra toda etapa da travessia — sem isso a
        CTE recursiva atravessa `graph_edge` sem checar workspace nenhum, e um
        `node_id` de outro projeto vazaria pro resultado (canonical_id já é
        único por `(workspace, canonical_id)`, mas edges referenciam UUID de
        nó direto, não canonical_id, então essa unicidade sozinha não protegia
        a travessia).
        """
        query = text(
            """
            WITH RECURSIVE graph_cte AS (
                SELECT id AS node_id, 0 AS hop
                FROM graph_node
                WHERE id = :node_id AND workspace = :workspace

                UNION

                SELECT
                    CASE WHEN e.source_id = gc.node_id
                        THEN e.target_id ELSE e.source_id
                    END AS node_id,
                    gc.hop + 1 AS hop
                FROM graph_cte gc
                JOIN graph_edge e ON (e.source_id = gc.node_id OR e.target_id = gc.node_id)
                    AND e.workspace = :workspace
                WHERE gc.hop < :max_hops
            )
            SELECT DISTINCT node_id FROM graph_cte;
            """
        )
        result = await self.session.execute(
            query, {"node_id": str(node_id), "workspace": workspace, "max_hops": max_hops}
        )
        node_ids = [row[0] for row in result.fetchall()]

        if not node_ids:
            return [], []

        nodes_result = await self.session.execute(
            select(GraphNode).where(GraphNode.id.in_(node_ids), GraphNode.workspace == workspace)
        )
        nodes = list(nodes_result.scalars().all())

        edges_result = await self.session.execute(
            select(GraphEdge).where(
                GraphEdge.source_id.in_(node_ids),
                GraphEdge.target_id.in_(node_ids),
                GraphEdge.workspace == workspace,
            )
        )
        edges = list(edges_result.scalars().all())

        return nodes, edges

    async def get_workspace_nodes(
        self, workspace: str = "default", limit: int = 100
    ) -> Sequence[GraphNode]:
        stmt = (
            select(GraphNode)
            .where(GraphNode.workspace == workspace)
            .order_by(GraphNode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_workspace_edges(
        self, workspace: str = "default", limit: int = 500
    ) -> Sequence[GraphEdge]:
        stmt = (
            select(GraphEdge)
            .where(GraphEdge.workspace == workspace)
            .order_by(GraphEdge.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def compute_metrics(self, workspace: str = "default") -> dict:
        """Calcula PageRank simplificado e contagem de graus dos nós do workspace (Otimizado)."""
        nodes_result = await self.session.execute(
            select(GraphNode).where(GraphNode.workspace == workspace)
        )
        nodes = list(nodes_result.scalars().all())

        if not nodes:
            return {
                "total_nodes": 0,
                "total_edges": 0,
                "orphan_nodes_count": 0,
                "orphan_percentage": 0.0,
                "density": 0.0,
            }

        edges_result = await self.session.execute(
            select(GraphEdge).where(GraphEdge.workspace == workspace)
        )
        edges = list(edges_result.scalars().all())

        in_degrees: dict = {n.id: 0 for n in nodes}
        out_degrees: dict = {n.id: 0 for n in nodes}
        incoming_map: dict[UUID, list[UUID]] = {n.id: [] for n in nodes}

        for e in edges:
            if e.source_id in out_degrees:
                out_degrees[e.source_id] += 1
            if e.target_id in in_degrees:
                in_degrees[e.target_id] += 1
            if e.target_id in incoming_map:
                incoming_map[e.target_id].append(e.source_id)

        N = len(nodes)
        damping = 0.85
        pagerank: dict = {n.id: 1.0 / N for n in nodes}

        # Fast PageRank with Adjacency List O(E) per iteration
        for _ in range(5):
            new_pr: dict = {}
            for n in nodes:
                rank_sum = sum(
                    pagerank.get(src_id, 0.0) / (out_degrees.get(src_id, 1) or 1)
                    for src_id in incoming_map[n.id]
                )
                new_pr[n.id] = (1 - damping) / N + damping * rank_sum
            pagerank = new_pr

        # Single SQL Query to fetch existing metrics
        gm_existing = await self.session.execute(
            select(GraphMetrics).where(GraphMetrics.workspace == workspace)
        )
        gm_map = {gm.node_id: gm for gm in gm_existing.scalars().all()}

        orphan_count = 0
        for n in nodes:
            in_d = in_degrees[n.id]
            out_d = out_degrees[n.id]
            pr = pagerank[n.id]
            if in_d == 0 and out_d == 0:
                orphan_count += 1

            gm = gm_map.get(n.id)
            if gm:
                gm.in_degree = in_d
                gm.out_degree = out_d
                gm.pagerank = pr
            else:
                gm = GraphMetrics(
                    node_id=n.id,
                    workspace=workspace,
                    in_degree=in_d,
                    out_degree=out_d,
                    pagerank=pr,
                )
                self.session.add(gm)

        await self.session.flush()

        E = len(edges)
        density = (2.0 * E / (N * (N - 1))) if N > 1 else 0.0

        return {
            "total_nodes": N,
            "total_edges": E,
            "orphan_nodes_count": orphan_count,
            "orphan_percentage": round((orphan_count / N) * 100, 2) if N > 0 else 0.0,
            "density": round(density, 4),
        }
