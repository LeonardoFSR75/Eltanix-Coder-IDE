"""Consulta paginada de `tool_span` — a metade durável de `TraceRecorder`.

`tracer.py::recent()`/`recent_async()` cobrem o "agora" (memória/Redis, rápido,
capado); isto cobre o histórico que sobrevive a um restart, sem duplicar
lógica de agregação — é busca simples filtrada, não métrica.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.db.models import ToolSpan


async def list_spans(
    session: AsyncSession,
    *,
    before: datetime | None = None,
    session_id: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> Sequence[ToolSpan]:
    stmt = select(ToolSpan).order_by(ToolSpan.created_at.desc()).limit(limit)
    if before is not None:
        stmt = stmt.where(ToolSpan.created_at < before)
    if session_id is not None:
        stmt = stmt.where(ToolSpan.session_id == session_id)
    if kind is not None:
        stmt = stmt.where(ToolSpan.kind == kind)
    result = await session.execute(stmt)
    return result.scalars().all()
