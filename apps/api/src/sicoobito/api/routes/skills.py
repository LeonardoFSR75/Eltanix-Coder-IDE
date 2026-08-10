"""Rotas de skills — presets de prompt de sistema reusáveis."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.audit.service import AuditService
from sicoobito.skills.service import SkillService

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[AuthDep])

_VALID_CATEGORIES = {"automation", "analysis", "code", "web", "database"}


def _service(request: Request) -> SkillService:
    service: SkillService | None = getattr(request.app.state, "skills", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de skills indisponível.",
        )
    return service


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


def _view(skill: Any) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "system_prompt": skill.system_prompt,
        "parameters_json": skill.parameters_json,
        "enabled": skill.enabled,
        "usage_count": skill.usage_count,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    category: str = Field(default="automation")
    system_prompt: str = Field(default="")
    parameters_json: str = Field(default="{}")

    def _validated_category(self) -> str:
        if self.category not in _VALID_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Categoria inválida: {self.category}. Use uma de {sorted(_VALID_CATEGORIES)}."
                ),
            )
        return self.category


@router.get("")
async def list_skills(request: Request) -> dict[str, Any]:
    skills = await _service(request).list_all()
    return {"skills": [_view(s) for s in skills]}


@router.post("")
async def create_skill(payload: SkillIn, request: Request) -> dict[str, Any]:
    skill = await _service(request).create(
        name=payload.name,
        description=payload.description,
        category=payload._validated_category(),
        system_prompt=payload.system_prompt,
        parameters_json=payload.parameters_json,
    )
    if audit := _audit(request):
        await audit.record(
            actor="usuário", module="Skills", action="Skill criada", details=skill.name
        )
    return _view(skill)


@router.get("/{skill_id}")
async def get_skill(skill_id: uuid.UUID, request: Request) -> dict[str, Any]:
    skill = await _service(request).get(skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill não encontrada.")
    return _view(skill)


@router.put("/{skill_id}")
async def update_skill(skill_id: uuid.UUID, payload: SkillIn, request: Request) -> dict[str, Any]:
    skill = await _service(request).update(
        skill_id,
        name=payload.name,
        description=payload.description,
        category=payload._validated_category(),
        system_prompt=payload.system_prompt,
        parameters_json=payload.parameters_json,
    )
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill não encontrada.")
    return _view(skill)


@router.post("/{skill_id}/toggle")
async def toggle_skill(skill_id: uuid.UUID, request: Request) -> dict[str, Any]:
    skill = await _service(request).toggle(skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill não encontrada.")
    return _view(skill)


@router.delete("/{skill_id}")
async def delete_skill(skill_id: uuid.UUID, request: Request) -> dict[str, Any]:
    skill = await _service(request).get(skill_id)
    deleted = await _service(request).delete(skill_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill não encontrada.")
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="Skills",
            action="Skill removida",
            details=skill.name if skill else str(skill_id),
            risk_level="medium",
        )
    return {"deleted": True}
