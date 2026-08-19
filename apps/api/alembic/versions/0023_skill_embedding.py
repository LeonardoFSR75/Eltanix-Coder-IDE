"""Skills: coluna de embedding da descrição para roteamento automático por similaridade

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-18

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mesma dimensão/fonte que a migração 0005 (document_chunk.embedding) — parte
# do DDL, não da configuração de runtime; mudar EMBEDDING_DIM exige nova
# migração, não só trocar a variável de ambiente.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.add_column(
        "skill",
        sa.Column("description_embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_skill_description_embedding ON skill "
        "USING hnsw (description_embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_skill_description_embedding")
    op.drop_column("skill", "description_embedding")
