"""Persistência de estado runtime de extensões — mesmo padrão de `skills/store.py`:
funções que só pedem um `AsyncSession`, sem `session_scope()` próprio."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.db.models import ExtensionSettings, ExtensionState

_UNSET: Any = object()


async def list_states(session: AsyncSession) -> dict[str, ExtensionState]:
    rows = (await session.execute(select(ExtensionState))).scalars().all()
    return {row.extension_id: row for row in rows}


async def upsert_state(
    session: AsyncSession,
    extension_id: str,
    *,
    active: bool | None = None,
    installed_version: str | None = _UNSET,
    pending_update_json: str | None = _UNSET,
) -> ExtensionState:
    state = await session.get(ExtensionState, extension_id)
    if state is None:
        state = ExtensionState(extension_id=extension_id, active=True if active is None else active)
        session.add(state)
    elif active is not None:
        state.active = active

    if installed_version is not _UNSET:
        state.installed_version = installed_version
    if pending_update_json is not _UNSET:
        state.pending_update_json = pending_update_json

    await session.flush()
    return state


async def get_settings(session: AsyncSession) -> ExtensionSettings:
    settings = await session.get(ExtensionSettings, 1)
    if settings is None:
        settings = ExtensionSettings(id=1)
        session.add(settings)
        await session.flush()
    return settings


async def update_settings(
    session: AsyncSession,
    *,
    auto_update_enabled: bool | None = None,
    last_sync_timestamp: float | None = None,
) -> ExtensionSettings:
    settings = await get_settings(session)
    if auto_update_enabled is not None:
        settings.auto_update_enabled = auto_update_enabled
    if last_sync_timestamp is not None:
        settings.last_sync_timestamp = last_sync_timestamp
    await session.flush()
    return settings
