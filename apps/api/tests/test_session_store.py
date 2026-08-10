"""Teste de integração real para `agent/session_store.py` — cobre a lineage
`parent_session_id` usada pela orquestração multiagente (Fase E).

Pulado por padrão — ver a fixture `pg_session` em `conftest.py`.
"""

from __future__ import annotations

import uuid

from sicoobito.agent import session_store


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
