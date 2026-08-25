"""`AuditService.record_approvals`: distingue auto-aprovação por política de
decisão humana no log de auditoria — sem isso, as duas ficariam
indistinguíveis e uma auto-aprovação passaria por "foi revisada".

Sem Postgres real: `session_scope`/`store.record` são trocados por fakes que
só capturam os argumentos, já que o serviço abre sua própria sessão e não
aceita uma injetada (mesmo padrão de `router/telemetry.py::record`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from novaai_studio.audit import service as audit_service_module
from novaai_studio.audit.service import AuditService


class _FakeSession:
    pass


@pytest.fixture
def capturado(monkeypatch):
    chamadas: list[dict] = []

    @asynccontextmanager
    async def _fake_session_scope():
        yield _FakeSession()

    async def _fake_record(session, **kwargs):
        chamadas.append(kwargs)
        return None

    monkeypatch.setattr(audit_service_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(audit_service_module.store, "record", _fake_record)
    return chamadas


async def test_policy_decision_is_recorded_with_distinct_actor(capturado):
    service = AuditService()
    pending = [
        {"tool_call_id": "call1", "tool": "edit_file", "risk": "write", "summary": "editar x"}
    ]
    await service.record_approvals(
        session_id="s1",
        pending=pending,
        approvals={"call1": True},
        reasons={"call1": "auto-aprovado por política: edição em *.md"},
        decided_by={"call1": "policy"},
    )

    assert len(capturado) == 1
    assert capturado[0]["actor"] == "política"
    assert capturado[0]["metadata"]["reason"] == "auto-aprovado por política: edição em *.md"
    assert capturado[0]["metadata"]["auto_approved"] is True


async def test_human_decision_keeps_agente_as_actor(capturado):
    service = AuditService()
    pending = [
        {"tool_call_id": "call1", "tool": "edit_file", "risk": "write", "summary": "editar x"}
    ]
    await service.record_approvals(
        session_id="s1",
        pending=pending,
        approvals={"call1": True},
        reasons={},
        decided_by={"call1": "human"},
    )

    assert capturado[0]["actor"] == "agente"
    assert capturado[0]["metadata"]["reason"] == ""
    assert capturado[0]["metadata"]["auto_approved"] is False


async def test_missing_decided_by_defaults_to_human_actor(capturado):
    # Sem `decided_by` (chamador antigo, ou nenhuma decisão registrada ainda)
    # o comportamento não pode virar "política" por omissão.
    service = AuditService()
    pending = [
        {"tool_call_id": "call1", "tool": "run_command", "risk": "exec", "summary": "rodar x"}
    ]
    await service.record_approvals(
        session_id="s1",
        pending=pending,
        approvals={"call1": False},
        reasons={"call1": "recusado"},
    )

    assert capturado[0]["actor"] == "agente"
    assert capturado[0]["status"] == "denied"
    assert capturado[0]["metadata"]["auto_approved"] is False
