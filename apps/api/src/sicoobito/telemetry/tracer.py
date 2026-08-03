"""Registro em memória de spans de execução: ferramentas do agente e buscas RAG.

Efêmero por design — não sobrevive a um restart, e não precisa: chamadas de
LLM já têm registro durável em `router/telemetry.py::TelemetryEntry`
(Postgres, por request) e `router/health.py::HealthTracker` (p50/p95 por
modelo, Redis). Este buffer cobre o que não tinha nenhum registro: quanto
tempo uma ferramenta do agente ou uma busca RAG levou, e se deu certo.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

TraceKind = Literal["tool", "rag"]
TraceStatus = Literal["ok", "error"]


@dataclass(slots=True)
class TraceEntry:
    ts: float
    kind: TraceKind
    name: str
    latency_ms: float
    status: TraceStatus
    session_id: str = ""
    error: str | None = None


class TraceRecorder:
    """Buffer circular das últimas execuções — visibilidade operacional, não
    auditoria (para isso existe `audit/`) nem contabilidade de custo (para
    isso existe `router/telemetry.py`)."""

    def __init__(self, maxlen: int = 500) -> None:
        self._entries: deque[TraceEntry] = deque(maxlen=maxlen)

    def record(
        self,
        *,
        kind: TraceKind,
        name: str,
        latency_ms: float,
        status: TraceStatus,
        session_id: str = "",
        error: str | None = None,
    ) -> None:
        entry = TraceEntry(
            ts=time.time(),
            kind=kind,
            name=name,
            latency_ms=round(latency_ms, 2),
            status=status,
            session_id=session_id,
            error=error[:300] if error else None,
        )
        self._entries.append(entry)
        log.info(
            "telemetry.span", kind=kind, name=name, latency_ms=entry.latency_ms, status=status
        )

    def recent(self, limit: int = 100) -> list[TraceEntry]:
        """Mais recente primeiro."""
        return list(self._entries)[::-1][:limit]
