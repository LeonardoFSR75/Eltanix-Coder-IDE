"""Engine principal do Graphify: Fachada para orquestrar indexação, GraphRAG e métricas."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from sicoobito.graphify.metrics.analytics import GraphAnalytics
from sicoobito.graphify.pipeline.indexer import GraphIndexer
from sicoobito.graphify.rag.graph_rag import GraphRAGQueryEngine
from sicoobito.graphify.store import GraphStore


class GraphifyEngine:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.store = GraphStore(session)
        self.indexer = GraphIndexer(self.store)
        self.rag_engine = GraphRAGQueryEngine(self.store)
        self.analytics = GraphAnalytics(self.store)

    async def index_item(self, source_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.indexer.run_pipeline(source_type, payload)
        self.session.commit()
        return result

    async def search_graph_rag(
        self, query: str, workspace: str = "default", top_k: int = 10, max_hops: int = 2
    ) -> dict[str, Any]:
        res = await self.rag_engine.search(query, workspace=workspace, top_k=top_k, max_hops=max_hops)
        return res.model_dump()

    def get_metrics(self, workspace: str = "default") -> dict[str, Any]:
        res = self.analytics.compute_all(workspace)
        self.session.commit()
        return res
