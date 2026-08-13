"""Resumo compacto de sessão do agente

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_session", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_session", "summary")
