"""Gerador de Sugestões de Correção para Falhas de IDE Mapeadas."""

from __future__ import annotations

from typing import Any

import structlog

from sicoobito.analytics.models.classifier import FailureCategory
from sicoobito.router import RouterEngine

logger = structlog.get_logger(__name__)


class CorrectionProposalGenerator:
    """Gera propostas de correção acionáveis baseadas na causa raiz diagnosticada."""

    def __init__(self, router: RouterEngine | None = None) -> None:
        self.router = router or RouterEngine()

    async def generate_proposal(
        self, trajectory: dict[str, Any], rca_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Gera uma proposta de correção contendo tipo, arquivo alvo, explicação e diff sugerido."""
        category = rca_result.get("category", FailureCategory.NONE)
        root_cause = rca_result.get("root_cause", "")

        if category == FailureCategory.TOOL_EXECUTION_FAILURE:
            return {
                "title": "Ajuste na Validação de Parâmetros da Ferramenta de Sandbox",
                "proposal_type": "TOOL_PATCH",
                "target_file": "apps/api/src/sicoobito/agent/tools/sandbox.py",
                "explanation": f"Falha na ferramenta detectada. {root_cause}",
                "diff_content": (
                    "--- a/agent/tools/sandbox.py\n"
                    "+++ b/agent/tools/sandbox.py\n"
                    "@@ -15,4 +15,6 @@\n"
                    "+ # Adicionada sanitização de caminho para prevenir FileNotFoundError\n"
                    "+ target_path = normalize_workspace_path(input_path)\n"
                ),
                "confidence_score": 0.88,
            }

        elif category == FailureCategory.AGENT_HALLUCINATION_OR_LOOP:
            return {
                "title": "Adição de Regra Anti-Loop e Parada Precoce no Prompt da Skill Mestra",
                "proposal_type": "PROMPT_PATCH",
                "target_file": ".agents/skills/master-dev/SKILL.md",
                "explanation": f"O agente entrou em loop de execução. {root_cause}",
                "diff_content": (
                    "--- a/.agents/skills/master-dev/SKILL.md\n"
                    "+++ b/.agents/skills/master-dev/SKILL.md\n"
                    "@@ -10,3 +10,5 @@\n"
                    "+ ## Diretrizes Anti-Loop\n"
                    "+ - Se uma ferramenta falhar 2x, solicite ajuda ao usuário.\n"
                ),
                "confidence_score": 0.92,
            }

        elif category == FailureCategory.RAG_RETRIEVAL_MISS:
            return {
                "title": "Ajuste do Limiar de Similaridade Semântica e Indexação do Grafo",
                "proposal_type": "RAG_TUNING",
                "target_file": "apps/api/src/sicoobito/context/store.py",
                "explanation": f"Falha de recuperação de documentos no RAG. {root_cause}",
                "diff_content": (
                    "--- a/context/store.py\n"
                    "+++ b/context/store.py\n"
                    "@@ -40,3 +40,3 @@\n"
                    "- similarity_threshold = 0.75\n"
                    "+ similarity_threshold = 0.60 # Reduzido para expandir busca contextual\n"
                ),
                "confidence_score": 0.85,
            }

        elif category == FailureCategory.CONTEXT_TRUNCATION_OR_OVERFLOW:
            return {
                "title": "Compressão Automática de Histórico via TokenCompressor",
                "proposal_type": "ROUTER_RULE_PATCH",
                "target_file": "config/routes.yaml",
                "explanation": f"Saturação da janela de contexto. {root_cause}",
                "diff_content": (
                    "--- a/config/routes.yaml\n"
                    "+++ b/config/routes.yaml\n"
                    "@@ -5,2 +5,4 @@\n"
                    "+ enable_auto_compression: true\n"
                    "+ max_history_tokens: 64000\n"
                ),
                "confidence_score": 0.90,
            }

        # Fallback genérico
        return {
            "title": f"Ajuste Operacional na IDE ({category})",
            "proposal_type": "CODE_FIX",
            "target_file": "apps/api/src/sicoobito/agent/runner.py",
            "explanation": f"Revisão operacional recomendada. {root_cause}",
            "diff_content": "# Revisão recomendada baseada no relatório de telemetria.",
            "confidence_score": 0.75,
        }
