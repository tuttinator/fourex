"""add is_admin column to user_identities

Revision ID: 20260430_000003
Revises: 20260430_000002
Create Date: 2026-04-30 00:00:03

Phase 3 of the map system overhaul introduces the admin role that
gates the saved-map authoring surface. Admin membership is sourced
from an env-var allowlist (``ADMIN_EMAIL_ALLOWLIST``) and re-synced
on every Auth.js verify, so this column mirrors deployment config
rather than acting as the source of truth. Default ``false`` so
every existing identity is non-admin until they sign in again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260430_000003"
down_revision: str | None = "20260430_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_identities",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_identities", "is_admin")
