"""Dependências compartilhadas: autenticação, acesso ao engine e identificação da origem."""

from __future__ import annotations

import hmac
import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

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


EngineDep = Annotated[RouterEngine, Depends(get_engine)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SourceDep = Annotated[str, Depends(identify_source)]
DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Depends(require_api_key)
