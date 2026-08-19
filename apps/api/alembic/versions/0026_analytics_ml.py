"""Tabelas de Analytics ML: chat_trajectory, failure_cluster e correction_proposal

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-19

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    # 1. chat_trajectory
    op.create_table(
        "chat_trajectory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("project_slug", sa.String(length=128), nullable=True),
        sa.Column("user_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("failure_category", sa.String(length=64), nullable=False, server_default="NONE"),
        sa.Column("trajectory_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_trajectory_session_id", "chat_trajectory", ["session_id"])
    op.create_index("ix_chat_trajectory_project_slug", "chat_trajectory", ["project_slug"])
    op.create_index("ix_chat_trajectory_failure_category", "chat_trajectory", ["failure_category"])

    # 2. failure_cluster
    op.create_table(
        "failure_cluster",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("centroid_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("sample_trajectory_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_failure_cluster_failure_category", "failure_cluster", ["failure_category"])
    op.create_index("ix_failure_cluster_status", "failure_cluster", ["status"])

    # 3. correction_proposal
    op.create_table(
        "correction_proposal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("proposal_type", sa.String(length=64), nullable=False),
        sa.Column("target_file", sa.String(length=512), nullable=True),
        sa.Column("diff_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["failure_cluster.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_correction_proposal_status", "correction_proposal", ["status"])


def downgrade() -> None:
    op.drop_index("ix_correction_proposal_status", table_name="correction_proposal")
    op.drop_table("correction_proposal")
    op.drop_index("ix_failure_cluster_status", table_name="failure_cluster")
    op.drop_index("ix_failure_cluster_failure_category", table_name="failure_cluster")
    op.drop_table("failure_cluster")
    op.drop_index("ix_chat_trajectory_failure_category", table_name="chat_trajectory")
    op.drop_index("ix_chat_trajectory_project_slug", table_name="chat_trajectory")
    op.drop_index("ix_chat_trajectory_session_id", table_name="chat_trajectory")
    op.drop_table("chat_trajectory")
