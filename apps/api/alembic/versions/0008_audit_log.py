"""Auditoria: audit_log

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_module", "audit_log", ["module"])
    op.create_index("ix_audit_log_risk_level", "audit_log", ["risk_level"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_risk_level", table_name="audit_log")
    op.drop_index("ix_audit_log_module", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
