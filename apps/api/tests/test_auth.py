"""Autenticação de sessão: hashing de senha, persistência e a dependência
`require_session` que substitui `require_api_key` como `AuthDep`.

Testes de `store.py` usam `pg_session` (Postgres real, isolado por transação
com rollback) — mesmo padrão de `test_hybrid_search.py`. Testes de
`require_session` chamam a dependência diretamente, como
`test_security_pentest.py::test_require_api_key_enforcement` já faz para a
função antiga.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from sicoobito.api.deps import require_session
from sicoobito.auth import store
from sicoobito.auth.service import _hash_password, _hash_token, _verify_password
from sicoobito.config import get_settings

# ── Hashing (unitário, sem banco) ──────────────────────────────────────────


def test_hash_password_roundtrip():
    hashed = _hash_password("senha-forte-123")
    assert _verify_password("senha-forte-123", hashed)
    assert not _verify_password("senha-errada", hashed)


def test_hash_password_uses_random_salt():
    assert _hash_password("mesma-senha") != _hash_password("mesma-senha")


def test_hash_token_is_deterministic_and_never_the_token_itself():
    token = "token-de-exemplo"
    assert _hash_token(token) == _hash_token(token)
    assert _hash_token(token) != token


# ── Store (contra Postgres real, isolado por transação) ────────────────────


async def test_create_and_authenticate_user(pg_session):
    username = f"user-{uuid.uuid4().hex[:8]}"
    await store.create_user(
        pg_session,
        username=username,
        password_hash=_hash_password("segredo123"),
        display_name="Teste",
    )
    user = await store.get_user_by_username(pg_session, username)
    assert user is not None
    assert _verify_password("segredo123", user.password_hash)
    assert not _verify_password("errada", user.password_hash)


async def test_get_user_by_username_ignores_inactive(pg_session):
    username = f"user-{uuid.uuid4().hex[:8]}"
    user = await store.create_user(
        pg_session, username=username, password_hash=_hash_password("x")
    )
    user.is_active = False
    await pg_session.flush()
    assert await store.get_user_by_username(pg_session, username) is None


async def test_count_users_reflects_inserts(pg_session):
    antes = await store.count_users(pg_session)
    await store.create_user(
        pg_session, username=f"user-{uuid.uuid4().hex[:8]}", password_hash=_hash_password("x")
    )
    assert await store.count_users(pg_session) == antes + 1


async def test_session_created_found_and_revoked(pg_session):
    user = await store.create_user(
        pg_session, username=f"user-{uuid.uuid4().hex[:8]}", password_hash=_hash_password("x")
    )
    token_hash = _hash_token("token-de-teste")
    expires_at = datetime.now(UTC) + timedelta(days=1)
    await store.create_session(
        pg_session, user_id=user.id, token_hash=token_hash, expires_at=expires_at
    )

    encontrada = await store.get_session_by_token_hash(pg_session, token_hash)
    assert encontrada is not None
    assert encontrada.revoked_at is None

    await store.revoke_session(pg_session, encontrada, now=datetime.now(UTC))
    assert encontrada.revoked_at is not None


async def test_touch_session_updates_last_seen(pg_session):
    user = await store.create_user(
        pg_session, username=f"user-{uuid.uuid4().hex[:8]}", password_hash=_hash_password("x")
    )
    token_hash = _hash_token("outro-token")
    auth_session = await store.create_session(
        pg_session,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert auth_session.last_seen_at is None
    agora = datetime.now(UTC)
    await store.touch_session(pg_session, auth_session, now=agora)
    assert auth_session.last_seen_at == agora


# ── require_session (dependência viva de `AuthDep`) ────────────────────────


def _settings_with_key(key: str):
    settings = get_settings()
    original = settings.api_key
    settings.api_key = key
    return settings, original


def _fake_request(auth_service: object | None) -> SimpleNamespace:
    # `request.state` (não `request.app.state`) é onde `require_session` grava
    # `actor` para `identify_actor` ler depois — ver `api/deps.py`.
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(auth=auth_service)),
        state=SimpleNamespace(),
    )


async def test_require_session_rejects_without_any_credential():
    settings, original = _settings_with_key("chave-secreta")
    try:
        with pytest.raises(HTTPException) as exc_info:
            await require_session(
                request=_fake_request(None),
                settings=settings,
                authorization=None,
                x_api_key=None,
                sicoobito_session=None,
            )
        assert exc_info.value.status_code == 401
    finally:
        settings.api_key = original


async def test_require_session_accepts_the_service_api_key():
    settings, original = _settings_with_key("chave-secreta")
    try:
        await require_session(
            request=_fake_request(None),
            settings=settings,
            authorization="Bearer chave-secreta",
            x_api_key=None,
            sicoobito_session=None,
        )
    finally:
        settings.api_key = original


async def test_require_session_never_opens_up_just_because_no_api_key_is_set():
    """A diferença central em relação a `require_api_key`: sem chave de
    serviço configurada, `require_session` não abre a API — ela passa a
    depender só da sessão de usuário, e sem uma sessão válida continua 401."""
    settings, original = _settings_with_key("")
    try:
        with pytest.raises(HTTPException) as exc_info:
            await require_session(
                request=_fake_request(None),
                settings=settings,
                authorization=None,
                x_api_key=None,
                sicoobito_session=None,
            )
        assert exc_info.value.status_code == 401
    finally:
        settings.api_key = original


async def test_require_session_accepts_a_valid_session_cookie():
    settings, original = _settings_with_key("")
    try:
        auth = SimpleNamespace(validate_session=_always_valid_user)
        await require_session(
            request=_fake_request(auth),
            settings=settings,
            authorization=None,
            x_api_key=None,
            sicoobito_session="token-valido",
        )
    finally:
        settings.api_key = original


async def test_require_session_rejects_an_invalid_session_cookie():
    settings, original = _settings_with_key("")
    try:
        auth = SimpleNamespace(validate_session=_always_invalid_user)
        with pytest.raises(HTTPException) as exc_info:
            await require_session(
                request=_fake_request(auth),
                settings=settings,
                authorization=None,
                x_api_key=None,
                sicoobito_session="token-invalido",
            )
        assert exc_info.value.status_code == 401
    finally:
        settings.api_key = original


async def _always_valid_user(_token: str) -> object:
    return SimpleNamespace(id=uuid.uuid4(), username="teste", is_admin=False)


async def _always_invalid_user(_token: str) -> None:
    return None


# ── Novas funcionalidades (Troca de senha, Purga, Rate Limit) ──────────────


async def test_purge_expired_sessions(pg_session):
    user = await store.create_user(
        pg_session, username=f"user-{uuid.uuid4().hex[:8]}", password_hash=_hash_password("x")
    )
    agora = datetime.now(UTC)

    # Sessão expirada
    await store.create_session(
        pg_session,
        user_id=user.id,
        token_hash=_hash_token("expirada"),
        expires_at=agora - timedelta(minutes=10),
    )
    # Sessão revogada
    sess_rev = await store.create_session(
        pg_session,
        user_id=user.id,
        token_hash=_hash_token("revogada"),
        expires_at=agora + timedelta(days=1),
    )
    await store.revoke_session(pg_session, sess_rev, now=agora)

    # Sessão válida
    await store.create_session(
        pg_session,
        user_id=user.id,
        token_hash=_hash_token("valida"),
        expires_at=agora + timedelta(days=1),
    )

    purged = await store.purge_expired_sessions(pg_session, now=agora)
    assert purged == 2
    assert await store.get_session_by_token_hash(pg_session, _hash_token("valida")) is not None


async def test_change_password_store(pg_session):
    username = f"user-{uuid.uuid4().hex[:8]}"
    user = await store.create_user(
        pg_session,
        username=username,
        password_hash=_hash_password("senha-antiga-123"),
        display_name="Teste",
    )

    # Troca de senha
    nova_hash = _hash_password("senha-nova-456")
    await store.update_user_password(pg_session, user, password_hash=nova_hash)

    user_refreshed = await store.get_user(pg_session, user.id)
    assert user_refreshed is not None
    assert _verify_password("senha-nova-456", user_refreshed.password_hash)
    assert not _verify_password("senha-antiga-123", user_refreshed.password_hash)


async def test_rate_limiting_in_memory():
    from sicoobito.auth.service import AuthService

    service = AuthService()
    ip = "192.168.1.100"

    for _ in range(5):
        assert await service.check_and_register_attempt(ip)

    assert not await service.check_and_register_attempt(ip)
    await service.reset_failed_attempts(ip)
    assert await service.check_and_register_attempt(ip)

