"""Calculadora de métricas de saúde, densidade e centralidade do Grafo de Conhecimento."""

from __future__ import annotations

from eltanix.graphify.store import GraphStore


class GraphAnalytics:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    async def compute_all(self, workspace: str = "default") -> dict:
        """Calcula densidade, percentual de órfãos e atualiza PageRank no banco."""
        return await self.store.compute_metrics(workspace)
