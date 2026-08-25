"""Mecanismo de busca GraphRAG: Recuperação Híbrida RRF + Expansão Multi-Hop por Grafo."""

from __future__ import annotations

from sqlalchemy import select, text

from eltanix.db.models import GraphEdge, GraphNode
from eltanix.graphify.schema import GraphEdgeRead, GraphNodeRead, GraphRAGResult
from eltanix.graphify.store import GraphStore


class GraphRAGQueryEngine:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.session = store.session

    async def search(
        self, query: str, workspace: str = "default", top_k: int = 10, max_hops: int = 2
    ) -> GraphRAGResult:
        """Executa busca GraphRAG combinando Full-Text + Expansão Multi-Hop."""
        # 1. Encontra Seed Nodes via Fulltext / Trigram no Postgres
        # `websearch_to_tsquery` (não `to_tsquery`) tolera aspas e operadores
        # digitados pelo usuário sem estourar erro de sintaxe — mesmo motivo
        # documentado em context/documents/notes `store.py`; `to_tsquery` cru
        # lança erro do Postgres em input comum (ex. "auth:", parêntese solto).
        sql = text(
            """
            SELECT id, name, entity_type, canonical_id, summary, workspace
            FROM graph_node
            WHERE workspace = :workspace
              AND (tsv @@ websearch_to_tsquery('simple', :query) OR name ILIKE :query_like)
            ORDER BY created_at DESC
            LIMIT :top_k;
            """
        )
        query_like = f"%{query.strip()}%"

        result = await self.session.execute(
            sql,
            {
                "workspace": workspace,
                "query": query.strip() or "a",
                "query_like": query_like,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        seed_node_ids = [row[0] for row in rows]

        if not seed_node_ids:
            # Fallback: traz os nós mais recentes do workspace
            recent = await self.store.get_workspace_nodes(workspace, limit=top_k)
            seed_node_ids = [n.id for n in recent]

        # 2. Travessia Multi-Hop de Grafo (CTE Recursiva)
        # `workspace` filtra toda etapa da travessia — mesma correção e mesmo
        # motivo documentados em `GraphStore.get_ego_subgraph`: sem isso a CTE
        # atravessa `graph_edge` sem checar workspace nenhum, e um seed node
        # de um workspace vazaria nó/aresta de outro (edges referenciam UUID
        # de nó direto, não canonical_id, então unicidade de canonical_id não
        # protege a travessia).
        all_node_ids: set = set(seed_node_ids)

        if seed_node_ids:
            cte_sql = text(
                """
                WITH RECURSIVE graph_expansion AS (
                    SELECT id AS node_id, 0 AS hop
                    FROM graph_node
                    WHERE id = ANY(:seed_ids) AND workspace = :workspace

                    UNION

                    SELECT
                        CASE WHEN e.source_id = ge.node_id
                            THEN e.target_id ELSE e.source_id
                        END AS node_id,
                        ge.hop + 1 AS hop
                    FROM graph_expansion ge
                    JOIN graph_edge e ON (e.source_id = ge.node_id OR e.target_id = ge.node_id)
                        AND e.workspace = :workspace
                    WHERE ge.hop < :max_hops AND e.weight >= 0.5
                )
                SELECT DISTINCT node_id FROM graph_expansion;
                """
            )
            cte_res = await self.session.execute(
                cte_sql,
                {
                    "seed_ids": [str(nid) for nid in seed_node_ids],
                    "max_hops": max_hops,
                    "workspace": workspace,
                },
            )
            for r in cte_res.fetchall():
                all_node_ids.add(r[0])

        nodes_result = await self.session.execute(
            select(GraphNode).where(
                GraphNode.id.in_(list(all_node_ids)), GraphNode.workspace == workspace
            )
        )
        nodes = list(nodes_result.scalars().all())

        edges_result = await self.session.execute(
            select(GraphEdge).where(
                GraphEdge.source_id.in_(list(all_node_ids)),
                GraphEdge.target_id.in_(list(all_node_ids)),
                GraphEdge.workspace == workspace,
            )
        )
        edges = list(edges_result.scalars().all())

        nodes_read = [
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

        edges_read = [
            GraphEdgeRead(
                id=e.id,
                workspace=e.workspace,
                source_id=e.source_id,
                target_id=e.target_id,
                relation_type=e.relation_type,
                layer=e.layer,
                weight=float(e.weight),
                evidence=e.evidence,
                edge_metadata=e.edge_metadata,
                created_at=e.created_at,
            )
            for e in edges
        ]

        chunks_summary = [
            {"node_id": str(n.id), "name": n.name, "type": n.entity_type, "summary": n.summary}
            for n in nodes
        ]

        return GraphRAGResult(
            nodes=nodes_read,
            edges=edges_read,
            chunks=chunks_summary,
            query=query,
            total_nodes=len(nodes_read),
        )
