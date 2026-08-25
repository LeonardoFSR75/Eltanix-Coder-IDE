"""Registro de spans de execução: ferramentas do agente e buscas RAG.

Buffer circular com persistência opcional no Redis (se disponível).
Sobrevive a restarts quando o Redis está ativo e degrada suavemente para a memória.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

TraceKind = Literal["tool", "rag"]
TraceStatus = Literal["ok", "error"]

_REDIS_KEY = "eltanix:telemetry:spans"


@dataclass(slots=True)
class TraceEntry:
    ts: float
    kind: TraceKind
    name: str
    latency_ms: float
    status: TraceStatus
    session_id: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "name": self.name,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "session_id": self.session_id,
            "error": self.error,
        }

    def to_otlp_json(self) -> dict:
        """Formata o span no padrão OpenTelemetry Trace JSON (OTLP v1)."""
        start_nano = int(self.ts * 1e9)
        end_nano = int((self.ts + (self.latency_ms / 1000.0)) * 1e9)
        return {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "eltanix-api"}},
                    {"key": "service.version", "value": {"stringValue": "0.1.0"}},
                ]
            },
            "scopeSpans": [
                {
                    "scope": {"name": f"eltanix.{self.kind}"},
                    "spans": [
                        {
                            "traceId": self.session_id.ljust(32, "0")
                            if self.session_id
                            else "0" * 32,
                            "spanId": hex(hash((self.name, self.ts)))[2:].zfill(16)[:16],
                            "name": self.name,
                            "kind": 1,  # SPAN_KIND_INTERNAL
                            "startTimeUnixNano": str(start_nano),
                            "endTimeUnixNano": str(end_nano),
                            "attributes": [
                                {"key": "eltanix.kind", "value": {"stringValue": self.kind}},
                                {
                                    "key": "eltanix.status",
                                    "value": {"stringValue": self.status},
                                },
                                {
                                    "key": "eltanix.session_id",
                                    "value": {"stringValue": self.session_id},
                                },
                            ],
                            "status": {
                                "code": 1 if self.status == "ok" else 2,
                                "message": self.error or "",
                            },
                        }
                    ],
                }
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TraceEntry:
        return cls(
            ts=float(d.get("ts", 0)),
            kind=d.get("kind", "tool"),
            name=str(d.get("name", "")),
            latency_ms=float(d.get("latency_ms", 0)),
            status=d.get("status", "ok"),
            session_id=str(d.get("session_id", "")),
            error=d.get("error"),
        )


class TraceRecorder:
    """Buffer circular das últimas execuções com persistência em Redis opcional."""

    def __init__(self, maxlen: int = 500, redis: Redis | None = None) -> None:
        self.maxlen = maxlen
        self._redis = redis
        self._entries: deque[TraceEntry] = deque(maxlen=maxlen)
        self._background_tasks: set[asyncio.Task[None]] = set()

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
        log.info("telemetry.span", kind=kind, name=name, latency_ms=entry.latency_ms, status=status)

        if self._redis is not None:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._persist_redis(entry))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                pass

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._persist_postgres(entry))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            pass

    async def _persist_redis(self, entry: TraceEntry) -> None:
        if self._redis is None:
            return
        try:
            payload = json.dumps(entry.to_dict())
            await self._redis.lpush(_REDIS_KEY, payload)
            await self._redis.ltrim(_REDIS_KEY, 0, self.maxlen - 1)
        except Exception as exc:
            log.warning("telemetry.redis_persist_failed", error=str(exc)[:200])

    async def _persist_postgres(self, entry: TraceEntry) -> None:
        # Import local: evita ciclo de import no módulo (tracer.py é usado por
        # serviços que db/models.py também acaba puxando indiretamente) e
        # mantém este módulo importável mesmo sem `db` configurado em testes.
        from eltanix.db.models import ToolSpan
        from eltanix.db.session import session_scope

        try:
            async with session_scope() as session:
                session.add(
                    ToolSpan(
                        kind=entry.kind,
                        name=entry.name[:255],
                        latency_ms=entry.latency_ms,
                        status=entry.status,
                        session_id=entry.session_id or None,
                        error=entry.error,
                    )
                )
        except Exception as exc:
            # "Perder telemetria é aceitável" (mesmo espírito de router/telemetry.py)
            # — nunca propaga e derruba quem chamou record().
            log.warning("telemetry.postgres_persist_failed", error=str(exc)[:200])

    async def recent_async(self, limit: int = 100) -> list[TraceEntry]:
        """Mais recente primeiro. Consulta Redis se disponível, caindo para memória."""
        if self._redis is not None:
            try:
                raw_list = await self._redis.lrange(_REDIS_KEY, 0, limit - 1)
                if raw_list:
                    res = []
                    for item in raw_list:
                        data = json.loads(item)
                        res.append(TraceEntry.from_dict(data))
                    return res
            except Exception as exc:
                log.warning("telemetry.redis_read_failed", error=str(exc)[:200])

        return self.recent(limit=limit)

    def recent(self, limit: int = 100) -> list[TraceEntry]:
        """Mais recente primeiro (versão síncrona em memória)."""
        return list(self._entries)[::-1][:limit]
