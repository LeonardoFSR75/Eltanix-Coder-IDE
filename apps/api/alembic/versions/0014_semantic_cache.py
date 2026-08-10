"""Cache semântico de respostas: cached_response_embedding

Índice pgvector apontando pra chaves do cache exato (Redis) — não duplica
payload, só a similaridade de embedding pra decidir se um lookup exato
recente (mas de outro prompt quase idêntico) ainda serve.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-10

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mesma convenção de 0005_documents.py: a dimensão faz parte do DDL, então lê
# do ambiente na hora da migração em vez de importar `Settings` (o app pode
# evoluir o default sem isso reabrir esta migração já aplicada).
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.create_table(
        "cached_response_embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("redis_cache_key", sa.String(length=128), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cached_response_embedding_model_expires",
        "cached_response_embedding",
        ["model_id", "expires_at"],
    )
    op.execute(
        "CREATE INDEX ix_cached_response_embedding_vector ON cached_response_embedding "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cached_response_embedding_vector")
    op.drop_index(
        "ix_cached_response_embedding_model_expires", table_name="cached_response_embedding"
    )
    op.drop_table("cached_response_embedding")
