"""Persistência do histórico de sessões do agente.

Guarda só o que uma lista de histórico precisa mostrar e filtrar — não o
grafo em si (isso é o checkpointer). Ver `db.models.AgentSessionRecord`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.db.models import AgentSessionRecord


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


async def mark_abandoned(session: AsyncSession, *, older_than: datetime) -> int:
    """Marca como `"abandoned"` toda sessão `"open"` sem atividade desde
    `older_than`. Nunca toca `"closed"`: uma aba fechada sem `close_session`
    explícito é o único jeito de uma sessão travar em `"open"` para sempre —
    ver `AgentSessionRecord.status` em `db/models.py`."""
    stmt = (
        update(AgentSessionRecord)
        .where(AgentSessionRecord.status == "open")
        .where(AgentSessionRecord.updated_at < older_than)
        .values(status="abandoned")
    )
    resultado = await session.execute(stmt)
    await session.flush()
    return resultado.rowcount or 0


async def graph_snapshot(
    session: AsyncSession, *, root_session_id: str
) -> Sequence[AgentSessionRecord]:
    """Reconstrói a árvore pai/filho (BFS) a partir do espelho durável nesta
    tabela — usado por `AgentCoordinator.graph_snapshot` como fallback quando
    o Redis está vazio (indisponível, ou TTL expirado depois de um restart:
    a árvore ao vivo mora só lá, ver `agent/coordinator.py`). `[]` se a raiz
    não existe aqui — pode ser uma sessão nova demais para ter sido persistida
    ainda, ou um `session_id` inválido."""
    raiz = await session.get(AgentSessionRecord, root_session_id)
    if raiz is None:
        return []
    registros = [raiz]
    fila = [root_session_id]
    visitados = {root_session_id}
    while fila:
        atual = fila.pop(0)
        filhos = await list_sessions(session, parent_session_id=atual, limit=1000)
        for filho in filhos:
            if filho.session_id in visitados:
                continue
            visitados.add(filho.session_id)
            registros.append(filho)
            fila.append(filho.session_id)
    return registros


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
