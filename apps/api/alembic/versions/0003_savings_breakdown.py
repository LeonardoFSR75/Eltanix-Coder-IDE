"""Detalhamento da economia por técnica

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sem o detalhamento por técnica, `tokens_saved` diz que houve economia mas
    # não qual engine a produziu — e aí não há como saber qual delas vale manter.
    op.add_column(
        "request_log",
        sa.Column(
            "savings_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "request_log",
        sa.Column("complexity", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("request_log", "complexity")
    op.drop_column("request_log", "savings_breakdown")
