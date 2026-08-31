"""Persistência de usuário, sessão e papel por projeto (`project_member`).
Mesmo padrão de `documents/store.py` e `notes/store.py`: funções que só pedem
um `AsyncSession`, sem `session_scope()` próprio — é o que permite testá-las
direto contra a fixture `pg_session`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.db.models import AppUser, AuthSession, ProjectMember


async def count_users(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(AppUser.id)))).scalar() or 0


async def list_users(session: AsyncSession) -> list[AppUser]:
    return list((await session.execute(select(AppUser).order_by(AppUser.username))).scalars())


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


async def update_user_password(session: AsyncSession, user: AppUser, *, password_hash: str) -> None:
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


async def touch_session(session: AsyncSession, auth_session: AuthSession, *, now: datetime) -> None:
    auth_session.last_seen_at = now


async def revoke_session(
    session: AsyncSession, auth_session: AuthSession, *, now: datetime
) -> None:
    auth_session.revoked_at = now


async def revoke_other_sessions(
    session: AsyncSession, *, user_id: uuid.UUID, keep_token_hash: str | None, now: datetime
) -> int:
    """Revoga toda sessão ativa do usuário, exceto (opcionalmente) a que fez a
    própria chamada — usado na troca de senha, para que um token roubado não
    continue valendo depois que o usuário legítimo trocou a senha."""
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_token_hash is not None:
        stmt = stmt.where(AuthSession.token_hash != keep_token_hash)
    sessions = (await session.execute(stmt)).scalars().all()
    for auth_session in sessions:
        auth_session.revoked_at = now
    return len(sessions)


async def purge_expired_sessions(session: AsyncSession, *, now: datetime) -> int:
    """Remove registros de sessão onde a data de expiração já passou ou a sessão
    foi revogada."""
    stmt = delete(AuthSession).where(
        or_(
            AuthSession.expires_at < now,
            AuthSession.revoked_at.is_not(None),
        )
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    return result.rowcount or 0


# --- project_member: papel de usuário por projeto (RBAC, ver auth/rbac.py) ---


async def get_member(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember | None:
    return await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )


async def list_members(session: AsyncSession, *, project_id: uuid.UUID) -> list[ProjectMember]:
    stmt = select(ProjectMember).where(ProjectMember.project_id == project_id)
    return list((await session.execute(stmt)).scalars())


async def list_member_project_ids(session: AsyncSession, *, user_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    return list((await session.execute(stmt)).scalars())


async def add_member(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> ProjectMember:
    """`upsert` manual em vez de `ON CONFLICT`: o volume aqui (convites) não
    justifica SQL específico do Postgres — ver `uq_project_member_project_user`
    (`db/models.py`) para a constraint que este caminho respeita na prática."""
    existing = await get_member(session, project_id=project_id, user_id=user_id)
    if existing is not None:
        existing.role = role
        await session.flush()
        return existing
    member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    session.add(member)
    await session.flush()
    return member


async def remove_member(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    member = await get_member(session, project_id=project_id, user_id=user_id)
    if member is None:
        return False
    await session.delete(member)
    await session.flush()
    return True
