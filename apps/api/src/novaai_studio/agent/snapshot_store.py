"""Snapshots de arquivo para checkpoints/rewind de sessão (Fase 8 do upgrade
do agente) — mesmo padrão de `agent/custom_modes.py`: funções de módulo sobre
`AsyncSession`, mais uma classe fina (`SnapshotService`) que abre a própria
`session_scope()` para quem não já está dentro de uma (o nó `act()` do grafo).

O que esta tabela responde é só "qual era o conteúdo deste arquivo antes da
primeira escrita depois do checkpoint N" — não um histórico de versões
navegável arquivo a arquivo (isso já existe via `workspace/git.py`, o worktree
de cada sessão é um repositório Git de verdade). `restore_targets` existe
unicamente para alimentar `POST /api/agent/sessions/{id}/rewind`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.db.models import SessionFileSnapshot
from novaai_studio.db.session import session_scope


async def _record(
    session: AsyncSession, *, session_id: str, iteration: int, path: str, content_before: str
) -> None:
    session.add(
        SessionFileSnapshot(
            session_id=session_id,
            iteration=iteration,
            path=path,
            content_before=content_before,
        )
    )
    await session.flush()


async def _restore_targets(
    session: AsyncSession, *, session_id: str, after_iteration: int
) -> list[SessionFileSnapshot]:
    """Um snapshot por `path`, escolhendo — entre todas as escritas ocorridas
    *depois* de `after_iteration` — a mais antiga: é o `content_before` dela
    que reverte o arquivo para como estava exatamente na iteração-alvo,
    independente de quantas vezes ele foi reescrito depois disso.

    `DISTINCT ON` é sintaxe específica do Postgres — aceitável aqui porque
    todo o resto do schema já depende de recursos exclusivos dele (JSONB,
    pgvector), então não há um fallback SQLite a preservar (ver `JSON_TYPE`/
    `VECTOR_TYPE` em `db/models.py`, que já assumem o mesmo).
    """
    stmt = (
        select(SessionFileSnapshot)
        .distinct(SessionFileSnapshot.path)
        .where(
            SessionFileSnapshot.session_id == session_id,
            SessionFileSnapshot.iteration > after_iteration,
        )
        .order_by(
            SessionFileSnapshot.path,
            SessionFileSnapshot.iteration.asc(),
            SessionFileSnapshot.created_at.asc(),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _list_for_session(session: AsyncSession, *, session_id: str) -> list[SessionFileSnapshot]:
    stmt = (
        select(SessionFileSnapshot)
        .where(SessionFileSnapshot.session_id == session_id)
        .order_by(SessionFileSnapshot.iteration.asc(), SessionFileSnapshot.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


class SnapshotService:
    async def record(
        self, *, session_id: str, iteration: int, path: str, content_before: str
    ) -> None:
        async with session_scope() as session:
            await _record(
                session,
                session_id=session_id,
                iteration=iteration,
                path=path,
                content_before=content_before,
            )

    async def restore_targets(
        self, *, session_id: str, after_iteration: int
    ) -> list[SessionFileSnapshot]:
        async with session_scope() as session:
            return await _restore_targets(
                session, session_id=session_id, after_iteration=after_iteration
            )

    async def list_for_session(self, *, session_id: str) -> list[SessionFileSnapshot]:
        async with session_scope() as session:
            return await _list_for_session(session, session_id=session_id)
