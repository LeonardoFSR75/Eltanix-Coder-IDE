"""Teste de integração real para `agent/session_store.py` — cobre a lineage
`parent_session_id` usada pela orquestração multiagente (Fase E).

Pulado por padrão — ver a fixture `pg_session` em `conftest.py`.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from eltanix.agent import session_store
from eltanix.agent.runner import AgentRunner


def _session_id() -> str:
    return uuid.uuid4().hex[:12]


async def test_create_without_parent_defaults_to_none(pg_session):
    session_id = _session_id()
    await session_store.create(
        pg_session,
        session_id=session_id,
        project="proj",
        task="tarefa",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
    )
    await pg_session.flush()

    encontrados = await session_store.list_sessions(pg_session, project="proj")
    alvo = next(s for s in encontrados if s.session_id == session_id)
    assert alvo.parent_session_id is None


async def test_create_with_parent_persists_lineage(pg_session):
    pai_id = _session_id()
    filho_id = _session_id()
    await session_store.create(
        pg_session,
        session_id=pai_id,
        project="proj",
        task="tarefa pai",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
    )
    await session_store.create(
        pg_session,
        session_id=filho_id,
        project="proj",
        task="tarefa filho",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
        parent_session_id=pai_id,
    )
    await pg_session.flush()

    filhos = await session_store.list_sessions(pg_session, parent_session_id=pai_id)
    assert [s.session_id for s in filhos] == [filho_id]


async def test_list_sessions_without_parent_filter_returns_all(pg_session):
    pai_id = _session_id()
    filho_id = _session_id()
    projeto = f"proj-{uuid.uuid4().hex[:8]}"
    await session_store.create(
        pg_session,
        session_id=pai_id,
        project=projeto,
        task="pai",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
    )
    await session_store.create(
        pg_session,
        session_id=filho_id,
        project=projeto,
        task="filho",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
        parent_session_id=pai_id,
    )
    await pg_session.flush()

    todas = await session_store.list_sessions(pg_session, project=projeto)
    assert {s.session_id for s in todas} == {pai_id, filho_id}


async def test_create_persists_compact_session_summary(pg_session):
    session_id = _session_id()
    await session_store.create(
        pg_session,
        session_id=session_id,
        project="proj",
        task="tarefa com resumo",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
        summary="Aguardando aprovação de 2 ações e com 1 falha recorrente.",
    )
    await pg_session.flush()

    registro = await session_store.get(pg_session, session_id=session_id)
    assert registro is not None
    assert registro.summary == "Aguardando aprovação de 2 ações e com 1 falha recorrente."


async def test_reconnect_session_handles_closed_records(monkeypatch):
    fake_settings = SimpleNamespace(effective_projects_root="/tmp/projects")
    runner = AgentRunner(
        settings=fake_settings,
        engine=None,
        indexer=None,
        sandboxes=SimpleNamespace(),
    )

    registro = SimpleNamespace(
        project="demo",
        task="tarefa antiga",
        mode="agent",
        profile=None,
        parent_session_id=None,
        status="closed",
    )

    monkeypatch.setattr(session_store, "get", AsyncMock(return_value=registro))

    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    monkeypatch.setattr("eltanix.agent.runner.session_scope", fake_session_scope)
    monkeypatch.setattr("eltanix.workspace.projects.resolve", lambda root, project: Path("/tmp/projects/demo"))
    created = object()

    async def fake_create_session(**kwargs):
        assert kwargs["session_id"] == "abc123"
        assert kwargs["task"] == "tarefa antiga"
        assert kwargs["workspace_root"] == Path("/tmp/projects/demo")
        return created

    monkeypatch.setattr(runner, "create_session", fake_create_session)

    result = await runner.reconnect_session("abc123")
    assert result is created
