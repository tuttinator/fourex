"""add resignation audit columns to games

Revision ID: 20260422_000001
Revises: 20260419_000002
Create Date: 2026-04-22 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260422_000001"
down_revision: str | None = "20260419_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("resigned_at", sa.DateTime(), nullable=True))
    op.add_column(
        "games", sa.Column("resigned_by", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "games", sa.Column("end_reason", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("games", "end_reason")
    op.drop_column("games", "resigned_by")
    op.drop_column("games", "resigned_at")
