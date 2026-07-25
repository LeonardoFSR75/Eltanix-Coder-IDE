"""Índice de contexto: indexed_file e code_chunk

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-25

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A dimensão faz parte do DDL. Se EMBEDDING_DIM mudar, é preciso uma nova
# migração — não basta trocar a variável de ambiente.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.create_table(
        "indexed_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=512), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mtime", sa.Float(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_chunking", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_indexed_file_workspace_path", "indexed_file", ["workspace", "path"], unique=True
    )

    op.create_table(
        "code_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=512), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("symbol", sa.String(length=256), nullable=True),
        sa.Column("parent", sa.String(length=256), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="block"),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["indexed_file.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_chunk_workspace_path", "code_chunk", ["workspace", "path"])
    op.create_index("ix_code_chunk_symbol", "code_chunk", ["workspace", "symbol"])

    # Coluna gerada: o Postgres mantém o tsvector em sincronia com `content`
    # sozinho. Config `simple` em vez de `english` porque stemming quebra
    # identificadores (`getUserById` não deve virar `getuserbyid` radicalizado).
    op.execute(
        "ALTER TABLE code_chunk ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.execute("CREATE INDEX ix_code_chunk_tsv ON code_chunk USING GIN (tsv)")

    # HNSW com distância de cosseno: os embeddings vêm normalizados, e cosseno é
    # o que o nomic-embed-text espera.
    op.execute(
        "CREATE INDEX ix_code_chunk_embedding ON code_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunk_embedding")
    op.execute("DROP INDEX IF EXISTS ix_code_chunk_tsv")
    op.drop_index("ix_code_chunk_symbol", table_name="code_chunk")
    op.drop_index("ix_code_chunk_workspace_path", table_name="code_chunk")
    op.drop_table("code_chunk")
    op.drop_index("uq_indexed_file_workspace_path", table_name="indexed_file")
    op.drop_table("indexed_file")
