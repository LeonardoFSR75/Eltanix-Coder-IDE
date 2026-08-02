"""Orquestração de skills — fina o bastante para não precisar de mais que isto:
CRUD simples e o contador de uso que a ferramenta `get_skill` incrementa."""

from __future__ import annotations

import uuid

from sicoobito.db.models import Skill
from sicoobito.db.session import session_scope
from sicoobito.skills import store


class SkillService:
    async def create(
        self,
        *,
        name: str,
        description: str,
        category: str,
        system_prompt: str,
        parameters_json: str,
    ) -> Skill:
        async with session_scope() as session:
            return await store.create_skill(
                session,
                name=name,
                description=description,
                category=category,
                system_prompt=system_prompt,
                parameters_json=parameters_json,
            )

    async def get(self, skill_id: uuid.UUID) -> Skill | None:
        async with session_scope() as session:
            return await store.get_skill(session, skill_id)

    async def list_all(self, *, only_enabled: bool = False) -> list[Skill]:
        async with session_scope() as session:
            return await store.list_skills(session, only_enabled=only_enabled)

    async def update(
        self,
        skill_id: uuid.UUID,
        *,
        name: str,
        description: str,
        category: str,
        system_prompt: str,
        parameters_json: str,
    ) -> Skill | None:
        async with session_scope() as session:
            return await store.update_skill(
                session,
                skill_id,
                name=name,
                description=description,
                category=category,
                system_prompt=system_prompt,
                parameters_json=parameters_json,
            )

    async def toggle(self, skill_id: uuid.UUID) -> Skill | None:
        async with session_scope() as session:
            return await store.toggle_skill(session, skill_id)

    async def delete(self, skill_id: uuid.UUID) -> bool:
        async with session_scope() as session:
            skill = await store.delete_skill(session, skill_id)
        return skill is not None

    async def get_and_record_usage(self, skill_id: uuid.UUID) -> Skill | None:
        """Usado pela ferramenta `get_skill` do agente: lê a skill e conta
        como uso — aceitável como efeito colateral de uma ferramenta READ,
        já que é só um contador, não estado que o agente controla."""
        async with session_scope() as session:
            skill = await store.get_skill(session, skill_id)
            if skill is None:
                return None
            await store.increment_usage(session, skill_id)
            await session.refresh(skill)
            return skill
