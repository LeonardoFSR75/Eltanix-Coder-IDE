"""Tabela completion_event — desfecho de sugestões de autocompletar inline (ADR 0014)

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-30

Custo/latência de cada chamada de autocompletar já caem em `request_log` pelo
router. Esta tabela guarda só o que falta lá: se a sugestão foi aceita,
rejeitada ou ignorada, e quantos chars o humano aproveitou. Sem prefixo/sufixo
nem o texto da sugestão.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "completion_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("suggestion_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("project_slug", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("shown_ms", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("chars_suggested", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chars_accepted", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_completion_event_created_at", "completion_event", ["created_at"], unique=False
    )
    op.create_index(
        "ix_completion_event_suggestion_id", "completion_event", ["suggestion_id"], unique=False
    )
    op.create_index(
        "ix_completion_event_project_slug", "completion_event", ["project_slug"], unique=False
    )
    op.create_index("ix_completion_event_language", "completion_event", ["language"], unique=False)
    op.create_index("ix_completion_event_outcome", "completion_event", ["outcome"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_completion_event_outcome", table_name="completion_event")
    op.drop_index("ix_completion_event_language", table_name="completion_event")
    op.drop_index("ix_completion_event_project_slug", table_name="completion_event")
    op.drop_index("ix_completion_event_suggestion_id", table_name="completion_event")
    op.drop_index("ix_completion_event_created_at", table_name="completion_event")
    op.drop_table("completion_event")
