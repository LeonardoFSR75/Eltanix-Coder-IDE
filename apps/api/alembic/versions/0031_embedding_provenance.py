"""Proveniência do vetor: `embedding_model` nas tabelas com embedding

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-30

Sem esta coluna, trocar o perfil de embedding mistura espaços vetoriais no
mesmo índice sem nenhum sinal: a distância de cosseno entre vetores de modelos
diferentes é ruído, e a busca continua devolvendo resultados — piores, sem
explicação. A partir daqui a busca filtra pelo modelo que gerou o vetor da
query (ver `context/store.py::hybrid_search`).

Linhas antigas ficam com NULL de propósito: são vetores de proveniência
desconhecida. Com `embedding_model` informado na busca elas param de aparecer
no ramo vetorial (continuam achaveis por full-text) e voltam ao índice na
próxima reindexação, já etiquetadas.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (tabela, coluna de vetor a que a proveniência se refere) — a coluna nova
# chama-se `embedding_model` em todas, inclusive em `skill`, onde o vetor é
# `description_embedding` e é o único da tabela.
_TABELAS = (
    "code_chunk",
    "document_chunk",
    "note_chunk",
    "graph_node",
    "skill",
)


def upgrade() -> None:
    for tabela in _TABELAS:
        op.add_column(
            tabela,
            sa.Column("embedding_model", sa.String(length=128), nullable=True),
        )

    # A busca filtra por `embedding_model` junto do `IS NOT NULL` do vetor; sem
    # índice, o filtro vira scan sobre o que o HNSW devolveu. Parcial porque
    # linha sem vetor nunca entra no ramo vetorial.
    op.execute(
        "CREATE INDEX ix_code_chunk_embedding_model ON code_chunk (workspace, embedding_model) "
        "WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_document_chunk_embedding_model ON document_chunk (embedding_model) "
        "WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_note_chunk_embedding_model ON note_chunk (embedding_model) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_note_chunk_embedding_model")
    op.execute("DROP INDEX IF EXISTS ix_document_chunk_embedding_model")
    op.execute("DROP INDEX IF EXISTS ix_code_chunk_embedding_model")
    for tabela in reversed(_TABELAS):
        op.drop_column(tabela, "embedding_model")
