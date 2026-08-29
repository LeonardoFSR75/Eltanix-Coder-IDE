"""Rotas de login. `/login` fica fora de `AuthDep` de propósito — é o único
jeito de entrar; `/me` e `/logout` exigem sessão válida."""

from __future__ import annotations

import io
import uuid
from typing import Any

import segno
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from eltanix.api.deps import AdminDep, AuthDep
from eltanix.auth.service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _service(request: Request) -> AuthService:
    service: AuthService | None = getattr(request.app.state, "auth", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Autenticação indisponível."
        )
    return service


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class MfaLoginRequest(BaseModel):
    mfa_token: str = Field(min_length=1, max_length=128)
    code: str = Field(
        min_length=1, max_length=32, description="Código do app autenticador ou de recuperação"
    )


class MfaActivateRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=32)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    is_admin: bool = Field(
        default=False, description="Concede acesso irrestrito a todo projeto — ver auth/rbac.py"
    )


def _client_ip(request: Request) -> str:
    # Não há reverse proxy confiável na frente desta API (o gateway do Next
    # não define X-Forwarded-For) — confiar nesse header permitiria a
    # qualquer chamador local resetar o próprio rate limit a cada tentativa,
    # só trocando o valor enviado.
    return request.client.host if request.client else "127.0.0.1"


async def _audit(
    request: Request, *, actor: str, action: str, status_: str = "success", details: str = ""
) -> None:
    """Trilha de auditoria dos eventos de auth (F-6 da revisão). Best-effort:
    um problema aqui nunca pode derrubar login/logout/troca de senha."""
    service = getattr(request.app.state, "audit", None)
    if service is None:
        return
    try:
        await service.record(
            actor=actor,
            module="auth",
            action=action,
            status=status_,
            risk_level="medium",
            details=details[:500],
            event_metadata={"ip": _client_ip(request)},
        )
    except Exception as exc:  # trilha de auditoria é best-effort, nunca fatal
        from eltanix.logging_setup import get_logger

        get_logger(__name__).warning("auth.audit_failed", action=action, error=str(exc)[:200])


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> dict[str, Any]:
    service = _service(request)
    redis = getattr(request.app.state, "redis", None)
    ip = _client_ip(request)

    ip_ok = await service.check_and_register_attempt(ip, redis)
    user_ok = await service.check_and_register_user_attempt(payload.username, redis)
    if not ip_ok or not user_ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
        )

    user = await service.authenticate(username=payload.username, password=payload.password)
    if user is None:
        await _audit(
            request,
            actor=payload.username[:64],
            action="login",
            status_="failure",
            details="usuário ou senha inválidos",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos."
        )

    await service.reset_failed_attempts(ip, redis)
    await service.reset_user_attempts(payload.username, redis)

    if await service.is_mfa_enabled(user.id):
        await _audit(request, actor=user.username, action="login", details="aguardando 2º fator")
        # Senha ok, mas ainda não há sessão: o cliente precisa completar o 2º
        # fator em `POST /api/auth/login/mfa` com este token de desafio.
        mfa_token = service.create_mfa_challenge(user.id)
        return {"mfa_required": True, "mfa_token": mfa_token}

    token, expires_at = await service.create_session(user_id=user.id, user_agent=user_agent)
    await _audit(request, actor=user.username, action="login")
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/login/mfa")
async def login_mfa(
    payload: MfaLoginRequest,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> dict[str, Any]:
    """Segunda etapa do login: troca o `mfa_token` do desafio + o código
    (TOTP ou de recuperação) por uma sessão. Rate-limitado pelo mesmo
    contador por IP do `/login` — um `mfa_token` roubado não vira balcão de
    brute-force do código."""
    service = _service(request)
    redis = getattr(request.app.state, "redis", None)
    ip = _client_ip(request)

    if not await service.check_and_register_attempt(ip, redis):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas. Tente novamente em 1 minuto.",
        )

    resultado = await service.complete_mfa_login(
        mfa_token=payload.mfa_token, code=payload.code, user_agent=user_agent
    )
    if resultado is None:
        await _audit(
            request,
            actor="?",
            action="login.mfa",
            status_="failure",
            details="código/desafio inválido",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código inválido ou desafio expirado. Faça login de novo.",
        )
    await service.reset_failed_attempts(ip, redis)
    token, expires_at = resultado
    await _audit(request, actor="(sessão criada via 2º fator)", action="login.mfa")
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/logout", dependencies=[AuthDep])
async def logout(
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if eltanix_session:
        service = _service(request)
        user = await service.validate_session(eltanix_session)
        await service.revoke_session(eltanix_session)
        await _audit(request, actor=user.username if user else "?", action="logout")
    return {"status": "ok"}


@router.get("/me", dependencies=[AuthDep])
async def me(
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if not eltanix_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sem sessão de usuário (chamada autenticada por chave de API de serviço).",
        )
    user = await _service(request).validate_session(eltanix_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.")
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name}


@router.post("/change-password", dependencies=[AuthDep])
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if not eltanix_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Troca de senha requer sessão de usuário.",
        )
    service = _service(request)
    user = await service.validate_session(eltanix_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.")

    success = await service.change_password(
        user_id=user.id,
        old_password=payload.old_password,
        new_password=payload.new_password,
        keep_session_token=eltanix_session,
    )
    if not success:
        await _audit(request, actor=user.username, action="change_password", status_="failure")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta.",
        )
    await _audit(request, actor=user.username, action="change_password")
    return {"status": "ok", "message": "Senha alterada com sucesso."}


@router.get("/sessions", dependencies=[AuthDep])
async def list_sessions(
    request: Request, eltanix_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """Sessões ativas do usuário — "onde estou logado" (F-5). A que fez esta
    chamada vem marcada com `current: true`."""
    user = await _require_session_user(request, eltanix_session)
    sessoes = await _service(request).list_sessions(user.id, current_token=eltanix_session)
    return {"sessions": sessoes}


@router.delete("/sessions/{session_id}", dependencies=[AuthDep])
async def revoke_one_session(
    session_id: str, request: Request, eltanix_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """Revoga uma sessão específica do próprio usuário (não dá para revogar a
    de outro: o `user_id` entra no `WHERE`)."""
    user = await _require_session_user(request, eltanix_session)
    try:
        alvo = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ID de sessão inválido."
        ) from exc
    ok = await _service(request).revoke_session_by_id(user.id, alvo)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada ou já revogada."
        )
    await _audit(request, actor=user.username, action="session.revoke", details=session_id)
    return {"status": "ok"}


async def _require_session_user(request: Request, eltanix_session: str | None) -> Any:
    """Usuário da sessão de browser ou 401 — as rotas de MFA são pessoais,
    não fazem sentido para o canal de serviço (`ELTANIX_API_KEY`)."""
    if not eltanix_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Requer sessão de usuário (não a chave de API de serviço).",
        )
    user = await _service(request).validate_session(eltanix_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.")
    return user


@router.get("/mfa/status", dependencies=[AuthDep])
async def mfa_status(
    request: Request, eltanix_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    user = await _require_session_user(request, eltanix_session)
    return await _service(request).mfa_status(user.id)


@router.post("/mfa/setup", dependencies=[AuthDep])
async def mfa_setup(
    request: Request, eltanix_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """Gera um segredo TOTP pendente (não ativa nada ainda). Chamável de novo
    enquanto não confirmado — cada chamada descarta o segredo anterior."""
    user = await _require_session_user(request, eltanix_session)
    try:
        return await _service(request).begin_mfa_setup(user.id, account=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/mfa/qr.svg", dependencies=[AuthDep])
async def mfa_qr(request: Request, eltanix_session: str | None = Cookie(default=None)) -> Response:
    """QR do segredo **pendente** para escanear no app autenticador. 404
    quando não há enrollment em andamento (nada a revelar de um MFA já ativo)."""
    user = await _require_session_user(request, eltanix_session)
    uri = await _service(request).pending_otpauth_uri(user.id, account=user.username)
    if uri is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum enrollment de MFA em andamento."
        )
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", scale=5, border=2)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/mfa/activate", dependencies=[AuthDep])
async def mfa_activate(
    payload: MfaActivateRequest,
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Confirma o enrollment com o primeiro código. Devolve os códigos de
    recuperação **uma única vez** — não há como recuperá-los depois."""
    user = await _require_session_user(request, eltanix_session)
    codes = await _service(request).activate_mfa(
        user.id, code=payload.code, keep_session_token=eltanix_session
    )
    if codes is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código inválido ou nenhum enrollment pendente.",
        )
    await _audit(request, actor=user.username, action="mfa.activate")
    return {"status": "ok", "recovery_codes": codes}


@router.post("/mfa/disable", dependencies=[AuthDep])
async def mfa_disable(
    payload: MfaDisableRequest,
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    user = await _require_session_user(request, eltanix_session)
    ok = await _service(request).disable_mfa(user.id, password=payload.password, code=payload.code)
    if not ok:
        await _audit(request, actor=user.username, action="mfa.disable", status_="failure")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Senha ou código inválido."
        )
    await _audit(request, actor=user.username, action="mfa.disable")
    return {"status": "ok"}


@router.post("/mfa/recovery-codes", dependencies=[AuthDep])
async def mfa_regenerate_recovery_codes(
    payload: MfaDisableRequest,
    request: Request,
    eltanix_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Novo conjunto de códigos de recuperação; invalida os antigos. Exige
    senha + código, como o disable."""
    user = await _require_session_user(request, eltanix_session)
    codes = await _service(request).regenerate_recovery_codes(
        user.id, password=payload.password, code=payload.code
    )
    if codes is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Senha ou código inválido."
        )
    return {"status": "ok", "recovery_codes": codes}


def _user_view(user: Any) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/users", dependencies=[AuthDep, AdminDep])
async def create_user(payload: CreateUserRequest, request: Request) -> dict[str, Any]:
    """Único jeito de criar usuário além do seed (`ensure_seed_user`, lifespan)
    — só o dono da instância ou o canal de serviço convida gente nova, não há
    self-signup (ver Horizonte 2 do plano de auditoria)."""
    user = await _service(request).create_user(
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        is_admin=payload.is_admin,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username já está em uso.")
    ator = getattr(request.state, "actor", "?")
    await _audit(
        request,
        actor=ator,
        action="create_user",
        details=f"username={payload.username} is_admin={payload.is_admin}",
    )
    return _user_view(user)


@router.get("/users", dependencies=[AuthDep, AdminDep])
async def list_users(request: Request) -> dict[str, Any]:
    users = await _service(request).list_users()
    return {"users": [_user_view(u) for u in users]}
