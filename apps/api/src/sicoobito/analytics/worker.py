"""Worker de segundo plano para processamento em lotes (batch) de diagnósticos ML.

Executa a cada 30 minutos agrupamento de falhas inéditas e análise de causa raiz (RCA)
para otimização do consumo de tokens de LLM.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from sicoobito.analytics.diagnostics.correction_generator import CorrectionProposalGenerator
from sicoobito.analytics.diagnostics.rca_engine import RCAEngine
from sicoobito.analytics.models.classifier import FailureCategory
from sicoobito.analytics.models.clustering import UnsupervisedClusterer
from sicoobito.db.models import ChatTrajectory, CorrectionProposal, FailureCluster
from sicoobito.db.session import session_scope
from sicoobito.router import RouterEngine

logger = structlog.get_logger(__name__)

# Intervalo do lote: 30 minutos (1800 segundos)
BATCH_INTERVAL_SECONDS = 1800


class AnalyticsBatchWorker:
    """Worker periódico que processa lotes de trajetórias acumuladas."""

    def __init__(self, router: RouterEngine | None = None) -> None:
        self.router = router or RouterEngine()
        self.rca_engine = RCAEngine(self.router)
        self.proposal_generator = CorrectionProposalGenerator(self.router)

    async def run_batch_cycle(self) -> dict[str, Any]:
        """Executa um ciclo de processamento em lote."""
        logger.info("analytics_worker.batch_started")
        now = datetime.now(UTC)
        time_window = now - timedelta(seconds=BATCH_INTERVAL_SECONDS)

        async with session_scope() as session:
            # Buscar trajetórias com falha nos últimos 30 minutos
            stmt = select(ChatTrajectory).where(
                ChatTrajectory.created_at >= time_window,
                ChatTrajectory.failure_category != FailureCategory.NONE,
            )
            res = await session.execute(stmt)
            trajectories = list(res.scalars().all())

            if not trajectories:
                logger.info("analytics_worker.batch_completed", processed_count=0)
                return {"processed_count": 0, "clusters_created": 0}

            # Formatar para o clusterer
            traj_dicts = [
                {
                    "id": str(t.id),
                    "session_id": t.session_id,
                    "user_prompt": t.user_prompt,
                    "failure_category": t.failure_category,
                    "trajectory_data": t.trajectory_data,
                    "metrics": t.metrics,
                    "embedding": t.embedding,
                }
                for t in trajectories
            ]

            # Executar clustering não-supervisionado
            clusters = UnsupervisedClusterer.cluster_trajectories(
                traj_dicts, distance_threshold=0.25
            )
            clusters_created = 0

            for cluster_info in clusters:
                sample_ids = cluster_info.get("sample_ids", [])
                if not sample_ids:
                    continue

                # Pega a primeira trajetória do cluster como representante
                first_traj = next((t for t in traj_dicts if t["id"] in sample_ids), None)
                if not first_traj:
                    continue

                category = first_traj["failure_category"]
                rca_res = await self.rca_engine.analyze_failure(first_traj, category)
                proposal_dict = await self.proposal_generator.generate_proposal(first_traj, rca_res)

                # Salvar cluster e proposta
                cluster_rec = FailureCluster(
                    name=f"Batch Cluster {category} ({sample_ids[0][:8]})",
                    failure_category=category,
                    description=rca_res.get("root_cause", ""),
                    occurrence_count=cluster_info.get("occurrence_count", 1),
                    centroid_embedding=first_traj.get("embedding"),
                    sample_trajectory_ids=sample_ids,
                    status="active",
                )
                session.add(cluster_rec)
                await session.flush()

                proposal_rec = CorrectionProposal(
                    cluster_id=cluster_rec.id,
                    title=proposal_dict["title"],
                    proposal_type=proposal_dict["proposal_type"],
                    target_file=proposal_dict.get("target_file"),
                    diff_content=proposal_dict["diff_content"],
                    explanation=proposal_dict["explanation"],
                    confidence_score=proposal_dict["confidence_score"],
                    status="pending",
                )
                session.add(proposal_rec)
                clusters_created += 1

            await session.commit()
            logger.info(
                "analytics_worker.batch_completed",
                processed_count=len(trajectories),
                clusters_created=clusters_created,
            )
            return {"processed_count": len(trajectories), "clusters_created": clusters_created}


async def run_analytics_batch_reaper(router: RouterEngine | None = None) -> None:
    """Loop de execução contínua a cada 30 minutos."""
    worker = AnalyticsBatchWorker(router)
    while True:
        try:
            await asyncio.sleep(BATCH_INTERVAL_SECONDS)
            await worker.run_batch_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("analytics_worker.loop_error", error=str(exc))
            with suppress(asyncio.CancelledError):
                await asyncio.sleep(10)
