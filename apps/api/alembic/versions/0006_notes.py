"""Segundo Cérebro: note e note_chunk

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-02

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        # IDs (texto) de outras notas ligadas via [[wikilink]] — resolvido no
        # servidor a cada save, não confiado ao cliente.
        sa.Column("links", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "note_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_chunk_note_id", "note_chunk", ["note_id"])

    op.execute(
        "ALTER TABLE note_chunk ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.execute("CREATE INDEX ix_note_chunk_tsv ON note_chunk USING GIN (tsv)")
    op.execute(
        "CREATE INDEX ix_note_chunk_embedding ON note_chunk USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_note_chunk_embedding")
    op.execute("DROP INDEX IF EXISTS ix_note_chunk_tsv")
    op.drop_index("ix_note_chunk_note_id", table_name="note_chunk")
    op.drop_table("note_chunk")
    op.drop_table("note")
