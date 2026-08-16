"""Coluna is_admin em app_user

Achado na auditoria arquitetural (docs/proposals/plano-implementacao-
auditoria-arquitetural.md, Horizonte 2, "RBAC com enforcement"): `project_member`
(migração 0018) guarda o papel por projeto, mas nada distinguia um usuário
"dono da instância" de um convidado comum — sem isso, toda operação
administrativa (criar usuário, gerenciar membro de qualquer projeto, listar
todos os projetos) precisaria de uma tabela de papel separada só para isso.
Reaproveita o próprio usuário seed (`AuthService.ensure_seed_user`) como o
primeiro admin: continua sendo o único usuário até alguém ser convidado, e
passa a ser automaticamente quem pode convidar. Nula não faz sentido aqui
(ao contrário de `RequestLog.session_id`) — todo usuário tem um valor
definido, `False` por padrão para qualquer usuário criado depois do seed.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # O primeiro usuário (criado antes desta coluna existir, via
    # `ensure_seed_user`) é sempre o admin original — sem isto, uma base já
    # em produção ficaria sem nenhum admin depois de migrar.
    op.execute(
        """
        UPDATE app_user SET is_admin = true
        WHERE id = (SELECT id FROM app_user ORDER BY created_at ASC LIMIT 1)
        """
    )


def downgrade() -> None:
    op.drop_column("app_user", "is_admin")
