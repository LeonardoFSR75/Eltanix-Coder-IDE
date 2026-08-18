"""Extensões: estado runtime (ativação, versão, update pendente) em Postgres

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_state",
        sa.Column("extension_id", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_version", sa.String(length=64), nullable=True),
        sa.Column("pending_update_json", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("extension_id"),
    )

    op.create_table(
        "extension_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auto_update_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_timestamp", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("extension_settings")
    op.drop_table("extension_state")
