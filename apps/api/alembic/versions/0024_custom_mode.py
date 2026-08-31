"""Modos customizáveis do agente (Fase 6 do upgrade do agente)

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_mode",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=False, server_default="🧩"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("prompt_block", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # `mode` também passa a poder guardar o id (UUID em texto, 36 chars) de um
    # modo customizado — String(16) nunca comportaria isso.
    op.alter_column(
        "agent_session", "mode", existing_type=sa.String(length=16), type_=sa.String(length=64)
    )


def downgrade() -> None:
    op.alter_column(
        "agent_session", "mode", existing_type=sa.String(length=64), type_=sa.String(length=16)
    )
    op.drop_table("custom_mode")
