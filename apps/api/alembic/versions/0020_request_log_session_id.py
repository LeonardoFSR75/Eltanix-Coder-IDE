"""Coluna session_id em request_log

Achado na auditoria arquitetural (docs/proposals/plano-implementacao-
auditoria-arquitetural.md, Horizonte 2, "Agent Flight Recorder v1"):
`tool_span` e `audit_log` já guardam `session_id`, mas `request_log` (custo de
LLM) não tinha nenhum jeito de ligar uma chamada de modelo à sessão de agente
que a disparou — só `source`/`project_slug`, que não identificam uma execução
específica. Sem isto, reconstruir a linha do tempo completa de uma sessão
(ferramenta + custo + auditoria) era estruturalmente impossível para a parte
de custo. `String(32)` para bater com o tamanho canônico de `AgentSessionRecord.
session_id` (12 chars hex, ver `db/models.py`), não com o `String(64)` que
`tool_span` usa. Nulável de propósito: linhas antigas e qualquer chamada fora
do fluxo do agente (ex: `/v1/chat/completions` direto) ficam sem sessão, não
com um valor falso. Índice composto com `created_at`, mesmo padrão de
`ix_tool_span_session_created` (migração 0013), para a leitura da timeline por
sessão não fazer sequential scan.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("request_log", sa.Column("session_id", sa.String(length=32), nullable=True))
    op.create_index(
        "ix_request_log_session_created", "request_log", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_request_log_session_created", table_name="request_log")
    op.drop_column("request_log", "session_id")
