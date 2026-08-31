"""Graphify: graph_node, graph_edge, graph_chunk_mapping, graph_metrics

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-07

"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def upgrade() -> None:
    op.create_table(
        "graph_node",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("canonical_id", sa.String(length=1024), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace", "canonical_id", name="uq_graph_node_workspace_canonical"),
    )
    op.create_index("ix_graph_node_workspace_type", "graph_node", ["workspace", "entity_type"])

    op.execute(
        "ALTER TABLE graph_node ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(summary, ''))) STORED"
    )
    op.execute("CREATE INDEX ix_graph_node_tsv ON graph_node USING GIN (tsv)")
    op.execute(
        "CREATE INDEX ix_graph_node_embedding ON graph_node USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "graph_edge",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("layer", sa.SmallInteger(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False, server_default="1.0000"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_id"], ["graph_node.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["graph_node.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "target_id", "relation_type", name="uq_graph_edge_src_tgt_type"),
    )
    op.create_index("ix_graph_edge_source", "graph_edge", ["source_id", "relation_type"])
    op.create_index("ix_graph_edge_target", "graph_edge", ["target_id", "relation_type"])
    op.create_index("ix_graph_edge_workspace_layer", "graph_edge", ["workspace", "layer"])

    op.create_table(
        "graph_chunk_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_type", sa.String(length=32), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "relevance_score",
            sa.Numeric(precision=5, scale=4),
            server_default="1.0000",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["graph_node.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_chunk_mapping_node", "graph_chunk_mapping", ["node_id"])
    op.create_index("ix_graph_chunk_mapping_chunk", "graph_chunk_mapping", ["chunk_id", "chunk_type"])

    op.create_table(
        "graph_metrics",
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace", sa.String(length=255), nullable=False),
        sa.Column("in_degree", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("out_degree", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pagerank", sa.Numeric(precision=10, scale=8), nullable=False, server_default="0.0"),
        sa.Column("betweenness", sa.Numeric(precision=10, scale=8), nullable=False, server_default="0.0"),
        sa.Column("community_id", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "last_calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["graph_node.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("node_id"),
    )
    # `in_degree`/`out_degree` são NOT NULL, então a expressão nunca resulta em
    # NULL — a coluna gerada acompanha o `nullable=False` do modelo.
    op.execute(
        "ALTER TABLE graph_metrics ADD COLUMN is_orphan boolean "
        "GENERATED ALWAYS AS (in_degree = 0 AND out_degree = 0) STORED NOT NULL"
    )
    op.create_index("ix_graph_metrics_workspace_pagerank", "graph_metrics", ["workspace", "pagerank"])


def downgrade() -> None:
    op.drop_table("graph_metrics")
    op.drop_table("graph_chunk_mapping")
    op.drop_table("graph_edge")
    op.drop_table("graph_node")
