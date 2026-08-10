"""Lineage de sessões: parent_session_id para orquestração multiagente

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_session",
        sa.Column("parent_session_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_agent_session_parent", "agent_session", ["parent_session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_session_parent", table_name="agent_session")
    op.drop_column("agent_session", "parent_session_id")
