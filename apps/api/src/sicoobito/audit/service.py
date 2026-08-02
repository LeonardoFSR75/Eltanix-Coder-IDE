"""Orquestração de auditoria.

Granularidade deliberada: só decisões de aprovação (WRITE/EXEC), CRUD de
documentos/notas/skills e eventos explícitos de UI sem contrapartida de
backend entram aqui. Toda ferramenta READ geraria muito ruído e pouco sinal —
nada muda, não há o que revisar depois.
"""

from __future__ import annotations

import uuid
from typing import Any

from sicoobito.audit import store
from sicoobito.db.models import AuditLogEntry
from sicoobito.db.session import session_scope


class AuditService:
    async def record(
        self,
        *,
        actor: str,
        module: str,
        action: str,
        details: str = "",
        risk_level: str = "low",
        status: str = "success",
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> AuditLogEntry:
        async with session_scope() as session:
            return await store.record(
                session,
                actor=actor,
                module=module,
                action=action,
                details=details,
                risk_level=risk_level,
                status=status,
                session_id=session_id,
                metadata=metadata,
            )

    async def record_approvals(
        self,
        *,
        session_id: str,
        pending: list[dict[str, Any]],
        approvals: dict[str, bool],
        reasons: dict[str, str],
    ) -> None:
        """Um registro por ação pendente — chamado pelo nó `approve` do grafo,
        depois de o usuário decidir. Cobre exatamente o momento em que uma
        ação de risco (WRITE/EXEC) passa a valer ou é recusada."""
        async with session_scope() as session:
            for item in pending:
                call_id = item.get("tool_call_id", "")
                approved = approvals.get(call_id, False)
                await store.record(
                    session,
                    actor="agente",
                    module="Agent",
                    action=f"Aprovação de ferramenta: {item.get('tool', '?')}",
                    details=item.get("summary", ""),
                    risk_level="critical" if item.get("risk") == "exec" else "medium",
                    status="success" if approved else "denied",
                    session_id=session_id,
                    metadata={"reason": reasons.get(call_id, "")} if not approved else None,
                )

    async def list_all(
        self,
        *,
        module: str | None = None,
        risk_level: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        async with session_scope() as session:
            return await store.list_entries(
                session, module=module, risk_level=risk_level, q=q, limit=limit, offset=offset
            )

    async def get(self, entry_id: uuid.UUID) -> AuditLogEntry | None:
        async with session_scope() as session:
            return await store.get_entry(session, entry_id)
