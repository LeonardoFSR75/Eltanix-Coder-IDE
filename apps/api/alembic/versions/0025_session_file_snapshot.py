"""Snapshots de arquivo para checkpoints/rewind de sessão (Fase 8 do upgrade do agente)

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_file_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content_before", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_file_snapshot_session_iteration",
        "session_file_snapshot",
        ["session_id", "iteration"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_file_snapshot_session_iteration", table_name="session_file_snapshot")
    op.drop_table("session_file_snapshot")
