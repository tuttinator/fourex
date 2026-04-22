"""add archive columns to games

Revision ID: 20260422_000002
Revises: 20260422_000001
Create Date: 2026-04-22 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260422_000002"
down_revision: str | None = "20260422_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column(
        "games", sa.Column("archived_reason", sa.String(length=50), nullable=True)
    )
    op.create_index("idx_game_archived_at", "games", ["archived_at"])


def downgrade() -> None:
    op.drop_index("idx_game_archived_at", table_name="games")
    op.drop_column("games", "archived_reason")
    op.drop_column("games", "archived_at")
