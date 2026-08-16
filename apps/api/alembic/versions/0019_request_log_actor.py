"""Coluna actor em request_log

Achado na auditoria arquitetural (docs/proposals/plano-implementacao-
auditoria-arquitetural.md, Horizonte 1): sem isto não havia como atribuir
custo de LLM a um usuário específico, só a `source` (ferramenta de origem) e
`project_slug` (projeto). Populada por `identify_actor` (`api/deps.py`) —
"api_key" para o canal de serviço (ADR 0005) ou o username da sessão de
browser. Nulável de propósito: linhas antigas e qualquer caminho que ainda
não passa por essa dependency ficam sem atribuição, não com um valor falso.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("request_log", sa.Column("actor", sa.String(length=64), nullable=True))
    op.create_index("ix_request_log_actor", "request_log", ["actor"])


def downgrade() -> None:
    op.drop_index("ix_request_log_actor", table_name="request_log")
    op.drop_column("request_log", "actor")
