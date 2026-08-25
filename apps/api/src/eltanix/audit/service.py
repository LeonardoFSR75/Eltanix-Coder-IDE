"""Orquestração de auditoria.

Granularidade deliberada: só decisões de aprovação (WRITE/EXEC), CRUD de
documentos/notas/skills e eventos explícitos de UI sem contrapartida de
backend entram aqui. Toda ferramenta READ geraria muito ruído e pouco sinal —
nada muda, não há o que revisar depois.
"""

from __future__ import annotations

import uuid
from typing import Any

from eltanix.audit import store
from eltanix.db.models import AuditLogEntry
from eltanix.db.session import session_scope


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
        project_slug: str | None = None,
        metadata: dict | None = None,
        event_metadata: dict | None = None,
    ) -> AuditLogEntry:
        meta = metadata if metadata is not None else event_metadata
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
                project_slug=project_slug,
                metadata=meta,
            )

    async def record_security_event(
        self,
        *,
        actor: str,
        action: str,
        details: str = "",
        risk_level: str = "medium",
        status: str = "success",
        session_id: str | None = None,
        project_slug: str | None = None,
        tool_name: str | None = None,
        tool_risk: str | None = None,
        decision: str | None = None,
        source: str = "agent",
        metadata: dict | None = None,
    ) -> AuditLogEntry:
        """Registra eventos de segurança do agente com estrutura rica para a UI.

        A ideia é padronizar os diversos gatilhos de risco (prompts maliciosos,
        bloqueio por política, recusa de decisão, repetição perigosa) num único
        formato que a rota de auditoria consegue exibir sem que cada evento
        invente um payload diferente.
        """
        base_meta = {
            "source": source,
            "tool": tool_name,
            "tool_risk": tool_risk,
            "decision": decision,
        }
        if metadata:
            base_meta.update(metadata)
        return await self.record(
            actor=actor,
            module="Security",
            action=action,
            details=details,
            risk_level=risk_level,
            status=status,
            session_id=session_id,
            project_slug=project_slug,
            metadata=base_meta,
        )

    async def record_approvals(
        self,
        *,
        session_id: str,
        pending: list[dict[str, Any]],
        approvals: dict[str, bool],
        reasons: dict[str, str],
        decided_by: dict[str, str] | None = None,
        project_slug: str | None = None,
    ) -> None:
        """Um registro por ação pendente — chamado pelo nó `approve` do grafo,
        depois de a decisão (humana ou por política de auto-aprovação) ser
        tomada. Cobre exatamente o momento em que uma ação de risco
        (WRITE/EXEC) passa a valer ou é recusada.

        `decided_by` distingue uma auto-aprovação (`"policy"`) de uma decisão
        humana de verdade — sem isso, as duas ficariam indistinguíveis no
        log de auditoria, e uma auto-aprovação passaria por "foi revisada"."""
        decisores = decided_by or {}
        async with session_scope() as session:
            for item in pending:
                call_id = item.get("tool_call_id", "")
                approved = approvals.get(call_id, False)
                auto_aprovado = decisores.get(call_id) == "policy"
                await store.record(
                    session,
                    actor="política" if auto_aprovado else "agente",
                    module="Agent",
                    action=f"Aprovação de ferramenta: {item.get('tool', '?')}",
                    details=item.get("summary", ""),
                    risk_level="critical" if item.get("risk") == "exec" else "medium",
                    status="success" if approved else "denied",
                    session_id=session_id,
                    project_slug=project_slug,
                    metadata={
                        "reason": reasons.get(call_id, ""),
                        "auto_approved": auto_aprovado,
                        "tool": item.get("tool"),
                        "tool_risk": item.get("risk"),
                        "decision": "approved" if approved else "denied",
                        "source": "policy" if auto_aprovado else "human",
                    },
                )

    async def list_all(
        self,
        *,
        module: str | None = None,
        risk_level: str | None = None,
        q: str | None = None,
        project_slug: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        async with session_scope() as session:
            return await store.list_entries(
                session,
                module=module,
                risk_level=risk_level,
                q=q,
                project_slug=project_slug,
                session_id=session_id,
                limit=limit,
                offset=offset,
            )

    async def get(self, entry_id: uuid.UUID) -> AuditLogEntry | None:
        async with session_scope() as session:
            return await store.get_entry(session, entry_id)
