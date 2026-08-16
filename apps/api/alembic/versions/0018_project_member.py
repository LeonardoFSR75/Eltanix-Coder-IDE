"""Papel de usuário por projeto: project_member

Etapa 2 do login obrigatório (ver docstring de `0012_auth.py::upgrade` e de
`AppUser` em `db/models.py`), que já reservava exatamente este nome de tabela.
Só o schema por enquanto — nenhuma rota ainda filtra por `project_member` nem
a preenche automaticamente; isso é enforcement, o próximo passo (ver
docs/proposals/plano-implementacao-auditoria-arquitetural.md, Horizonte 2).

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="owner"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_project_member_project_user",
        "project_member",
        ["project_id", "user_id"],
        unique=True,
    )
    op.create_index("ix_project_member_user", "project_member", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_member_user", table_name="project_member")
    op.drop_index("uq_project_member_project_user", table_name="project_member")
    op.drop_table("project_member")
