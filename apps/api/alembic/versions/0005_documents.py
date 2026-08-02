"""Documentos (RAG): document e document_chunk

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-02

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A dimensão faz parte do DDL, igual à migração 0002. Mudar EMBEDDING_DIM
# exige uma nova migração, não só trocar a variável de ambiente.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("minio_bucket", sa.String(length=128), nullable=False),
        sa.Column("minio_object", sa.String(length=512), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        # pending -> processing -> ready | failed
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_status", "document", ["status"])

    op.create_table(
        "document_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_chunk_document_id", "document_chunk", ["document_id"])

    # Mesmo padrão da migração 0002: coluna gerada, config `simple` (sem
    # stemming — os documentos podem citar identificadores e nomes próprios
    # que stemming em inglês distorceria).
    op.execute(
        "ALTER TABLE document_chunk ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.execute("CREATE INDEX ix_document_chunk_tsv ON document_chunk USING GIN (tsv)")
    op.execute(
        "CREATE INDEX ix_document_chunk_embedding ON document_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunk_embedding")
    op.execute("DROP INDEX IF EXISTS ix_document_chunk_tsv")
    op.drop_index("ix_document_chunk_document_id", table_name="document_chunk")
    op.drop_table("document_chunk")
    op.drop_index("ix_document_status", table_name="document")
    op.drop_table("document")
