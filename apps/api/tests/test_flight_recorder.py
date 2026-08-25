"""`telemetry/flight_recorder.py::session_timeline` — mescla `tool_span`,
`request_log` e `audit_log` por `session_id`, ordenado por `created_at`.

Integração real — usa a fixture `pg_session` (`conftest.py`), pulada por
padrão sem `DATABASE_URL_TEST`. Sem isso não há como testar de verdade a
ordenação entre três tabelas com `server_default=func.now()` cada.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from novaai_studio.db.models import AuditLogEntry, RequestLog, ToolSpan
from novaai_studio.telemetry.flight_recorder import session_timeline


def _session_id() -> str:
    return uuid.uuid4().hex[:12]


async def test_session_timeline_merges_and_sorts_the_three_sources(pg_session):
    sid = _session_id()
    outra_sessao = _session_id()
    t0 = datetime.now(UTC)

    pg_session.add(
        ToolSpan(
            created_at=t0,
            kind="tool",
            name="list_files",
            latency_ms=12.0,
            status="ok",
            session_id=sid,
        )
    )
    pg_session.add(
        RequestLog(
            created_at=t0 + timedelta(seconds=1),
            requested_model="coding",
            resolved_model="anthropic/claude-sonnet-5",
            status="ok",
            session_id=sid,
        )
    )
    pg_session.add(
        AuditLogEntry(
            created_at=t0 + timedelta(seconds=2),
            actor="agente",
            module="Security",
            action="Decisão de aprovação de ferramenta",
            session_id=sid,
        )
    )
    # Ruído de outra sessão — não deve aparecer na timeline.
    pg_session.add(
        ToolSpan(
            created_at=t0,
            kind="tool",
            name="write_file",
            latency_ms=5.0,
            status="ok",
            session_id=outra_sessao,
        )
    )
    await pg_session.flush()

    eventos = await session_timeline(pg_session, session_id=sid)

    assert [e.kind for e in eventos] == ["tool_span", "request_log", "audit_log"]
    assert eventos[0].summary == "tool:list_files"
    assert eventos[1].summary == "anthropic/claude-sonnet-5"
    assert eventos[1].detail["cost_usd"] == 0.0
    assert eventos[2].summary == "Security: Decisão de aprovação de ferramenta"
    # ordem estritamente crescente por `ts`
    assert eventos[0].ts < eventos[1].ts < eventos[2].ts


async def test_session_timeline_unknown_session_is_empty(pg_session):
    assert await session_timeline(pg_session, session_id="nao-existe") == []
