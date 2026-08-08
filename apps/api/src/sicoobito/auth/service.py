"""Orquestração de autenticação — etapa 1 do login obrigatório.

Um único usuário seed por enquanto (ver `ensure_seed_user`, chamado no
lifespan), sem RBAC. Senha em `scrypt` (stdlib — nenhuma dependência nova, e
evita wheel nativo em ambiente Windows sem MSVC Build Tools); token de sessão
opaco, só o hash (`sha256`) fica no banco, igual `require_api_key` já faz
para a chave de API de serviço via `hmac.compare_digest`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sicoobito.auth import store
from sicoobito.db.models import AppUser
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

SESSION_TTL = timedelta(days=14)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"{salt.hex()}${derived.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_hex, _ = password_hash.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    candidate = _hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, password_hash)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self) -> None:
        self._memory_attempts: dict[str, list[datetime]] = {}

    async def check_rate_limit(self, ip: str, redis: Any | None = None) -> bool:
        """Verifica se o IP excedeu o limite de 5 tentativas por minuto.

        Usa Redis se disponível; caso contrário, usa contador em memória local.
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(seconds=60)

        if redis is not None:
            try:
                key = f"auth:ratelimit:{ip}"
                count = await redis.get(key)
                if count and int(count) >= 5:
                    return False
                return True
            except Exception as exc:
                log.warning("auth.ratelimit.redis_failed", error=str(exc)[:200])

        attempts = [t for t in self._memory_attempts.get(ip, []) if t > window_start]
        self._memory_attempts[ip] = attempts
        return len(attempts) < 5

    async def record_failed_attempt(self, ip: str, redis: Any | None = None) -> None:
        """Registra uma tentativa malsucedida de login para o IP fornecido."""
        now = datetime.now(UTC)
        if redis is not None:
            try:
                key = f"auth:ratelimit:{ip}"
                pipe = redis.pipeline()
                await pipe.incr(key)
                await pipe.expire(key, 60)
                await pipe.execute()
                return
            except Exception as exc:
                log.warning("auth.ratelimit.redis_record_failed", error=str(exc)[:200])

        attempts = [t for t in self._memory_attempts.get(ip, []) if t > now - timedelta(seconds=60)]
        attempts.append(now)
        self._memory_attempts[ip] = attempts

    async def reset_failed_attempts(self, ip: str, redis: Any | None = None) -> None:
        """Limpa o registro de falhas para o IP após login bem-sucedido."""
        if redis is not None:
            try:
                await redis.delete(f"auth:ratelimit:{ip}")
            except Exception as exc:
                log.warning("auth.ratelimit.redis_reset_failed", error=str(exc)[:200])
        self._memory_attempts.pop(ip, None)

    async def ensure_seed_user(self, *, username: str, password: str) -> None:
        """Cria o usuário único se `app_user` estiver vazia. Idempotente e
        best-effort: um soluço aqui não pode impedir a API de subir — só
        deixa o login indisponível até o próximo restart, mesmo espírito de
        degradação graciosa do resto do projeto."""
        try:
            async with session_scope() as session:
                if await store.count_users(session) > 0:
                    return
                await store.create_user(
                    session,
                    username=username,
                    password_hash=_hash_password(password),
                    display_name=username,
                )
            log.info("auth.seed_user.created", username=username)
        except Exception as exc:
            log.error("auth.seed_user.failed", error=str(exc)[:200])

    async def authenticate(self, *, username: str, password: str) -> AppUser | None:
        async with session_scope() as session:
            user = await store.get_user_by_username(session, username)
        if user is None or not _verify_password(password, user.password_hash):
            return None
        return user

    async def change_password(
        self, *, user_id: uuid.UUID, old_password: str, new_password: str
    ) -> bool:
        """Troca a senha do usuário caso a senha antiga seja válida."""
        async with session_scope() as session:
            user = await store.get_user(session, user_id)
            if user is None or not _verify_password(old_password, user.password_hash):
                return False
            new_hash = _hash_password(new_password)
            await store.update_user_password(session, user, password_hash=new_hash)
        log.info("auth.change_password.success", user_id=str(user_id))
        return True

    async def create_session(
        self, *, user_id: uuid.UUID, user_agent: str | None = None
    ) -> tuple[str, datetime]:
        """Devolve o token em claro (só existe neste retorno, nunca mais) e
        o instante de expiração."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + SESSION_TTL
        async with session_scope() as session:
            await store.create_session(
                session,
                user_id=user_id,
                token_hash=_hash_token(token),
                expires_at=expires_at,
                user_agent=user_agent,
            )
        return token, expires_at

    async def validate_session(self, token: str) -> AppUser | None:
        token_hash = _hash_token(token)
        async with session_scope() as session:
            auth_session = await store.get_session_by_token_hash(session, token_hash)
            if auth_session is None or auth_session.revoked_at is not None:
                return None
            now = datetime.now(UTC)
            if auth_session.expires_at < now:
                return None
            await store.touch_session(session, auth_session, now=now)
            user = await store.get_user(session, auth_session.user_id)
        return user if user and user.is_active else None

    async def revoke_session(self, token: str) -> None:
        token_hash = _hash_token(token)
        async with session_scope() as session:
            auth_session = await store.get_session_by_token_hash(session, token_hash)
            if auth_session is not None:
                await store.revoke_session(session, auth_session, now=datetime.now(UTC))

    async def purge_expired_sessions(self) -> int:
        """Deleta do banco todas as sessões expiradas ou revogadas."""
        try:
            async with session_scope() as session:
                purged = await store.purge_expired_sessions(session, now=datetime.now(UTC))
            if purged > 0:
                log.info("auth.sessions.purged", count=purged)
            return purged
        except Exception as exc:
            log.warning("auth.sessions.purge_failed", error=str(exc)[:200])
            return 0

