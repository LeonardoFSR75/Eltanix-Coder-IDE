"""Persistência de skills — CRUD simples, sem vetor nem chunking."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import Skill


async def create_skill(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    category: str,
    system_prompt: str,
    parameters_json: str,
) -> Skill:
    skill = Skill(
        name=name,
        description=description,
        category=category,
        system_prompt=system_prompt,
        parameters_json=parameters_json,
    )
    session.add(skill)
    await session.flush()
    await session.refresh(skill)
    return skill


async def get_skill(session: AsyncSession, skill_id: uuid.UUID) -> Skill | None:
    return await session.get(Skill, skill_id)


async def list_skills(session: AsyncSession, *, only_enabled: bool = False) -> list[Skill]:
    stmt = select(Skill).order_by(Skill.created_at.desc())
    if only_enabled:
        stmt = stmt.where(Skill.enabled.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def update_skill(
    session: AsyncSession,
    skill_id: uuid.UUID,
    *,
    name: str,
    description: str,
    category: str,
    system_prompt: str,
    parameters_json: str,
) -> Skill | None:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        return None
    skill.name = name
    skill.description = description
    skill.category = category
    skill.system_prompt = system_prompt
    skill.parameters_json = parameters_json
    await session.flush()
    await session.refresh(skill)
    return skill


async def toggle_skill(session: AsyncSession, skill_id: uuid.UUID) -> Skill | None:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        return None
    skill.enabled = not skill.enabled
    await session.flush()
    await session.refresh(skill)
    return skill


async def increment_usage(session: AsyncSession, skill_id: uuid.UUID) -> None:
    skill = await session.get(Skill, skill_id)
    if skill is not None:
        skill.usage_count += 1


async def delete_skill(session: AsyncSession, skill_id: uuid.UUID) -> Skill | None:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        return None
    await session.delete(skill)
    return skill
