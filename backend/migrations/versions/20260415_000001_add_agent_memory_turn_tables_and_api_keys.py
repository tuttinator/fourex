"""add agent memory, turn snapshots/actions, and player api keys

Revision ID: 20260415_000001
Revises:
Create Date: 2026-04-15 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260415_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("scratchpad_text", sa.String(length=4000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "char_length(scratchpad_text) <= 4000", name="ck_agent_memory_text_len"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "player_id", "turn_number", name="uq_agent_memory"
        ),
    )
    op.create_index(
        "idx_agent_memory_lookup",
        "agent_memory",
        ["game_id", "player_id", "turn_number"],
    )

    op.create_table(
        "turn_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "player_id", "turn_number", name="uq_turn_snapshot"
        ),
    )
    op.create_index(
        "idx_turn_snapshot_lookup",
        "turn_snapshots",
        ["game_id", "player_id", "turn_number"],
    )

    op.create_table(
        "turn_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "actions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "player_id", "turn_number", name="uq_turn_action"
        ),
    )
    op.create_index(
        "idx_turn_action_lookup",
        "turn_actions",
        ["game_id", "player_id", "turn_number"],
    )

    op.create_table(
        "player_api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "player_id", name="uq_player_api_keys_game_player"
        ),
        sa.UniqueConstraint("key_hash", name="uq_player_api_keys_hash"),
    )
    op.create_index(
        "idx_player_api_keys_lookup",
        "player_api_keys",
        ["game_id", "player_id"],
    )
    op.create_index(
        "idx_player_api_keys_expiry",
        "player_api_keys",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_player_api_keys_expiry", table_name="player_api_keys")
    op.drop_index("idx_player_api_keys_lookup", table_name="player_api_keys")
    op.drop_table("player_api_keys")

    op.drop_index("idx_turn_action_lookup", table_name="turn_actions")
    op.drop_table("turn_actions")

    op.drop_index("idx_turn_snapshot_lookup", table_name="turn_snapshots")
    op.drop_table("turn_snapshots")

    op.drop_index("idx_agent_memory_lookup", table_name="agent_memory")
    op.drop_table("agent_memory")
