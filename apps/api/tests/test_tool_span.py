"""Teste de integração real para `telemetry/store.py::list_spans` — a metade
durável de `TraceRecorder` (ver `tests/test_telemetry.py` para o buffer em
memória, que não precisa de Postgres).

Pulado por padrão — ver a fixture `pg_session` em `conftest.py`.
"""

from __future__ import annotations

import uuid

from eltanix.db.models import ToolSpan
from eltanix.telemetry import store as telemetry_store


async def test_list_spans_returns_most_recent_first(pg_session):
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    pg_session.add_all(
        [
            ToolSpan(kind="tool", name="a", latency_ms=1.0, status="ok", session_id=session_id),
            ToolSpan(kind="tool", name="b", latency_ms=2.0, status="ok", session_id=session_id),
        ]
    )
    await pg_session.flush()

    spans = await telemetry_store.list_spans(pg_session, session_id=session_id)
    assert [s.name for s in spans] == ["b", "a"]


async def test_list_spans_filters_by_kind(pg_session):
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    pg_session.add_all(
        [
            ToolSpan(
                kind="tool", name="write_file", latency_ms=1.0, status="ok", session_id=session_id
            ),
            ToolSpan(
                kind="rag", name="documents", latency_ms=2.0, status="ok", session_id=session_id
            ),
        ]
    )
    await pg_session.flush()

    spans = await telemetry_store.list_spans(pg_session, session_id=session_id, kind="rag")
    assert [s.name for s in spans] == ["documents"]


async def test_list_spans_respects_limit(pg_session):
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    pg_session.add_all(
        [
            ToolSpan(kind="tool", name=f"t{i}", latency_ms=1.0, status="ok", session_id=session_id)
            for i in range(5)
        ]
    )
    await pg_session.flush()

    spans = await telemetry_store.list_spans(pg_session, session_id=session_id, limit=2)
    assert len(spans) == 2
