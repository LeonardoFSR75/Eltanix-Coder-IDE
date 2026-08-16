"""Orquestração de autenticação — etapa 1 do login obrigatório.

Um único usuário seed por enquanto (ver `ensure_seed_user`, chamado no
lifespan), sem RBAC. Senha em `scrypt` (stdlib — nenhuma dependência nova, e
evita wheel nativo em ambiente Windows sem MSVC Build Tools); token de sessão
opaco, só o hash (`sha256`) fica no banco, igual `require_api_key` já faz
para a chave de API de serviço via `hmac.compare_digest`.
"""

from __future__ import annotations

import asyncio
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
# N=2**17 é o teto que a OWASP recomenda para scrypt isolado (sem pepper), mas
# custou ~2,7s por hash medido neste hardware — inaceitável num endpoint de
# login síncrono. N=2**16 (a alternativa mais leve que a própria OWASP lista)
# fica em ~1s: 4x mais caro que o valor antigo (2**14) sem tornar o login
# perceptivelmente travado. O formato do hash carrega os próprios parâmetros
# (`n$r$p$salt$hash`) — nunca fixos pelas constantes abaixo — para que bumpar
# N aqui no futuro não quebre a verificação de hashes antigos: cada senha é
# verificada com os parâmetros com que foi de fato gravada, e re-hasheada com
# os atuais só depois de uma autenticação bem-sucedida (ver `AuthService.
# authenticate`).
_SCRYPT_N = 2**16
_SCRYPT_R = 8
_SCRYPT_P = 1
# Formato legado (`salt$hash`, sem parâmetros embutidos) de antes desta
# migração — todo hash nesse formato foi gerado com estes valores.
_LEGACY_SCRYPT_N = 2**14
_LEGACY_SCRYPT_R = 8
_LEGACY_SCRYPT_P = 1


def _hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    n: int = _SCRYPT_N,
    r: int = _SCRYPT_R,
    p: int = _SCRYPT_P,
) -> str:
    salt = salt or secrets.token_bytes(16)
    # scrypt usa ~128*n*r bytes de memória (~128 MiB em n=2**17, r=8) — acima
    # do teto default de 32 MiB do OpenSSL (`maxmem`), que faria N=2**17
    # explodir com "memory limit exceeded". Dobrar a estimativa cobre a folga
    # interna do algoritmo sem precisar recalcular a cada bump futuro de N.
    maxmem = 128 * n * r * 2
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=maxmem)
    return f"{n}${r}${p}${salt.hex()}${derived.hex()}"


def _parse_password_hash(password_hash: str) -> tuple[int, int, int, bytes, str]:
    """Aceita os dois formatos: `n$r$p$salt$hash` (atual) e `salt$hash`
    (legado, sempre `_LEGACY_SCRYPT_*`) — ver comentário acima de `_SCRYPT_N`."""
    partes = password_hash.split("$")
    if len(partes) == 5:
        n_str, r_str, p_str, salt_hex, hash_hex = partes
        return int(n_str), int(r_str), int(p_str), bytes.fromhex(salt_hex), hash_hex
    if len(partes) == 2:
        salt_hex, hash_hex = partes
        return (
            _LEGACY_SCRYPT_N,
            _LEGACY_SCRYPT_R,
            _LEGACY_SCRYPT_P,
            bytes.fromhex(salt_hex),
            hash_hex,
        )
    raise ValueError(f"formato de password_hash desconhecido ({len(partes)} partes)")


def _verify_password(password: str, password_hash: str) -> bool:
    """Compara só os bytes derivados, nunca a string formatada inteira: um
    hash legado (2 partes) e um recém-gerado (5 partes) têm o mesmo salt e o
    mesmo derived-hash quando a senha bate, mas formatos de string diferentes
    — comparar a string inteira faria todo hash legado falhar sempre."""
    try:
        n, r, p, salt, stored_hash_hex = _parse_password_hash(password_hash)
    except (ValueError, TypeError):
        return False
    maxmem = 128 * n * r * 2
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=maxmem)
    return hmac.compare_digest(derived.hex(), stored_hash_hex)


def _needs_rehash(password_hash: str) -> bool:
    """True se o hash não foi gerado com os parâmetros atuais — inclui todo
    hash no formato legado, que é sempre mais fraco que `_SCRYPT_N` atual."""
    try:
        n, r, p, _, _ = _parse_password_hash(password_hash)
    except (ValueError, TypeError):
        return False
    return (n, r, p) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Hash de uma senha que ninguém tem — só para gastar o mesmo tempo de scrypt
# quando o username não existe (ver `AuthService.authenticate`). Sem isso,
# username desconhecido responde rápido (nunca roda scrypt) e username válido
# com senha errada responde devagar (sempre roda), um canal de tempo que
# permite enumerar o username do admin medindo a latência de `/api/auth/login`.
_DUMMY_PASSWORD_HASH = _hash_password(secrets.token_urlsafe(32))


class AuthService:
    def __init__(self) -> None:
        self._memory_attempts: dict[str, list[datetime]] = {}

    async def check_and_register_attempt(self, ip: str, redis: Any | None = None) -> bool:
        """Registra a tentativa de login atual e devolve `True` se ainda está
        dentro do limite de 5 por minuto.

        Increment-then-check num único passo atômico (Redis `INCR`, ou lista
        em memória sem nenhum `await` entre leitura e escrita) — antes disto,
        `check_rate_limit` e `record_failed_attempt` eram duas chamadas
        separadas: sob concorrência, várias tentativas paralelas liam a
        mesma contagem antes de qualquer incremento ser persistido e todas
        passavam pelo limite. Contar a tentativa atual (não só as que já
        falharam) fecha essa corrida.
        """
        now = datetime.now(UTC)

        if redis is not None:
            try:
                key = f"auth:ratelimit:{ip}"
                pipe = redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, 60)
                count, _ = await pipe.execute()
                return int(count) <= 5
            except Exception as exc:
                log.warning("auth.ratelimit.redis_failed", error=str(exc)[:200])

        window_start = now - timedelta(seconds=60)
        # Sem isso, IPs cujas tentativas já expiraram ficam presos no dict
        # para sempre — só `reset_failed_attempts` (chamada em login
        # bem-sucedido) removia uma entrada. Com Redis fora do ar por um
        # período longo e tentativas de muitos IPs que nunca têm sucesso, o
        # dict cresce sem limite até o próximo restart do processo.
        ips_expirados = [
            outro_ip
            for outro_ip, tentativas in self._memory_attempts.items()
            if outro_ip != ip and all(t <= window_start for t in tentativas)
        ]
        for outro_ip in ips_expirados:
            self._memory_attempts.pop(outro_ip, None)

        attempts = [t for t in self._memory_attempts.get(ip, []) if t > window_start]
        attempts.append(now)
        self._memory_attempts[ip] = attempts
        return len(attempts) <= 5

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
        # Sempre roda `_verify_password` (scrypt), mesmo com username
        # desconhecido — contra um hash "dummy" fixo se não achar o usuário —
        # para as duas respostas terem o mesmo custo e fechar o canal de tempo.
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        valid = _verify_password(password, password_hash)
        if user is None or not valid:
            return None
        if _needs_rehash(user.password_hash):
            # Best-effort: um soluço aqui não pode derrubar um login que já
            # foi validado — o hash antigo continua verificável (`_parse_
            # password_hash` entende os dois formatos) até a próxima tentativa.
            try:
                async with session_scope() as session:
                    fresh = await store.get_user(session, user.id)
                    if fresh is not None:
                        await store.update_user_password(
                            session, fresh, password_hash=_hash_password(password)
                        )
                log.info("auth.password.rehashed", user_id=str(user.id))
            except Exception as exc:
                log.warning("auth.password.rehash_failed", error=str(exc)[:200])
        return user

    async def change_password(
        self,
        *,
        user_id: uuid.UUID,
        old_password: str,
        new_password: str,
        keep_session_token: str | None = None,
    ) -> bool:
        """Troca a senha do usuário caso a senha antiga seja válida.

        Revoga toda outra sessão ativa do usuário — sem isso, um token de
        sessão vazado continuaria válido mesmo depois da troca de senha, que é
        justamente a reação esperada quando o usuário legítimo suspeita de
        acesso indevido."""
        async with session_scope() as session:
            user = await store.get_user(session, user_id)
            if user is None or not _verify_password(old_password, user.password_hash):
                return False
            new_hash = _hash_password(new_password)
            await store.update_user_password(session, user, password_hash=new_hash)
            keep_hash = _hash_token(keep_session_token) if keep_session_token else None
            revogadas = await store.revoke_other_sessions(
                session, user_id=user_id, keep_token_hash=keep_hash, now=datetime.now(UTC)
            )
        log.info("auth.change_password.success", user_id=str(user_id), sessions_revoked=revogadas)
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
        try:
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
        except Exception as exc:
            log.warning("auth.validate_session.failed", error=str(exc)[:200])
            return None

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

    async def run_session_purge_reaper(self, interval_seconds: int = 3600) -> None:
        """Laço de limpeza periódica, mesmo padrão de `SandboxManager.run_reaper`.

        `purge_expired_sessions` só era chamada uma vez, no `lifespan` de
        startup — sem essa task de fundo, uma instância rodando por semanas
        sem restart acumula indefinidamente linhas de `auth_session`
        expiradas/revogadas no Postgres (não é falha de segurança, já que
        `validate_session` sempre confere `expires_at`, mas é uma tabela sem
        rotina de limpeza contínua, ao contrário do resto do projeto)."""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.purge_expired_sessions()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("auth.sessions.purge_reaper_iteration_failed", error=str(exc)[:200])
