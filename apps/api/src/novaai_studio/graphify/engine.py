"""Engine principal do Graphify: Fachada para orquestrar indexação, GraphRAG e métricas."""

from __future__ import annotations

from typing import Any

from novaai_studio.graphify.metrics.analytics import GraphAnalytics
from novaai_studio.graphify.pipeline.indexer import GraphIndexer
from novaai_studio.graphify.rag.graph_rag import GraphRAGQueryEngine
from novaai_studio.graphify.store import GraphStore
from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

# Limite de fan-out de `search_multi_workspace` — cada workspace é uma busca
# GraphRAG inteira (RRF + expansão multi-hop); sem teto, um pedido de busca
# cross-project vira um jeito barato de derrubar o banco.
MAX_MULTI_WORKSPACE_FANOUT = 10


class GraphifyEngine:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.store = GraphStore(session)
        self.indexer = GraphIndexer(self.store)
        self.rag_engine = GraphRAGQueryEngine(self.store)
        self.analytics = GraphAnalytics(self.store)

    async def index_item(self, source_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.indexer.run_pipeline(source_type, payload)
        if hasattr(self.session, "commit"):
            commit_res = self.session.commit()
            if hasattr(commit_res, "__await__"):
                await commit_res
        return result

    async def search_graph_rag(
        self, query: str, workspace: str = "default", top_k: int = 10, max_hops: int = 2
    ) -> dict[str, Any]:
        res = await self.rag_engine.search(
            query, workspace=workspace, top_k=top_k, max_hops=max_hops
        )
        return res.model_dump()

    async def get_metrics(self, workspace: str = "default") -> dict[str, Any]:
        res = await self.analytics.compute_all(workspace)
        if hasattr(self.session, "commit"):
            commit_res = self.session.commit()
            if hasattr(commit_res, "__await__"):
                await commit_res
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
