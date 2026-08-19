"""Extração de vetores de embeddings e representação semântica de trajetórias."""

from __future__ import annotations

from typing import Any

import structlog

from sicoobito.router import RouterEngine

logger = structlog.get_logger(__name__)


class FeatureExtractor:
    """Gera representação semântica vetorial para trajetórias de chat."""

    def __init__(self, router: RouterEngine | None = None) -> None:
        self.router = router or RouterEngine()

    async def generate_trajectory_embedding(self, trajectory: dict[str, Any]) -> list[float] | None:
        """Gera o embedding denso combinado (Prompt + Resumos de Passos + Erros)."""
        try:
            prompt = trajectory.get("user_prompt", "")
            steps = trajectory.get("trajectory_data", {}).get("steps", [])

            error_snippets = []
            for step in steps:
                for call in step.get("tool_calls", []):
                    if call.get("error"):
                        error_snippets.append(f"Tool {call.get('name')}: {call.get('error')}")

            summary_text = f"User Intent: {prompt}\n"
            if error_snippets:
                summary_text += "Errors:\n" + "\n".join(error_snippets[:5])

            res = await self.router.embed(input_text=summary_text[:2000])
            return res.vector
        except Exception as e:
            logger.warning("analytics.embedding_generation_failed", error=str(e))
            return None
