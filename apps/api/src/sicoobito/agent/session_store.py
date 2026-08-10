"""Persistência do histórico de sessões do agente.

Guarda só o que uma lista de histórico precisa mostrar e filtrar — não o
grafo em si (isso é o checkpointer). Ver `db.models.AgentSessionRecord`.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import AgentSessionRecord


async def create(
    session: AsyncSession,
    *,
    session_id: str,
    project: str,
    task: str,
    mode: str,
    profile: str | None,
    branch: str | None,
    base_branch: str | None,
    parent_session_id: str | None = None,
) -> None:
    session.add(
        AgentSessionRecord(
            session_id=session_id,
            project=project,
            task=task,
            mode=mode,
            profile=profile,
            branch=branch or None,
            base_branch=base_branch,
            parent_session_id=parent_session_id,
        )
    )
    await session.flush()


async def mark_closed(session: AsyncSession, *, session_id: str) -> None:
    registro = await session.get(AgentSessionRecord, session_id)
    if registro is None:
        # A sessão pode ter sido criada antes desta tabela existir, ou o
        # registro pode ter falhado silenciosamente na criação (ver
        # runner.py) — fechar algo que não está lá não é erro.
        return
    registro.status = "closed"
    await session.flush()


async def list_sessions(
    session: AsyncSession,
    *,
    project: str | None = None,
    status: str | None = None,
    parent_session_id: str | None = None,
    limit: int = 50,
) -> Sequence[AgentSessionRecord]:
    query = select(AgentSessionRecord).order_by(AgentSessionRecord.updated_at.desc()).limit(limit)
    if project is not None:
        query = query.where(AgentSessionRecord.project == project)
    if status is not None and status != "all":
        query = query.where(AgentSessionRecord.status == status)
    if parent_session_id is not None:
        query = query.where(AgentSessionRecord.parent_session_id == parent_session_id)
    return (await session.execute(query)).scalars().all()
