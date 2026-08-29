"""Tabela request_log e extensão pgvector

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Criada já na fase 1 para que a indexação da fase 2 não exija migração de infra.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "request_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("endpoint", sa.String(length=64), nullable=False, server_default="chat"),
        sa.Column("requested_model", sa.String(length=128), nullable=False),
        sa.Column("profile", sa.String(length=64), nullable=True),
        sa.Column("resolved_model", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column(
            "fallback_from",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stream", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=8), nullable=False, server_default="0"),
        sa.Column("cost_known", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tokens_saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cost_saved_usd", sa.Numeric(precision=14, scale=8), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_log_created_at", "request_log", ["created_at"])
    op.create_index("ix_request_log_model_created", "request_log", ["resolved_model", "created_at"])
    op.create_index("ix_request_log_source_created", "request_log", ["source", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_request_log_source_created", table_name="request_log")
    op.drop_index("ix_request_log_model_created", table_name="request_log")
    op.drop_index("ix_request_log_created_at", table_name="request_log")
    op.drop_table("request_log")
