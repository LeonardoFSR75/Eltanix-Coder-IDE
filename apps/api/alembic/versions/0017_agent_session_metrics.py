"""Métricas e resumo compactos da sessão do agente

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_session", sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0"))
    op.add_column("agent_session", sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_session", sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_session", sa.Column("pending_approvals", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_session", sa.Column("last_failed_call_count", sa.Integer(), nullable=False, server_default="0"))

    op.alter_column("agent_session", "total_cost_usd", server_default=None)
    op.alter_column("agent_session", "total_tokens", server_default=None)
    op.alter_column("agent_session", "iterations", server_default=None)
    op.alter_column("agent_session", "pending_approvals", server_default=None)
    op.alter_column("agent_session", "last_failed_call_count", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_session", "last_failed_call_count")
    op.drop_column("agent_session", "pending_approvals")
    op.drop_column("agent_session", "iterations")
    op.drop_column("agent_session", "total_tokens")
    op.drop_column("agent_session", "total_cost_usd")
