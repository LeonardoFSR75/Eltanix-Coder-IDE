"""Telemetria durável de ferramentas/RAG: tool_span

Espelha `request_log` (custo de LLM, já durável) para os spans de
`telemetry/tracer.py::TraceRecorder`, hoje só em memória + Redis capado.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_span",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_span_created_at", "tool_span", ["created_at"])
    op.create_index("ix_tool_span_name_created", "tool_span", ["name", "created_at"])
    op.create_index("ix_tool_span_session_created", "tool_span", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tool_span_session_created", table_name="tool_span")
    op.drop_index("ix_tool_span_name_created", table_name="tool_span")
    op.drop_index("ix_tool_span_created_at", table_name="tool_span")
    op.drop_table("tool_span")
