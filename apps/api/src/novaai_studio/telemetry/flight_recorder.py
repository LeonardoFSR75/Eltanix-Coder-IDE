"""Linha do tempo unificada de uma sessão de agente — Agent Flight Recorder v1.

Compõe, por leitura, as três fontes de telemetria hoje isoladas (`tool_span`,
`request_log`, `audit_log`) numa única lista ordenada por `created_at`.
Read-time, não write-time: as três tabelas já persistem de forma independente
e com semânticas de falha diferentes — `tool_span`/`request_log` são
fire-and-forget (`telemetry/tracer.py`, `router/telemetry.py` — perder uma
linha é aceitável), `audit_log` é síncrona (`audit/store.py`). Espelhar as
três num quarto append-only novo exigiria um quarto ponto de escrita com o
mesmo risco de perda, sem eliminar a necessidade de nenhuma das três (cada
uma já tem seu próprio consumidor: `/api/telemetry/*`, `/api/metrics/*`,
`/api/audit`). Ver docs/proposals/plano-implementacao-auditoria-arquitetural.md,
Horizonte 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import AuditLogEntry, RequestLog, ToolSpan

TimelineKind = Literal["tool_span", "request_log", "audit_log"]


@dataclass(slots=True)
class TimelineEvent:
    ts: datetime
    kind: TimelineKind
    summary: str
    status: str
    detail: dict[str, Any]


async def session_timeline(
    session: AsyncSession, *, session_id: str, limit: int = 200
) -> list[TimelineEvent]:
    """Uma linha por evento de `tool_span`+`request_log`+`audit_log` desta
    sessão, ordenada por `created_at` crescente. `limit` é aplicado por fonte
    antes de mesclar — uma sessão com muita atividade numa fonte não afoga as
    outras duas."""
    spans = (
        (
            await session.execute(
                select(ToolSpan)
                .where(ToolSpan.session_id == session_id)
                .order_by(ToolSpan.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    requests = (
        (
            await session.execute(
                select(RequestLog)
                .where(RequestLog.session_id == session_id)
                .order_by(RequestLog.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    entries = (
        (
            await session.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.session_id == session_id)
                .order_by(AuditLogEntry.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    eventos: list[TimelineEvent] = []
    for span in spans:
        eventos.append(
            TimelineEvent(
                ts=span.created_at,
                kind="tool_span",
                summary=f"{span.kind}:{span.name}",
                status=span.status,
                detail={"latency_ms": span.latency_ms, "error": span.error},
            )
        )
    for req in requests:
        eventos.append(
            TimelineEvent(
                ts=req.created_at,
                kind="request_log",
                summary=req.resolved_model or req.requested_model,
                status=req.status,
                detail={
                    "provider": req.provider,
                    "total_tokens": req.total_tokens,
                    "cost_usd": float(req.cost_usd),
                    "cache_hit": req.cache_hit,
                    "latency_ms": req.latency_ms,
                },
            )
        )
    for entry in entries:
        eventos.append(
            TimelineEvent(
                ts=entry.created_at,
                kind="audit_log",
                summary=f"{entry.module}: {entry.action}",
                status=entry.status,
                detail={"risk_level": entry.risk_level, "details": entry.details},
            )
        )

    eventos.sort(key=lambda e: e.ts)
    return eventos
