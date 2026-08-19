"""Serviço Principal de Analytics ML e Auto-Diagnóstico."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.analytics.diagnostics.correction_generator import CorrectionProposalGenerator
from sicoobito.analytics.diagnostics.rca_engine import RCAEngine
from sicoobito.analytics.features import FeatureExtractor
from sicoobito.analytics.ingestion import TrajectoryIngestor
from sicoobito.analytics.models.classifier import FailureCategory, TrajectoryClassifier
from sicoobito.db.models import ChatTrajectory, CorrectionProposal, FailureCluster
from sicoobito.router import RouterEngine

logger = structlog.get_logger(__name__)


class AnalyticsService:
    """Orquestrador do subsistema de análise de trajetórias e auto-diagnósticos por ML."""

    def __init__(self, db: AsyncSession, router: RouterEngine | None = None) -> None:
        self.db = db
        self.router = router
        self.feature_extractor = FeatureExtractor(self.router)
        self.rca_engine = RCAEngine(self.router)
        self.proposal_generator = CorrectionProposalGenerator(self.router)

    async def analyze_and_store_session(
        self,
        session_id: str,
        user_prompt: str,
        steps: list[dict[str, Any]],
        project_slug: str | None = None,
        status: str = "success",
    ) -> ChatTrajectory:
        """Informa, analisa, classifica e persiste uma sessão de chat."""
        # 1. Ingestão e Sanitização
        processed = TrajectoryIngestor.process_raw_session(
            session_id=session_id,
            user_prompt=user_prompt,
            steps=steps,
            project_slug=project_slug,
        )
        processed["status"] = status

        # 2. Extração de Embeddings
        embedding = await self.feature_extractor.generate_trajectory_embedding(processed)

        # 3. Classificação ML
        failure_category = TrajectoryClassifier.classify(processed)

        # 4. Criar e salvar ChatTrajectory
        trajectory_record = ChatTrajectory(
            session_id=session_id,
            project_slug=project_slug,
            user_prompt=processed["user_prompt"],
            step_count=processed["step_count"],
            tool_calls_count=processed["tool_calls_count"],
            tool_errors_count=processed["tool_errors_count"],
            status=status,
            failure_category=failure_category,
            trajectory_data=processed["trajectory_data"],
            metrics=processed["metrics"],
            embedding=embedding,
        )
        self.db.add(trajectory_record)
        await self.db.flush()

        # 5. Se houver falha, executar RCA e gerar Proposta de Correção
        if failure_category != FailureCategory.NONE:
            rca_res = await self.rca_engine.analyze_failure(processed, failure_category)
            proposal_dict = await self.proposal_generator.generate_proposal(processed, rca_res)

            # Criar ou atualizar cluster de falha
            cluster = FailureCluster(
                name=f"Cluster {failure_category} ({session_id[:8]})",
                failure_category=failure_category,
                description=rca_res.get("root_cause", ""),
                occurrence_count=1,
                centroid_embedding=embedding,
                sample_trajectory_ids=[str(trajectory_record.id)],
                status="active",
            )
            self.db.add(cluster)
            await self.db.flush()

            proposal = CorrectionProposal(
                cluster_id=cluster.id,
                title=proposal_dict["title"],
                proposal_type=proposal_dict["proposal_type"],
                target_file=proposal_dict.get("target_file"),
                diff_content=proposal_dict["diff_content"],
                explanation=proposal_dict["explanation"],
                confidence_score=proposal_dict["confidence_score"],
                status="pending",
            )
            self.db.add(proposal)
            await self.db.flush()

        await self.db.commit()
        return trajectory_record

    async def get_dashboard_summary(self) -> dict[str, Any]:
        """Calcula agregados e métricas para o painel de diagnósticos da IDE."""
        total_stmt = select(func.count(ChatTrajectory.id))
        total_res = await self.db.execute(total_stmt)
        total_sessions = total_res.scalar() or 0

        failed_stmt = select(func.count(ChatTrajectory.id)).where(
            ChatTrajectory.failure_category != FailureCategory.NONE
        )
        failed_res = await self.db.execute(failed_stmt)
        failed_sessions = failed_res.scalar() or 0

        pending_proposals_stmt = select(func.count(CorrectionProposal.id)).where(
            CorrectionProposal.status == "pending"
        )
        pending_res = await self.db.execute(pending_proposals_stmt)
        pending_proposals = pending_res.scalar() or 0

        success_rate = round(100.0 * (1.0 - (failed_sessions / max(total_sessions, 1))), 1)

        return {
            "total_sessions": total_sessions,
            "failed_sessions": failed_sessions,
            "success_rate_percent": success_rate,
            "pending_proposals_count": pending_proposals,
        }

    async def get_pending_proposals(self) -> list[CorrectionProposal]:
        """Retorna todas as propostas de correção pendentes de revisão."""
        stmt = (
            select(CorrectionProposal)
            .where(CorrectionProposal.status == "pending")
            .order_by(CorrectionProposal.created_at.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def apply_proposal(self, proposal_id: uuid.UUID) -> bool:
        """Marca uma proposta de correção como aplicada."""
        stmt = select(CorrectionProposal).where(CorrectionProposal.id == proposal_id)
        res = await self.db.execute(stmt)
        proposal = res.scalar_one_or_none()
        if not proposal:
            return False

        proposal.status = "applied"
        proposal.applied_at = datetime.now(UTC)
        await self.db.commit()
        return True
