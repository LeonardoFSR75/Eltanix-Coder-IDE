"""Rotas de modos customizáveis do agente (Fase 6 do upgrade do agente).

Mesmo desenho de `api/routes/skills.py`: recurso global (não por projeto),
service guardado em `app.state`, view function traduzindo o modelo ORM em
dict JSON-serializável."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from eltanix.agent.custom_modes import CustomModeService
from eltanix.api.deps import AuthDep
from eltanix.audit.service import AuditService

router = APIRouter(prefix="/api/agent/custom-modes", tags=["agent"], dependencies=[AuthDep])


def _service(request: Request) -> CustomModeService:
    service: CustomModeService | None = getattr(request.app.state, "custom_modes", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de modos customizados indisponível.",
        )
    return service


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


def _view(modo: Any) -> dict[str, Any]:
    return {
        "id": str(modo.id),
        "name": modo.name,
        "icon": modo.icon,
        "description": modo.description,
        "allowed_tools": modo.allowed_tools,
        "prompt_block": modo.prompt_block,
        "created_at": modo.created_at.isoformat(),
        "updated_at": modo.updated_at.isoformat(),
    }


class CustomModeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    icon: str = Field(default="🧩", max_length=16)
    description: str = Field(default="")
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_block: str = Field(default="")


@router.get("")
async def list_custom_modes(request: Request) -> dict[str, Any]:
    modos = await _service(request).list_all()
    return {"modes": [_view(m) for m in modos]}


@router.post("")
async def create_custom_mode(payload: CustomModeIn, request: Request) -> dict[str, Any]:
    modo = await _service(request).create(
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        allowed_tools=payload.allowed_tools,
        prompt_block=payload.prompt_block,
    )
    if audit := _audit(request):
        await audit.record(
            actor="usuário", module="Agente", action="Modo customizado criado", details=modo.name
        )
    return _view(modo)


@router.get("/{mode_id}")
async def get_custom_mode(mode_id: uuid.UUID, request: Request) -> dict[str, Any]:
    modo = await _service(request).get(mode_id)
    if modo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modo não encontrado.")
    return _view(modo)


@router.put("/{mode_id}")
async def update_custom_mode(
    mode_id: uuid.UUID, payload: CustomModeIn, request: Request
) -> dict[str, Any]:
    modo = await _service(request).update(
        mode_id,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        allowed_tools=payload.allowed_tools,
        prompt_block=payload.prompt_block,
    )
    if modo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modo não encontrado.")
    return _view(modo)


@router.delete("/{mode_id}")
async def delete_custom_mode(mode_id: uuid.UUID, request: Request) -> dict[str, Any]:
    modo = await _service(request).get(mode_id)
    deleted = await _service(request).delete(mode_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modo não encontrado.")
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="Agente",
            action="Modo customizado removido",
            details=modo.name if modo else str(mode_id),
            risk_level="medium",
        )
    return {"deleted": True}
