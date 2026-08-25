"""Persistência de skills — CRUD simples + busca por similaridade do embedding
de `description` (roteamento automático, ver `SkillService.find_relevant`)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.db.models import Skill


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


async def get_skill_by_name(session: AsyncSession, name: str) -> Skill | None:
    """Usado por `spawn_agent` (Horizonte 4, item 3) para carregar o
    `system_prompt` de uma skill existente como especialização de um agente
    filho — o nome é o identificador que o chamador (LLM) conhece, não o UUID."""
    stmt = select(Skill).where(Skill.name == name)
    return (await session.execute(stmt)).scalar_one_or_none()


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


async def set_description_embedding(
    session: AsyncSession, skill_id: uuid.UUID, embedding: list[float]
) -> None:
    """Grava o vetor de `description` calculado fora da transação (a chamada ao
    provedor de embedding não pode acontecer dentro de um `session_scope`)."""
    skill = await session.get(Skill, skill_id)
    if skill is not None:
        skill.description_embedding = embedding


async def search_by_similarity(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    top_k: int = 2,
    min_score: float = 0.72,
) -> list[Skill]:
    """Top-k skills habilitadas por similaridade de cosseno entre
    `query_embedding` e `description_embedding`. `1 - (a <=> b)` converte a
    distância de cosseno do pgvector (0 = idêntico) em score de similaridade
    (1 = idêntico) — mesma convenção usada para o `min_score` em
    `SkillService.find_relevant`. Skills sem embedding ainda calculado
    (`description_embedding IS NULL`) nunca aparecem — silenciosamente
    ausentes do roteamento automático até o próximo seed/CRUD as recalcular,
    não um erro.
    """
    sql = """
        SELECT id, 1 - (description_embedding <=> CAST(:embedding AS vector)) AS score
        FROM skill
        WHERE enabled = true AND description_embedding IS NOT NULL
        ORDER BY description_embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """
    rows = (
        (await session.execute(text(sql), {"embedding": str(query_embedding), "top_k": top_k}))
        .mappings()
        .all()
    )

    matched_ids = [row["id"] for row in rows if float(row["score"]) >= min_score]
    if not matched_ids:
        return []

    skills = {
        s.id: s
        for s in (await session.execute(select(Skill).where(Skill.id.in_(matched_ids)))).scalars()
    }
    # Reordena pelo score original (a query `IN` do passo acima não preserva ordem).
    return [skills[i] for i in matched_ids if i in skills]
