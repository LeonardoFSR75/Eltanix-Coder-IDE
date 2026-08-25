"""RBAC — enforcement de papel por projeto sobre `project_member` (Horizonte 2,
ver docs/proposals/plano-implementacao-auditoria-arquitetural.md).

Três papéis, rank crescente: `viewer` (leitura) < `editor` (escrita) < `owner`
(admin do projeto — atualiza, apaga, gerencia membro). Dois bypasses, os dois
já estabelecidos em outro lugar do projeto: o canal de serviço
(`NOVAAI_STUDIO_API_KEY`, ADR 0005) e o usuário `is_admin` (dono da instância,
`AppUser.is_admin`) sempre passam sem consultar `project_member` — nenhum dos
dois é "membro" de projeto nenhum, mas os dois têm acesso irrestrito por
desenho, o mesmo espírito de "canal de serviço não é usuário de browser" que
já rege `require_session` (`api/deps.py`).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.auth import store
from novaai_studio.db.models import ProjectRecord

ROLE_RANK: dict[str, int] = {"viewer": 1, "editor": 2, "owner": 3}


def _actor_bypasses(request: Request) -> bool:
    is_service = getattr(request.state, "is_service", False)
    is_admin = getattr(request.state, "is_admin", False)
    return bool(is_service or is_admin)


async def get_role(
    session: AsyncSession, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    member = await store.get_member(session, project_id=project_id, user_id=user_id)
    return member.role if member else None


async def require_role(
    session: AsyncSession, request: Request, *, project_id: uuid.UUID, min_role: str
) -> None:
    """Levanta 403 se o ator autenticado não tem, no mínimo, `min_role` no
    projeto `project_id`. Bypass total para canal de serviço e admin da
    instância — ver docstring do módulo."""
    if _actor_bypasses(request):
        return

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        # Sessão de browser sempre tem `user_id` (ver `require_session`);
        # chegar aqui sem um é o mesmo tipo de estado impossível que outros
        # `getattr(request.state, ...)` deste projeto tratam como "sem
        # acesso" em vez de derrubar a requisição com um erro não tratado.
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Sem acesso a este projeto.")

    role = await get_role(session, project_id=project_id, user_id=user_id)
    if role is None or ROLE_RANK.get(role, 0) < ROLE_RANK[min_role]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Sem acesso a este projeto.")


async def require_role_by_slug(
    session: AsyncSession, request: Request, *, project_slug: str | None, min_role: str
) -> None:
    """Mesma checagem de `require_role`, mas a partir do slug — usado pelas
    rotas de conteúdo (`notes`, `documents`, `context`) onde o projeto chega
    como string opcional, não como `ProjectRecord` já carregado.

    `project_slug=None` não faz nada: nota/documento/busca "global" (sem
    projeto) continua com o comportamento de hoje, sem checagem — RBAC só
    existe *por projeto*, não há papel "global" para aplicar. Um slug que não
    bate com nenhum `ProjectRecord` também não faz nada: mantém o mesmo
    comportamento tolerante que essas rotas já têm hoje para projeto
    inexistente/ad-hoc (ver `ensure_project_slug_exists`), em vez de RBAC
    virar a primeira coisa a bloquear um fluxo que sempre funcionou.
    """
    if not project_slug or _actor_bypasses(request):
        return
    project_id = await session.scalar(
        select(ProjectRecord.id).where(ProjectRecord.slug == project_slug)
    )
    if project_id is None:
        return
    await require_role(session, request, project_id=project_id, min_role=min_role)
