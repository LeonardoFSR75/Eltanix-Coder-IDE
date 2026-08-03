"""Spans recentes de execução: ferramentas do agente e buscas RAG.

Complementa `metrics.py` (custo/tokens de LLM, durável em Postgres) e
`health.py` (p50/p95 por modelo, Redis) com o que nenhum dos dois cobre —
ver `telemetry/tracer.py::TraceRecorder`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from sicoobito.api.deps import AuthDep
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
    entries = _recorder(request).recent(limit=limit)
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
