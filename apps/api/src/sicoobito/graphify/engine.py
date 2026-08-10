"""Engine principal do Graphify: Fachada para orquestrar indexação, GraphRAG e métricas."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from sicoobito.graphify.metrics.analytics import GraphAnalytics
from sicoobito.graphify.pipeline.indexer import GraphIndexer
from sicoobito.graphify.rag.graph_rag import GraphRAGQueryEngine
from sicoobito.graphify.store import GraphStore
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Limite de fan-out de `search_multi_workspace` — cada workspace é uma busca
# GraphRAG inteira (RRF + expansão multi-hop); sem teto, um pedido de busca
# cross-project vira um jeito barato de derrubar o banco.
MAX_MULTI_WORKSPACE_FANOUT = 10


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
        res = await self.rag_engine.search(
            query, workspace=workspace, top_k=top_k, max_hops=max_hops
        )
        return res.model_dump()

    def get_metrics(self, workspace: str = "default") -> dict[str, Any]:
        res = self.analytics.compute_all(workspace)
        self.session.commit()
        return res

    async def search_multi_workspace(
        self, query: str, workspaces: list[str], top_k: int = 10, max_hops: int = 2
    ) -> dict[str, dict[str, Any]]:
        """Roda `search_graph_rag` em cada workspace, sem fundir score entre
        eles — relevância não é comparável entre workspaces independentes, e
        um ranking global daria uma falsa sensação de "isso é mais relevante
        que aquilo" quando na verdade veio de escalas diferentes. Cada
        workspace decide se contribui; um que falhar é omitido (logado), não
        derruba os outros — mesmo espírito de degradação suave do resto da
        plataforma.

        `workspaces` é limitado a `MAX_MULTI_WORKSPACE_FANOUT` pelo chamador
        (rota/tool) antes de chegar aqui, mas a checagem também vive aqui
        porque este método pode ser chamado direto, sem passar pela rota."""
        limited = workspaces[:MAX_MULTI_WORKSPACE_FANOUT]
        results: dict[str, dict[str, Any]] = {}
        for workspace in limited:
            try:
                results[workspace] = await self.search_graph_rag(
                    query, workspace=workspace, top_k=top_k, max_hops=max_hops
                )
            except Exception as exc:
                log.warning(
                    "graphify.multi_workspace.failed", workspace=workspace, error=str(exc)[:200]
                )
        return results
