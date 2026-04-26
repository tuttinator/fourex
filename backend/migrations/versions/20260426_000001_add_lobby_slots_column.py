"""add lobby_slots json column to games

Revision ID: 20260426_000001
Revises: 20260422_000002
Create Date: 2026-04-26 00:00:01

Phase 2 of the lobby + skill split: introduces the ``lobby_slots``
JSON column on ``games`` so per-slot type/name/key metadata can live
alongside the existing ``players`` roster. The column is nullable;
legacy rows continue to render as all-Human slots derived from
``players`` until they're rewritten by create/join/leave.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426_000001"
down_revision: str | None = "20260422_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("lobby_slots", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "lobby_slots")
