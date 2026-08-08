"""Dependências compartilhadas: autenticação, acesso ao engine e identificação da origem."""

from __future__ import annotations

import hmac
import re
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from sicoobito.auth.service import AuthService
from sicoobito.config import Settings, get_settings
from sicoobito.db.session import get_session
from sicoobito.router.engine import RouterEngine


def get_engine(request: Request) -> RouterEngine:
    engine: RouterEngine | None = getattr(request.app.state, "engine", None)
    if engine is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Router não inicializado.",
        )
    return engine


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Chave única local.

    Sem `SICOOBITO_API_KEY` definida a API fica aberta — aceitável para uso
    estritamente local, e por isso o startup emite um aviso explícito.
    """
    if not settings.api_key:
        return

    presented = x_api_key
    if not presented and authorization:
        scheme, _, token = authorization.partition(" ")
        presented = token.strip() if scheme.lower() == "bearer" else authorization.strip()

    if not presented or not hmac.compare_digest(presented, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API inválida ou ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    sicoobito_session: Annotated[str | None, Cookie()] = None,
) -> None:
    """Dependência viva das rotas (`AuthDep`) — substitui a checagem isolada de
    `require_api_key`.

    A chave de API de serviço continua valendo (CI, cline, cursor, aider —
    tudo que já usa `X-Api-Key`/`Authorization: Bearer`), e passa a valer
    também uma sessão de usuário via cookie httpOnly. Ao contrário de
    `require_api_key`, esta função **nunca** fica aberta por omissão: sem
    nenhuma das duas credenciais válidas, é sempre 401 — é exatamente essa
    mudança de comportamento que torna o login obrigatório.
    """
    if settings.api_key:
        presented = x_api_key
        if not presented and authorization:
            scheme, _, token = authorization.partition(" ")
            presented = token.strip() if scheme.lower() == "bearer" else authorization.strip()
        if presented and hmac.compare_digest(presented, settings.api_key):
            return

    if sicoobito_session:
        auth: AuthService | None = getattr(request.app.state, "auth", None)
        if auth is not None and await auth.validate_session(sicoobito_session) is not None:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticação necessária — chave de API ou login.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Assinaturas de User-Agent das ferramentas que costumam apontar para o gateway.
_SOURCE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cline", re.compile(r"cline", re.I)),
    ("continue", re.compile(r"continue", re.I)),
    ("aider", re.compile(r"aider", re.I)),
    ("claude-code", re.compile(r"claude[-_ ]?code", re.I)),
    ("cursor", re.compile(r"cursor", re.I)),
    ("roo", re.compile(r"roo[-_ ]?code", re.I)),
    ("openai-sdk", re.compile(r"openai-python|openai-node", re.I)),
    ("curl", re.compile(r"^curl/", re.I)),
]


def identify_source(
    x_sicoobito_source: Annotated[str | None, Header()] = None,
    user_agent: Annotated[str | None, Header()] = None,
) -> str:
    """Descobre quem está chamando, para o dashboard atribuir gasto por ferramenta.

    O header explícito ganha do User-Agent; é o que a IDE e o agente usarão.
    """
    if x_sicoobito_source:
        return x_sicoobito_source[:64]
    if user_agent:
        for name, pattern in _SOURCE_PATTERNS:
            if pattern.search(user_agent):
                return name
        return user_agent.split("/")[0][:64]
    return "unknown"


def identify_project(
    x_sicoobito_project: Annotated[str | None, Header()] = None,
) -> str | None:
    """Projeto de origem da chamada, para atribuição de custo por projeto.

    Opcional: ferramentas externas (cline, cursor, aider) não têm o conceito de
    projeto do SicoobitoCode e simplesmente não mandam o header — nesse caso o
    custo fica sem projeto associado, igual acontecia antes desta dependency existir.
    """
    return x_sicoobito_project[:128] if x_sicoobito_project else None


EngineDep = Annotated[RouterEngine, Depends(get_engine)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SourceDep = Annotated[str, Depends(identify_source)]
ProjectDep = Annotated[str | None, Depends(identify_project)]
DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Depends(require_session)
