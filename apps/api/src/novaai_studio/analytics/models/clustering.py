"""Agrupamento semântico não-supervisionado de anomalias inéditas em trajetórias."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def cosine_distance(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calcula a distância de cosseno entre dois vetores (1 - cosine_similarity)."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 1.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    similarity = dot / (norm_a * norm_b)
    return max(0.0, 1.0 - similarity)


class UnsupervisedClusterer:
    """Agrupa trajetórias com base em similaridade de distância de cosseno dos embeddings."""

    @staticmethod
    def cluster_trajectories(
        trajectories: list[dict[str, Any]], distance_threshold: float = 0.25
    ) -> list[dict[str, Any]]:
        """Agrupa trajetórias em clusters semânticos por proximidade de embeddings."""
        clusters: list[list[dict[str, Any]]] = []

        for traj in trajectories:
            emb = traj.get("embedding")
            if not emb:
                continue

            assigned = False
            for cluster in clusters:
                centroid = cluster[0]["embedding"]
                if cosine_distance(emb, centroid) <= distance_threshold:
                    cluster.append(traj)
                    assigned = True
                    break

            if not assigned:
                clusters.append([traj])

        result_clusters = []
        for i, cluster in enumerate(clusters):
            first = cluster[0]
            result_clusters.append(
                {
                    "cluster_index": i + 1,
                    "failure_category": first.get("failure_category", "UNKNOWN"),
                    "sample_ids": [t["id"] for t in cluster if "id" in t],
                    "occurrence_count": len(cluster),
                    "representative_prompt": first.get("user_prompt", "")[:100],
                }
            )

        return result_clusters
