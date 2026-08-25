"""Rotas de auditoria.

`POST /log` existe para eventos puramente client-side sem contrapartida de
backend (ex.: "inserir código sugerido no editor") — eventos que já nascem no
servidor (aprovações de ferramenta, CRUD de documentos/notas/skills) chamam
`AuditService.record` direto, sem round-trip HTTP.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from eltanix.api.deps import AuthDep
from eltanix.audit.service import AuditService

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[AuthDep])


def _service(request: Request) -> AuditService:
    service: AuditService | None = getattr(request.app.state, "audit", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auditoria indisponível."
        )
    return service


def _view(entry: Any) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "created_at": entry.created_at.isoformat(),
        "actor": entry.actor,
        "module": entry.module,
        "action": entry.action,
        "details": entry.details,
        "risk_level": entry.risk_level,
        "status": entry.status,
        "session_id": entry.session_id,
        "project_slug": entry.project_slug,
        "metadata": entry.event_metadata,
    }


@router.get("")
async def list_audit(
    request: Request,
    module: str | None = None,
    risk_level: str | None = None,
    q: str | None = None,
    project_slug: str | None = None,
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    entries = await _service(request).list_all(
        module=module,
        risk_level=risk_level,
        q=q,
        project_slug=project_slug,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return {"entries": [_view(e) for e in entries]}


@router.get("/{entry_id}")
async def get_audit_entry(entry_id: uuid.UUID, request: Request) -> dict[str, Any]:
    entry = await _service(request).get(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Registro não encontrado."
        )
    return _view(entry)


class AuditLogRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=128)
    module: str = Field(min_length=1, max_length=32)
    action: str = Field(min_length=1, max_length=255)
    details: str = Field(default="")
    risk_level: str = Field(default="low")
    status: str = Field(default="success")


@router.post("/log")
async def log_event(payload: AuditLogRequest, request: Request) -> dict[str, Any]:
    entry = await _service(request).record(
        actor=payload.actor,
        module=payload.module,
        action=payload.action,
        details=payload.details,
        risk_level=payload.risk_level,
        status=payload.status,
    )
    return _view(entry)
