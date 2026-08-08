"""Rotas de login. `/login` fica fora de `AuthDep` de propósito — é o único
jeito de entrar; `/me` e `/logout` exigem sessão válida."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.auth.service import AuthService

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


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> dict[str, Any]:
    service = _service(request)
    user = await service.authenticate(username=payload.username, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos."
        )
    token, expires_at = await service.create_session(user_id=user.id, user_agent=user_agent)
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/logout", dependencies=[AuthDep])
async def logout(
    request: Request,
    sicoobito_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if sicoobito_session:
        await _service(request).revoke_session(sicoobito_session)
    return {"status": "ok"}


@router.get("/me", dependencies=[AuthDep])
async def me(
    request: Request,
    sicoobito_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    if not sicoobito_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sem sessão de usuário (chamada autenticada por chave de API de serviço).",
        )
    user = await _service(request).validate_session(sicoobito_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.")
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name}
