"""Modos customizáveis do agente (Fase 6 do upgrade do agente): CRUD simples,
mesmo padrão de `skills/store.py`+`skills/service.py`, num único arquivo por
não ter a complexidade extra de busca por embedding que skills tem.

O `id` (UUID) é o próprio valor que passa a circular como `mode` de uma sessão
quando não é um dos 7 modos embutidos — ver `agent/state.py::BUILTIN_MODES` e
`agent/graph.py::_tool_schemas`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.db.models import CustomMode
from eltanix.db.session import session_scope


async def _create(
    session: AsyncSession,
    *,
    name: str,
    icon: str,
    description: str,
    allowed_tools: list[str],
    prompt_block: str,
) -> CustomMode:
    modo = CustomMode(
        name=name,
        icon=icon,
        description=description,
        allowed_tools=allowed_tools,
        prompt_block=prompt_block,
    )
    session.add(modo)
    await session.flush()
    await session.refresh(modo)
    return modo


async def _get(session: AsyncSession, mode_id: uuid.UUID) -> CustomMode | None:
    return await session.get(CustomMode, mode_id)


async def _list_all(session: AsyncSession) -> list[CustomMode]:
    stmt = select(CustomMode).order_by(CustomMode.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def _update(
    session: AsyncSession,
    mode_id: uuid.UUID,
    *,
    name: str,
    icon: str,
    description: str,
    allowed_tools: list[str],
    prompt_block: str,
) -> CustomMode | None:
    modo = await session.get(CustomMode, mode_id)
    if modo is None:
        return None
    modo.name = name
    modo.icon = icon
    modo.description = description
    modo.allowed_tools = allowed_tools
    modo.prompt_block = prompt_block
    await session.flush()
    await session.refresh(modo)
    return modo


async def _delete(session: AsyncSession, mode_id: uuid.UUID) -> CustomMode | None:
    modo = await session.get(CustomMode, mode_id)
    if modo is None:
        return None
    await session.delete(modo)
    return modo


class CustomModeService:
    async def create(
        self,
        *,
        name: str,
        icon: str = "🧩",
        description: str = "",
        allowed_tools: list[str],
        prompt_block: str = "",
    ) -> CustomMode:
        async with session_scope() as session:
            return await _create(
                session,
                name=name,
                icon=icon,
                description=description,
                allowed_tools=allowed_tools,
                prompt_block=prompt_block,
            )

    async def get(self, mode_id: uuid.UUID) -> CustomMode | None:
        async with session_scope() as session:
            return await _get(session, mode_id)

    async def list_all(self) -> list[CustomMode]:
        async with session_scope() as session:
            return await _list_all(session)

    async def update(
        self,
        mode_id: uuid.UUID,
        *,
        name: str,
        icon: str,
        description: str,
        allowed_tools: list[str],
        prompt_block: str,
    ) -> CustomMode | None:
        async with session_scope() as session:
            return await _update(
                session,
                mode_id,
                name=name,
                icon=icon,
                description=description,
                allowed_tools=allowed_tools,
                prompt_block=prompt_block,
            )

    async def delete(self, mode_id: uuid.UUID) -> bool:
        async with session_scope() as session:
            modo = await _delete(session, mode_id)
        return modo is not None
