"""Persistência de usuário e sessão. Mesmo padrão de `documents/store.py` e
`notes/store.py`: funções que só pedem um `AsyncSession`, sem `session_scope()`
próprio — é o que permite testá-las direto contra a fixture `pg_session`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.db.models import AppUser, AuthSession


async def count_users(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(AppUser.id)))).scalar() or 0


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password_hash: str,
    display_name: str | None = None,
) -> AppUser:
    user = AppUser(username=username, password_hash=password_hash, display_name=display_name)
    session.add(user)
    await session.flush()
    return user


async def update_user_password(
    session: AsyncSession, user: AppUser, *, password_hash: str
) -> None:
    user.password_hash = password_hash
    await session.flush()


async def get_user_by_username(session: AsyncSession, username: str) -> AppUser | None:
    return await session.scalar(
        select(AppUser).where(AppUser.username == username, AppUser.is_active)
    )


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> AppUser | None:
    return await session.get(AppUser, user_id)


async def create_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
) -> AuthSession:
    auth_session = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent[:512] if user_agent else None,
    )
    session.add(auth_session)
    await session.flush()
    return auth_session


async def get_session_by_token_hash(session: AsyncSession, token_hash: str) -> AuthSession | None:
    return await session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))


async def touch_session(
    session: AsyncSession, auth_session: AuthSession, *, now: datetime
) -> None:
    auth_session.last_seen_at = now


async def revoke_session(
    session: AsyncSession, auth_session: AuthSession, *, now: datetime
) -> None:
    auth_session.revoked_at = now


async def purge_expired_sessions(session: AsyncSession, *, now: datetime) -> int:
    """Remove registros de sessão onde a data de expiração já passou ou a sessão
    foi revogada."""
    stmt = delete(AuthSession).where(
        or_(
            AuthSession.expires_at < now,
            AuthSession.revoked_at.is_not(None),
        )
    )
    result = await session.execute(stmt)
    return result.rowcount or 0

