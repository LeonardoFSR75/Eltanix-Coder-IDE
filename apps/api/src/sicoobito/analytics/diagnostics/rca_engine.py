"""Engine de Análise de Causa Raiz (RCA) para falhas mapeadas da IDE."""

from __future__ import annotations

from typing import Any

import structlog

from sicoobito.analytics.models.classifier import FailureCategory
from sicoobito.router import RouterEngine

logger = structlog.get_logger(__name__)


class RCAEngine:
    """Diagnostica causas raízes de falhas de trajetória utilizando a fachada de LLM."""

    def __init__(self, router: RouterEngine | None = None) -> None:
        self.router = router

    async def analyze_failure(self, trajectory: dict[str, Any], category: str) -> dict[str, Any]:
        """Gera uma explicação detalhada e causa raiz da falha capturada."""
        if category == FailureCategory.NONE:
            return {"root_cause": "Nenhuma falha detectada.", "severity": "low"}

        prompt = trajectory.get("user_prompt", "")
        steps = trajectory.get("trajectory_data", {}).get("steps", [])

        errors = []
        for step in steps:
            for call in step.get("tool_calls", []):
                if call.get("error"):
                    errors.append(f"Tool `{call.get('name')}`: {call.get('error')}")

        errors_str = "\n".join(errors) if errors else "Sem exceção explícita no log."

        analysis_prompt = (
            f"Você é o diagnosticador de telemetria da IDE SicoobitoCode.\n"
            f"Analise a falha a seguir:\n"
            f"- Categoria da Falha: {category}\n"
            f"- Intenção do Usuário: {prompt}\n"
            f"- Erros Encontrados:\n{errors_str}\n\n"
            f"Forneça a Causa Raiz em 2-3 frases identificando "
            f"o componente responsável (Sandbox, Prompt, Tool, RAG ou Router)."
        )

        if self.router:
            try:
                res = await self.router.complete(prompt=analysis_prompt, max_tokens=256)
                explanation = res.text.strip()
            except Exception as e:
                logger.warning("rca_engine.completion_failed", error=str(e))
                explanation = (
                    f"Causa raiz inferida por regra: Falha no componente {category} "
                    f"durante a execução do comando."
                )
        else:
            explanation = (
                f"Causa raiz inferida por regra: Falha no componente {category} "
                f"durante a execução do comando."
            )

        severity_map = {
            FailureCategory.TOOL_EXECUTION_FAILURE: "high",
            FailureCategory.AGENT_HALLUCINATION_OR_LOOP: "critical",
            FailureCategory.RAG_RETRIEVAL_MISS: "medium",
            FailureCategory.CONTEXT_TRUNCATION_OR_OVERFLOW: "high",
            FailureCategory.PROMPT_REGRESSION_OR_AMBIGUITY: "medium",
            FailureCategory.LLM_PROVIDER_DEGRADATION: "critical",
        }

        return {
            "category": category,
            "root_cause": explanation,
            "severity": severity_map.get(category, "low"),
        }
