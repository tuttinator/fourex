"""add saved_maps table

Revision ID: 20260430_000004
Revises: 20260430_000003
Create Date: 2026-04-30 00:00:04

Phase 4 of the map system overhaul. Admin-authored saved maps live
in their own table and surface alongside parametric templates in
the lobby drop-down via the ``saved:<id>`` namespace. Tiles and
spawn zones are stored as JSONB so the editor can write whole-map
diffs in one shot and the lobby resolver can read them in one
fetch. ``name`` is unique so the lobby drop-down can present a
clean per-map row without resolving collisions on the client.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260430_000004"
down_revision: str | None = "20260430_000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_maps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("tiles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "spawn_zones", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_identities.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_saved_maps_name"),
    )
    op.create_index("idx_saved_maps_created_by", "saved_maps", ["created_by"])
    op.create_index("idx_saved_maps_updated_at", "saved_maps", ["updated_at"])


def downgrade() -> None:
    op.drop_index("idx_saved_maps_updated_at", table_name="saved_maps")
    op.drop_index("idx_saved_maps_created_by", table_name="saved_maps")
    op.drop_table("saved_maps")
