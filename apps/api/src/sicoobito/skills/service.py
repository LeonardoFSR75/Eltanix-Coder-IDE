"""Orquestração de skills — fina o bastante para não precisar de mais que isto:
CRUD simples e o contador de uso que a ferramenta `get_skill` incrementa."""

from __future__ import annotations

import uuid
from pathlib import Path

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

    async def propose_and_save(
        self,
        *,
        name: str,
        description: str,
        category: str = "learned",
        system_prompt: str,
        parameters_json: str = "{}",
        workspace_root: Path | None = None,
    ) -> Skill:
        """Cria a skill no banco e opcionalmente grava o arquivo `.sicoobito/skills/<name>.md`
        no repositório do workspace para persistência no Git (Self-Improving Skill)."""
        async with session_scope() as session:
            skill = await store.create_skill(
                session,
                name=name,
                description=description,
                category=category,
                system_prompt=system_prompt,
                parameters_json=parameters_json,
            )

        if workspace_root is not None:
            try:
                ws_path = Path(workspace_root)
                skills_dir = ws_path / ".sicoobito" / "skills"
                skills_dir.mkdir(parents=True, exist_ok=True)
                slug_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
                file_path = skills_dir / f"{slug_name}.md"
                file_content = (
                    f"---\n"
                    f"name: {name}\n"
                    f"category: {category}\n"
                    f"description: {description}\n"
                    f"---\n\n"
                    f"{system_prompt}\n"
                )
                file_path.write_text(file_content, encoding="utf-8")
            except Exception:
                pass

        return skill
