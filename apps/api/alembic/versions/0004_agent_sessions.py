"""Histórico de sessões do agente

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-26

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_session",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("base_branch", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_agent_session_project_updated", "agent_session", ["project", "updated_at"]
    )
    op.create_index("ix_agent_session_status", "agent_session", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_session_status", table_name="agent_session")
    op.drop_index("ix_agent_session_project_updated", table_name="agent_session")
    op.drop_table("agent_session")
