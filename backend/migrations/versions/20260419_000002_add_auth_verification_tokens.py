"""add auth_verification_tokens table for Auth.js magic-link adapter

Revision ID: 20260419_000002
Revises: 20260419_000001
Create Date: 2026-04-19 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260419_000002"
down_revision: str | None = "20260419_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_verification_tokens",
        sa.Column("identifier", sa.String(length=320), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "identifier", "token", name="pk_auth_verification_tokens"
        ),
    )
    op.create_index(
        "idx_auth_verification_tokens_expiry",
        "auth_verification_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_auth_verification_tokens_expiry",
        table_name="auth_verification_tokens",
    )
    op.drop_table("auth_verification_tokens")
