"""Alarga user_mfa.secret para caber o envelope AES-GCM (F-7)

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-29

O segredo TOTP passa a ser cifrado em repouso quando `ELTANIX_MFA_SECRET_KEY`
está definida (ver `auth/secret_box.py`). O envelope (`enc:v1:` + base64 de
nonce+ciphertext+tag) não cabe nos 64 chars originais do base32 cru.
Sem alteração de dado: valores em claro existentes continuam válidos e são
re-cifrados na próxima autenticação bem-sucedida.

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "user_mfa",
        "secret",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Truncaria segredos cifrados — só é seguro com MFA sem cifra ativa.
    op.alter_column(
        "user_mfa",
        "secret",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
