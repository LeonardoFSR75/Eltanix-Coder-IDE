"""Busca lexical ciente de código: split de identificadores + pg_trgm

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-30

Dois buracos na metade lexical da busca híbrida, medidos no Postgres real:

    to_tsvector('simple', 'getUserById')   -> 'getuserbyid'
    to_tsvector('simple', 'get_user_by_id') -> 'get','user','by','id'

Ou seja: procurar `getUserById` nunca encontrava `get_user_by_id`, e vice-versa.
Num índice de código isso não é caso de borda — é a forma mais comum de
procurar. O embedding às vezes salvava; quando a pergunta era o identificador
exato (justamente onde o vetor é fraco), não salvava.

A correção é uma função IMMUTABLE no banco, `eltanix_split_identifiers`, usada
**tanto** na coluna gerada quanto na montagem da tsquery. Ficar no banco em vez
de num helper Python é deliberado: a expressão do índice e a da consulta têm de
ser byte a byte a mesma, e um helper que cada store chamasse do seu jeito é
exatamente como elas divergiriam.

O `pg_trgm` entra como terceiro sinal da fusão (só em `code_chunk`): nome
parcial e erro de digitação em identificador não são recuperados nem pelo vetor
nem pelo full-text.

Custo: recriar coluna gerada exige DROP + ADD, o que reescreve as três tabelas
de chunk. Em índice grande isso demora — é migração de janela, não de deploy
quente.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `([a-z0-9])([A-Z])` separa `getUser` -> `get User`.
# `([A-Z]+)([A-Z][a-z])` separa a sigla colada: `HTTPServer` -> `HTTP Server`.
# Sem a segunda, `HTTPServer` continuaria um token só.
# Raw string obrigatória: `\1` numa string Python comum é escape octal e vira
# chr(1) — a função ia para o banco substituindo por bytes de controle em vez
# de back-references, e o split silenciosamente destruía o texto.
_SPLIT_FN = r"""
CREATE OR REPLACE FUNCTION eltanix_split_identifiers(txt text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$
    SELECT regexp_replace(
        regexp_replace(txt, '([a-z0-9])([A-Z])', '\1 \2', 'g'),
        '([A-Z]+)([A-Z][a-z])', '\1 \2', 'g'
    )
$$
"""

# O conteúdo original entra junto do separado: quem colar `getuserbyid` inteiro
# e minúsculo continua achando. O tsvector deduplica lexema, então o custo em
# disco é só o dos tokens novos, não o dobro do texto.
_TSV_EXPR = (
    "to_tsvector('simple', {col} || ' ' || eltanix_split_identifiers({col}))"
)

_TABELAS = (
    ("code_chunk", "content", "ix_code_chunk_tsv"),
    ("document_chunk", "content", "ix_document_chunk_tsv"),
    ("note_chunk", "content", "ix_note_chunk_tsv"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(_SPLIT_FN)

    for tabela, coluna, indice in _TABELAS:
        op.execute(f"DROP INDEX IF EXISTS {indice}")
        # Coluna gerada não aceita ALTER da expressão: só DROP + ADD.
        op.execute(f"ALTER TABLE {tabela} DROP COLUMN IF EXISTS tsv")
        op.execute(
            f"ALTER TABLE {tabela} ADD COLUMN tsv tsvector "
            f"GENERATED ALWAYS AS ({_TSV_EXPR.format(col=coluna)}) STORED"
        )
        op.execute(f"CREATE INDEX {indice} ON {tabela} USING GIN (tsv)")

    # Trigram só onde há identificador: `symbol` e `path` de código. Documento e
    # nota são prosa — trigram ali devolveria vizinhança de palavra comum, não
    # nome parecido.
    op.execute(
        "CREATE INDEX ix_code_chunk_symbol_trgm ON code_chunk "
        "USING GIN (symbol gin_trgm_ops) WHERE symbol IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_code_chunk_path_trgm ON code_chunk USING GIN (path gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunk_path_trgm")
    op.execute("DROP INDEX IF EXISTS ix_code_chunk_symbol_trgm")

    for tabela, coluna, indice in _TABELAS:
        op.execute(f"DROP INDEX IF EXISTS {indice}")
        op.execute(f"ALTER TABLE {tabela} DROP COLUMN IF EXISTS tsv")
        op.execute(
            f"ALTER TABLE {tabela} ADD COLUMN tsv tsvector "
            f"GENERATED ALWAYS AS (to_tsvector('simple', {coluna})) STORED"
        )
        op.execute(f"CREATE INDEX {indice} ON {tabela} USING GIN (tsv)")

    op.execute("DROP FUNCTION IF EXISTS eltanix_split_identifiers(text)")
