from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from eltanix.config import get_settings
from eltanix.db.base import Base
from eltanix.db import models  # noqa: F401  (registra as tabelas no metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


# Índices que saem de `op.execute()` com DDL cru porque não cabem em
# `op.create_table`/`op.create_index` (ver apps/api/CLAUDE.md, "Migração nova"):
# HNSW do pgvector e GIN sobre as colunas `tsv` (`GENERATED ALWAYS AS
# (to_tsvector(...)) STORED`). O autogenerate do Alembic não introspecta nem o
# acesso `hnsw` nem o índice sobre coluna gerada, então `alembic check`
# proporia um DROP fantasma em toda execução. Ficam fora da comparação — a
# checagem de tipo abaixo cobre qualquer índice futuro sobre coluna Vector/
# TSVECTOR, e o conjunto explícito é a rede de segurança se a reflexão não
# trouxer as colunas do índice HNSW.
_UNINTROSPECTABLE_INDEXES = frozenset(
    {
        "ix_code_chunk_tsv",
        "ix_code_chunk_embedding",
        "ix_document_chunk_tsv",
        "ix_document_chunk_embedding",
        "ix_note_chunk_tsv",
        "ix_note_chunk_embedding",
        "ix_graph_node_tsv",
        "ix_graph_node_embedding",
        "ix_cached_response_embedding_vector",
        "ix_skill_description_embedding",
    }
)


def _include_object(object_, name, type_, reflected, compare_to) -> bool:
    if type_ == "index":
        if name in _UNINTROSPECTABLE_INDEXES:
            return False
        cols = list(getattr(object_, "columns", []) or [])
        if any(isinstance(getattr(col, "type", None), (Vector, TSVECTOR)) for col in cols):
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
