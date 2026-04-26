"""add creator_user_identity_id column to games

Revision ID: 20260426_000002
Revises: 20260426_000001
Create Date: 2026-04-26 00:00:02

Phase 3 of the lobby + skill split: tracks the ``UserIdentity`` who
created a lobby so an all-Agent game (creator unticks "I'll take a
slot") can still authorise creator-only actions like Start and
slot regeneration via the Auth.js JWT path. Nullable so legacy rows
remain valid; the new ``creator_credentials`` dependency falls back to
the per-game key when the column is null.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426_000002"
down_revision: str | None = "20260426_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column(
            "creator_user_identity_id",
            sa.Integer(),
            sa.ForeignKey("user_identities.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_games_creator_user_identity",
        "games",
        ["creator_user_identity_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_games_creator_user_identity", table_name="games")
    op.drop_column("games", "creator_user_identity_id")
