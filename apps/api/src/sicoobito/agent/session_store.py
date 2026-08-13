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
    summary: str | None = None,
    total_cost_usd: float | None = None,
    total_tokens: int | None = None,
    iterations: int | None = None,
    pending_approvals: int | None = None,
    last_failed_call_count: int | None = None,
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
            summary=summary,
            total_cost_usd=total_cost_usd or 0.0,
            total_tokens=total_tokens or 0,
            iterations=iterations or 0,
            pending_approvals=pending_approvals or 0,
            last_failed_call_count=last_failed_call_count or 0,
        )
    )
    await session.flush()


async def get(session: AsyncSession, *, session_id: str) -> AgentSessionRecord | None:
    return await session.get(AgentSessionRecord, session_id)


async def update_summary(session: AsyncSession, *, session_id: str, summary: str | None) -> None:
    registro = await session.get(AgentSessionRecord, session_id)
    if registro is None:
        return
    registro.summary = summary
    await session.flush()


async def update_metrics(
    session: AsyncSession,
    *,
    session_id: str,
    summary: str | None = None,
    total_cost_usd: float | None = None,
    total_tokens: int | None = None,
    iterations: int | None = None,
    pending_approvals: int | None = None,
    last_failed_call_count: int | None = None,
) -> None:
    registro = await session.get(AgentSessionRecord, session_id)
    if registro is None:
        return
    if summary is not None:
        registro.summary = summary
    if total_cost_usd is not None:
        registro.total_cost_usd = total_cost_usd
    if total_tokens is not None:
        registro.total_tokens = total_tokens
    if iterations is not None:
        registro.iterations = iterations
    if pending_approvals is not None:
        registro.pending_approvals = pending_approvals
    if last_failed_call_count is not None:
        registro.last_failed_call_count = last_failed_call_count
    await session.flush()


async def mark_closed(
    session: AsyncSession, *, session_id: str, summary: str | None = None
) -> None:
    registro = await session.get(AgentSessionRecord, session_id)
    if registro is None:
        # A sessão pode ter sido criada antes desta tabela existir, ou o
        # registro pode ter falhado silenciosamente na criação (ver
        # runner.py) — fechar algo que não está lá não é erro.
        return
    registro.status = "closed"
    if summary is not None:
        registro.summary = summary
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
