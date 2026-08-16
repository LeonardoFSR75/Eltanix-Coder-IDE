"""`auth/rbac.py` + a fatia de `auth/store.py` que sustenta `project_member`
(Horizonte 2, ver docs/proposals/plano-implementacao-auditoria-arquitetural.md).

Integração real — usa a fixture `pg_session` (`conftest.py`), pulada por
padrão sem `DATABASE_URL_TEST`. `require_role`/`require_role_by_slug` fazem
`SELECT`s reais contra `project_member`/`project_record`, então testá-los
contra SQLite ou mock não pegaria erro de FK/constraint de verdade.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from sicoobito.auth import store
from sicoobito.auth.rbac import get_role, require_role, require_role_by_slug
from sicoobito.db.models import AppUser, ProjectRecord


def _request(*, user_id: uuid.UUID | None = None, is_admin: bool = False, is_service: bool = False):
    return SimpleNamespace(
        state=SimpleNamespace(user_id=user_id, is_admin=is_admin, is_service=is_service)
    )


async def _make_project(pg_session, *, slug: str | None = None) -> ProjectRecord:
    rec = ProjectRecord(slug=slug or f"proj-{uuid.uuid4().hex[:8]}", name="Projeto de teste")
    pg_session.add(rec)
    await pg_session.flush()
    return rec


async def _make_user(pg_session, *, is_admin: bool = False) -> AppUser:
    user = AppUser(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        is_admin=is_admin,
    )
    pg_session.add(user)
    await pg_session.flush()
    return user


async def test_require_role_allows_when_member_has_enough_rank(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)
    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="editor")

    await require_role(
        pg_session, _request(user_id=usuario.id), project_id=projeto.id, min_role="viewer"
    )
    await require_role(
        pg_session, _request(user_id=usuario.id), project_id=projeto.id, min_role="editor"
    )


async def test_require_role_denies_when_rank_is_too_low(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)
    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="viewer")

    with pytest.raises(HTTPException) as exc_info:
        await require_role(
            pg_session, _request(user_id=usuario.id), project_id=projeto.id, min_role="owner"
        )
    assert exc_info.value.status_code == 403


async def test_require_role_denies_non_member(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)

    with pytest.raises(HTTPException) as exc_info:
        await require_role(
            pg_session, _request(user_id=usuario.id), project_id=projeto.id, min_role="viewer"
        )
    assert exc_info.value.status_code == 403


async def test_require_role_denies_when_no_user_id(pg_session):
    projeto = await _make_project(pg_session)

    with pytest.raises(HTTPException) as exc_info:
        await require_role(
            pg_session, _request(user_id=None), project_id=projeto.id, min_role="viewer"
        )
    assert exc_info.value.status_code == 403


async def test_require_role_bypasses_for_service_channel(pg_session):
    projeto = await _make_project(pg_session)

    # Sem `user_id`, sem membership — só o bypass de serviço permite passar.
    await require_role(
        pg_session, _request(is_service=True), project_id=projeto.id, min_role="owner"
    )


async def test_require_role_bypasses_for_instance_admin(pg_session):
    projeto = await _make_project(pg_session)
    admin = await _make_user(pg_session, is_admin=True)

    # Admin da instância não precisa ser membro do projeto.
    await require_role(
        pg_session,
        _request(user_id=admin.id, is_admin=True),
        project_id=projeto.id,
        min_role="owner",
    )


async def test_require_role_by_slug_noop_when_slug_is_none(pg_session):
    # Conteúdo global (sem projeto) — não há papel "global" para checar.
    await require_role_by_slug(
        pg_session, _request(user_id=uuid.uuid4()), project_slug=None, min_role="owner"
    )


async def test_require_role_by_slug_noop_when_slug_is_unregistered(pg_session):
    # Slug que não bate com nenhum ProjectRecord — mesmo comportamento
    # tolerante que essas rotas já tinham para projeto ad-hoc/inexistente.
    await require_role_by_slug(
        pg_session,
        _request(user_id=uuid.uuid4()),
        project_slug="projeto-nunca-registrado",
        min_role="owner",
    )


async def test_require_role_by_slug_enforces_when_project_exists(pg_session):
    projeto = await _make_project(pg_session, slug="projeto-com-dono")
    usuario = await _make_user(pg_session)
    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="viewer")

    with pytest.raises(HTTPException) as exc_info:
        await require_role_by_slug(
            pg_session,
            _request(user_id=usuario.id),
            project_slug="projeto-com-dono",
            min_role="editor",
        )
    assert exc_info.value.status_code == 403

    await require_role_by_slug(
        pg_session,
        _request(user_id=usuario.id),
        project_slug="projeto-com-dono",
        min_role="viewer",
    )


async def test_get_role_returns_none_for_non_member(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)
    assert await get_role(pg_session, project_id=projeto.id, user_id=usuario.id) is None


async def test_add_member_upserts_role(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)

    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="viewer")
    assert await get_role(pg_session, project_id=projeto.id, user_id=usuario.id) == "viewer"

    # Segunda chamada com papel diferente atualiza em vez de duplicar linha.
    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="owner")
    assert await get_role(pg_session, project_id=projeto.id, user_id=usuario.id) == "owner"
    assert len(await store.list_members(pg_session, project_id=projeto.id)) == 1


async def test_remove_member(pg_session):
    projeto = await _make_project(pg_session)
    usuario = await _make_user(pg_session)
    await store.add_member(pg_session, project_id=projeto.id, user_id=usuario.id, role="editor")

    assert await store.remove_member(pg_session, project_id=projeto.id, user_id=usuario.id) is True
    assert await get_role(pg_session, project_id=projeto.id, user_id=usuario.id) is None
    # Remover de novo (já removido) não deve levantar, só reportar que não fez nada.
    assert await store.remove_member(pg_session, project_id=projeto.id, user_id=usuario.id) is False


async def test_list_member_project_ids(pg_session):
    usuario = await _make_user(pg_session)
    projeto_a = await _make_project(pg_session)
    projeto_b = await _make_project(pg_session)
    outro_projeto = await _make_project(pg_session)

    await store.add_member(pg_session, project_id=projeto_a.id, user_id=usuario.id, role="viewer")
    await store.add_member(pg_session, project_id=projeto_b.id, user_id=usuario.id, role="owner")

    ids = await store.list_member_project_ids(pg_session, user_id=usuario.id)
    assert set(ids) == {projeto_a.id, projeto_b.id}
    assert outro_projeto.id not in ids
