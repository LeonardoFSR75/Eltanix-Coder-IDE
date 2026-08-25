"""Classificador de Falhas de Trajetória da IDE."""

from __future__ import annotations

from typing import Any


class FailureCategory:
    NONE = "NONE"
    TOOL_EXECUTION_FAILURE = "TOOL_EXECUTION_FAILURE"
    AGENT_HALLUCINATION_OR_LOOP = "AGENT_HALLUCINATION_OR_LOOP"
    RAG_RETRIEVAL_MISS = "RAG_RETRIEVAL_MISS"
    CONTEXT_TRUNCATION_OR_OVERFLOW = "CONTEXT_TRUNCATION_OR_OVERFLOW"
    PROMPT_REGRESSION_OR_AMBIGUITY = "PROMPT_REGRESSION_OR_AMBIGUITY"
    LLM_PROVIDER_DEGRADATION = "LLM_PROVIDER_DEGRADATION"


class TrajectoryClassifier:
    """Classifica falhas em trajetórias de chat utilizando heurísticas e métricas quantitativas."""

    @staticmethod
    def classify(trajectory: dict[str, Any]) -> str:
        """Determina a categoria de falha predominante da sessão."""
        metrics = trajectory.get("metrics", {})
        steps = trajectory.get("trajectory_data", {}).get("steps", [])
        tool_errors_count = trajectory.get("tool_errors_count", 0)
        tool_calls_count = trajectory.get("tool_calls_count", 0)

        # 1. Verificação de estouro/saturação de contexto
        if metrics.get("context_saturation", 0.0) >= 0.95:
            return FailureCategory.CONTEXT_TRUNCATION_OR_OVERFLOW

        # 2. Verificação de loops de repetição do agente
        if metrics.get("loop_coefficient", 0.0) >= 0.60 or (
            tool_calls_count > 10 and tool_errors_count == 0 and len(steps) > 8
        ):
            return FailureCategory.AGENT_HALLUCINATION_OR_LOOP

        # 3. Verificação de falhas de execução de ferramentas
        if tool_errors_count > 0 and (tool_errors_count / max(tool_calls_count, 1)) >= 0.33:
            # Checa se o erro é decorrente do sandbox/ferramenta
            for step in steps:
                for call in step.get("tool_calls", []):
                    err = str(call.get("error", "")).lower()
                    if "500" in err or "rate limit" in err or "timeout" in err:
                        return FailureCategory.LLM_PROVIDER_DEGRADATION
            return FailureCategory.TOOL_EXECUTION_FAILURE

        # 4. Verificação de falhas de RAG
        for step in steps:
            for call in step.get("tool_calls", []):
                if call.get("name") in ("search_codebase", "graph_search", "rag_query"):
                    output = str(call.get("output", "")).lower()
                    if "no results" in output or "not found" in output or "empty" in output:
                        return FailureCategory.RAG_RETRIEVAL_MISS

        # 5. Se o status geral for falha sem erros explícitos de ferramenta,
        # considera ambiguidade de prompt
        if trajectory.get("status") == "failed":
            return FailureCategory.PROMPT_REGRESSION_OR_AMBIGUITY

        return FailureCategory.NONE
