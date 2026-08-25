"""Spans recentes de execução: ferramentas do agente e buscas RAG.

Complementa `metrics.py` (custo/tokens de LLM, durável em Postgres) e
`health.py` (p50/p95 por modelo, Redis) com o que nenhum dos dois cobre —
ver `telemetry/tracer.py::TraceRecorder`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from sicoobito.api.deps import AuthDep
from sicoobito.db.session import session_scope
from sicoobito.telemetry import store as telemetry_store
from sicoobito.telemetry.tracer import TraceRecorder

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"], dependencies=[AuthDep])


def _recorder(request: Request) -> TraceRecorder:
    recorder: TraceRecorder | None = getattr(request.app.state, "trace_recorder", None)
    if recorder is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registro de telemetria indisponível.",
        )
    return recorder


@router.get("/recent")
async def recent(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    entries = await _recorder(request).recent_async(limit=limit)
    return {
        "entries": [
            {
                "ts": entry.ts,
                "kind": entry.kind,
                "name": entry.name,
                "latency_ms": entry.latency_ms,
                "status": entry.status,
                "session_id": entry.session_id,
                "error": entry.error,
            }
            for entry in entries
        ]
    }


@router.get("/history")
async def history(
    before: datetime | None = None,
    session_id: str | None = Query(default=None),
    kind: Literal["tool", "rag"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Histórico durável (Postgres, `tool_span`) — complementa `/recent`
    (memória/Redis, capado) para consultas além da janela recente."""
    async with session_scope() as session:
        spans = await telemetry_store.list_spans(
            session, before=before, session_id=session_id, kind=kind, limit=limit
        )
    return {
        "entries": [
            {
                "id": str(span.id),
                "ts": span.created_at.timestamp(),
                "kind": span.kind,
                "name": span.name,
                "latency_ms": span.latency_ms,
                "status": span.status,
                "session_id": span.session_id,
                "error": span.error,
            }
            for span in spans
        ],
        "next_before": spans[-1].created_at.isoformat() if len(spans) == limit else None,
    }
