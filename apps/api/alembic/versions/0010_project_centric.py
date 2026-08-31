"""Arquitetura Orientada a Projetos: project_record e project_slug

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Tabela project_record
    op.create_table(
        "project_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("git_url", sa.String(length=512), nullable=True),
        sa.Column("default_branch", sa.String(length=128), nullable=False, server_default="main"),
        sa.Column("budget_limit_usd", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Índice único — bate com `unique=True, index=True` no modelo
    # `ProjectRecord.slug`.
    op.create_index("ix_project_record_slug", "project_record", ["slug"], unique=True)

    # 2. Adicionar project_slug nas tabelas de telemetria, auditoria, notas e documentos
    op.add_column("request_log", sa.Column("project_slug", sa.String(length=128), nullable=True))
    op.create_index("ix_request_log_project_slug", "request_log", ["project_slug"])

    op.add_column("audit_log", sa.Column("project_slug", sa.String(length=128), nullable=True))
    op.create_index("ix_audit_log_project_slug", "audit_log", ["project_slug"])

    op.add_column("note", sa.Column("project_slug", sa.String(length=128), nullable=True))
    op.create_index("ix_note_project_slug", "note", ["project_slug"])

    op.add_column("document", sa.Column("project_slug", sa.String(length=128), nullable=True))
    op.create_index("ix_document_project_slug", "document", ["project_slug"])


def downgrade() -> None:
    op.drop_index("ix_document_project_slug", table_name="document")
    op.drop_column("document", "project_slug")

    op.drop_index("ix_note_project_slug", table_name="note")
    op.drop_column("note", "project_slug")

    op.drop_index("ix_audit_log_project_slug", table_name="audit_log")
    op.drop_column("audit_log", "project_slug")

    op.drop_index("ix_request_log_project_slug", table_name="request_log")
    op.drop_column("request_log", "project_slug")

    op.drop_index("ix_project_record_slug", table_name="project_record")
    op.drop_table("project_record")
