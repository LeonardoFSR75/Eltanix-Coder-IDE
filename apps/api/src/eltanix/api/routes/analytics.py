"""Rotas de API para o subsistema de Analytics ML e Auto-Diagnósticos."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from eltanix.analytics.service import AnalyticsService
from eltanix.api.deps import AuthDep, EngineDep
from eltanix.db.session import session_scope

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[AuthDep])


class IngestSessionPayload(BaseModel):
    session_id: str = Field(..., description="ID da sessão de agente")
    user_prompt: str = Field(..., description="Prompt do usuário")
    steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Passos e ferramentas executadas"
    )
    project_slug: str | None = Field(default=None, description="Slug do projeto")
    status: str = Field(
        default="success", description="Status da sessão (success, failed, interrupted)"
    )


@router.get("/dashboard")
async def get_dashboard(engine: EngineDep) -> dict[str, Any]:
    """Retorna o resumo de estatísticas de telemetria ML e falhas da IDE."""
    async with session_scope() as session:
        service = AnalyticsService(session, router=engine)
        summary = await service.get_dashboard_summary()
    return summary


@router.get("/proposals")
async def list_pending_proposals(engine: EngineDep) -> dict[str, Any]:
    """Lista todas as propostas de correção pendentes de revisão."""
    async with session_scope() as session:
        service = AnalyticsService(session, router=engine)
        proposals = await service.get_pending_proposals()

    return {
        "proposals": [
            {
                "id": str(p.id),
                "cluster_id": str(p.cluster_id) if p.cluster_id else None,
                "title": p.title,
                "proposal_type": p.proposal_type,
                "target_file": p.target_file,
                "diff_content": p.diff_content,
                "explanation": p.explanation,
                "confidence_score": p.confidence_score,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in proposals
        ]
    }


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(proposal_id: uuid.UUID, engine: EngineDep) -> dict[str, Any]:
    """Aplica uma proposta de correção sugerida."""
    async with session_scope() as session:
        service = AnalyticsService(session, router=engine)
        success = await service.apply_proposal(proposal_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposta de correção não encontrada.",
            )

    return {"status": "success", "message": "Proposta de correção aplicada com sucesso."}


@router.post("/ingest")
async def ingest_session(payload: IngestSessionPayload, engine: EngineDep) -> dict[str, Any]:
    """Ingere e analisa uma trajetória de chat em tempo real."""
    async with session_scope() as session:
        service = AnalyticsService(session, router=engine)
        record = await service.analyze_and_store_session(
            session_id=payload.session_id,
            user_prompt=payload.user_prompt,
            steps=payload.steps,
            project_slug=payload.project_slug,
            status=payload.status,
        )

    return {
        "status": "success",
        "trajectory_id": str(record.id),
        "failure_category": record.failure_category,
    }
