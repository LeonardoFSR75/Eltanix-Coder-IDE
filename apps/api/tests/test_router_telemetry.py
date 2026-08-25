"""`router/telemetry.py::record()` — grava `TelemetryEntry` em `request_log`.

Integração real — usa a fixture `pg_session` (`conftest.py`), pulada por
padrão sem `DATABASE_URL_TEST`. Cobre especificamente `session_id`, a coluna
nova do item "Agent Flight Recorder v1" (Horizonte 2): sem isto o closure
`record()` em `RouterEngine.complete/stream/embed` (`router/engine.py`)
poderia estar montando o `TelemetryEntry` certo mas `record()` silenciosamente
descartando o campo na hora de persistir.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select

from eltanix.db.models import RequestLog
from eltanix.router.telemetry import TelemetryEntry, record


def _session_id() -> str:
    return uuid.uuid4().hex[:12]


async def test_record_persists_session_id(pg_session, monkeypatch):
    @asynccontextmanager
    async def fake_session_scope():
        yield pg_session

    monkeypatch.setattr("eltanix.router.telemetry.session_scope", fake_session_scope)

    sid = _session_id()
    await record(
        TelemetryEntry(
            requested_model="coding",
            resolved_model="anthropic/claude-sonnet-5",
            source="agent:agent",
            session_id=sid,
        )
    )
    await pg_session.flush()

    linha = (
        await pg_session.execute(select(RequestLog).where(RequestLog.session_id == sid))
    ).scalar_one()
    assert linha.resolved_model == "anthropic/claude-sonnet-5"


async def test_record_without_session_id_leaves_it_null(pg_session, monkeypatch):
    @asynccontextmanager
    async def fake_session_scope():
        yield pg_session

    monkeypatch.setattr("eltanix.router.telemetry.session_scope", fake_session_scope)

    marcador = f"unit-test-{uuid.uuid4().hex[:8]}"
    await record(TelemetryEntry(requested_model=marcador, source="unit-test"))
    await pg_session.flush()

    linha = (
        await pg_session.execute(select(RequestLog).where(RequestLog.requested_model == marcador))
    ).scalar_one()
    assert linha.session_id is None
