"""add lobby_invites table

Revision ID: 20260426_000003
Revises: 20260426_000002
Create Date: 2026-04-26 00:00:03

Phase 5 of the lobby + skill split: human slot reservations. A
``lobby_invites`` row pins a (game, slot, email) tuple to a
single-use, hashed token with an expiry. The Resend-delivered email
embeds the plaintext token in the lobby URL; the join endpoint
verifies the hash, the email match against the caller's Auth.js
identity, expiry, and ``redeemed_at IS NULL`` before seating the
user. Tokens are hashed at rest so a DB read alone cannot mint
working invite links.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426_000003"
down_revision: str | None = "20260426_000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lobby_invites",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.String(length=255),
            sa.ForeignKey("games.id"),
            nullable=False,
        ),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_lobby_invites_game_slot",
        "lobby_invites",
        ["game_id", "slot_index"],
    )
    op.create_index(
        "idx_lobby_invites_token_hash",
        "lobby_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "idx_lobby_invites_email",
        "lobby_invites",
        ["email"],
    )


def downgrade() -> None:
    op.drop_index("idx_lobby_invites_email", table_name="lobby_invites")
    op.drop_index("idx_lobby_invites_token_hash", table_name="lobby_invites")
    op.drop_index("idx_lobby_invites_game_slot", table_name="lobby_invites")
    op.drop_table("lobby_invites")
