"""Code Knowledge Graph: code_edge

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_edge",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=512), nullable=False),
        sa.Column("from_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_path", sa.String(length=1024), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_chunk_id"], ["code_chunk.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_chunk_id"], ["code_chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_edge_workspace_from", "code_edge", ["workspace", "from_chunk_id"])
    op.create_index("ix_code_edge_workspace_to", "code_edge", ["workspace", "to_chunk_id"])
    op.create_index("ix_code_edge_workspace_to_path", "code_edge", ["workspace", "to_path"])


def downgrade() -> None:
    op.drop_index("ix_code_edge_workspace_to_path", table_name="code_edge")
    op.drop_index("ix_code_edge_workspace_to", table_name="code_edge")
    op.drop_index("ix_code_edge_workspace_from", table_name="code_edge")
    op.drop_table("code_edge")
