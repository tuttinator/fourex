"""add map_template column to games

Revision ID: 20260430_000002
Revises: 20260430_000001
Create Date: 2026-04-30 00:00:02

Phase 2 of the map system overhaul adds a parametric map template
registry. ``Game.map_template`` records which template generated the
map so the lobby controller can re-derive spawn zones deterministically
at start time and so future readers (UI, replay) can display the choice
back to the user. Default ``random`` reproduces the legacy noise
behaviour for any existing rows that pre-date the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260430_000002"
down_revision: str | None = "20260430_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column(
            "map_template",
            sa.String(length=64),
            nullable=False,
            server_default="random",
        ),
    )


def downgrade() -> None:
    op.drop_column("games", "map_template")
