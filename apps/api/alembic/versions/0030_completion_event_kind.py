"""completion_event ganha kind + jump_lines — predição do próximo edit (ADR 0015)

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-30

`completion_event` deixa de ser só autocompletar inline: `kind` separa
`inline` (ADR 0014) de `next_edit` (ADR 0015). `jump_lines` é a distância em
linhas do cursor até o trecho previsto — sinal só do next_edit.
Linhas existentes são `inline` (o server_default cobre o backfill).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "completion_event",
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default="inline",
            nullable=False,
        ),
    )
    op.add_column(
        "completion_event",
        sa.Column("jump_lines", sa.Integer(), nullable=True),
    )
    op.create_index("ix_completion_event_kind", "completion_event", ["kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_completion_event_kind", table_name="completion_event")
    op.drop_column("completion_event", "jump_lines")
    op.drop_column("completion_event", "kind")
