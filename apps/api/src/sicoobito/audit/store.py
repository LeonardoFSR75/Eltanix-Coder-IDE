"""Persistência de auditoria."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import AuditLogEntry


async def record(
    session: AsyncSession,
    *,
    actor: str,
    module: str,
    action: str,
    details: str = "",
    risk_level: str = "low",
    status: str = "success",
    session_id: str | None = None,
    metadata: dict | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(
        actor=actor,
        module=module,
        action=action,
        details=details,
        risk_level=risk_level,
        status=status,
        session_id=session_id,
        event_metadata=metadata or {},
    )
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    return entry


async def list_entries(
    session: AsyncSession,
    *,
    module: str | None = None,
    risk_level: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLogEntry]:
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.created_at.desc())
    if module:
        stmt = stmt.where(AuditLogEntry.module == module)
    if risk_level:
        stmt = stmt.where(AuditLogEntry.risk_level == risk_level)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AuditLogEntry.action.ilike(like) | AuditLogEntry.details.ilike(like))
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def get_entry(session: AsyncSession, entry_id: uuid.UUID) -> AuditLogEntry | None:
    return await session.get(AuditLogEntry, entry_id)
