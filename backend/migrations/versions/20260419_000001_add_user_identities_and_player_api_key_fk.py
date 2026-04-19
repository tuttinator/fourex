"""add user_identities table and user_identity_id FK on player_api_keys

Revision ID: 20260419_000001
Revises: 20260417_000001
Create Date: 2026-04-19 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260419_000001"
down_revision: str | None = "20260417_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_identities_email"),
    )
    op.create_index(
        "idx_user_identities_email",
        "user_identities",
        ["email"],
    )

    op.add_column(
        "player_api_keys",
        sa.Column("user_identity_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_player_api_keys_user_identity",
        "player_api_keys",
        "user_identities",
        ["user_identity_id"],
        ["id"],
    )
    op.create_index(
        "idx_player_api_keys_user_identity",
        "player_api_keys",
        ["user_identity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_player_api_keys_user_identity", table_name="player_api_keys"
    )
    op.drop_constraint(
        "fk_player_api_keys_user_identity", "player_api_keys", type_="foreignkey"
    )
    op.drop_column("player_api_keys", "user_identity_id")

    op.drop_index("idx_user_identities_email", table_name="user_identities")
    op.drop_table("user_identities")
