"""baseline schema — tables historically created by ``Base.metadata.create_all``

Revision ID: 20260414_000001
Revises:
Create Date: 2026-04-14 00:00:00

Establishes Alembic as the sole owner of the schema. Prior to this
revision the baseline tables (``games``, ``game_turns``,
``player_actions``, ``prompt_logs``, ``game_snapshots``,
``player_stats``) were materialised by ``Base.metadata.create_all``
from the FastAPI lifespan's ``init_db``; Alembic was adopted mid-
project for incremental deltas and its first revision
(``20260415_000001``) assumes these tables already exist. That gap
made ``alembic upgrade head`` fail against a fresh database.

This baseline captures those tables exactly as they looked *before*
any later migration touched them — so the chain
``upgrade base -> head`` now produces the same schema that
``create_all`` used to, with no external bootstrap step required.

The ``games`` table in particular drops the columns later added by
``20260422_000001`` (``resigned_at`` / ``resigned_by`` /
``end_reason``) and ``20260422_000002`` (``archived_at`` /
``archived_reason`` plus the ``idx_game_archived_at`` index) so
those add-column migrations remain a no-op delta on top of the
baseline.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260414_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("map_width", sa.Integer(), nullable=False),
        sa.Column("map_height", sa.Integer(), nullable=False),
        sa.Column("rng_state", sa.Integer(), nullable=False),
        sa.Column("player_slots", sa.Integer(), nullable=False),
        sa.Column("creator", sa.String(length=255), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("players", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("winner", sa.String(length=255), nullable=True),
        sa.Column("victory_type", sa.String(length=50), nullable=True),
        sa.Column("turn_started_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_game_status", "games", ["status"])
    op.create_index("idx_game_created", "games", ["created_at"])
    op.create_index("idx_game_updated", "games", ["updated_at"])

    op.create_table(
        "game_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("player_actions", sa.JSON(), nullable=False),
        sa.Column("action_results", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "turn_number", name="uq_game_turn"),
    )
    op.create_index("idx_turn_game_turn", "game_turns", ["game_id", "turn_number"])
    op.create_index("idx_turn_completed", "game_turns", ["completed_at"])

    op.create_table(
        "player_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("action_data", sa.JSON(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_action_game_turn_player",
        "player_actions",
        ["game_id", "turn_number", "player_id"],
    )
    op.create_index("idx_action_type", "player_actions", ["action_type"])
    op.create_index("idx_action_submitted", "player_actions", ["submitted_at"])

    op.create_table(
        "prompt_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=True),
        sa.Column("llm_provider", sa.String(length=100), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("thinking_tokens", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_prompt_game_player", "prompt_logs", ["game_id", "player_id"])
    op.create_index("idx_prompt_turn", "prompt_logs", ["turn_number"])
    op.create_index("idx_prompt_provider", "prompt_logs", ["llm_provider"])
    op.create_index("idx_prompt_created", "prompt_logs", ["created_at"])

    op.create_table(
        "game_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.String(length=255), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("complete_state", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_type", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_snapshot_game_turn", "game_snapshots", ["game_id", "turn_number"]
    )
    op.create_index("idx_snapshot_hash", "game_snapshots", ["state_hash"])
    op.create_index("idx_snapshot_created", "game_snapshots", ["created_at"])

    op.create_table(
        "player_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("games_played", sa.Integer(), nullable=False),
        sa.Column("games_won", sa.Integer(), nullable=False),
        sa.Column("total_turns", sa.Integer(), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=False),
        sa.Column("avg_game_duration", sa.Float(), nullable=False),
        sa.Column("domination_wins", sa.Integer(), nullable=False),
        sa.Column("score_wins", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", name="uq_player_stats"),
    )
    op.create_index("idx_player_stats_wins", "player_stats", ["games_won"])
    op.create_index("idx_player_stats_played", "player_stats", ["games_played"])


def downgrade() -> None:
    op.drop_index("idx_player_stats_played", table_name="player_stats")
    op.drop_index("idx_player_stats_wins", table_name="player_stats")
    op.drop_table("player_stats")

    op.drop_index("idx_snapshot_created", table_name="game_snapshots")
    op.drop_index("idx_snapshot_hash", table_name="game_snapshots")
    op.drop_index("idx_snapshot_game_turn", table_name="game_snapshots")
    op.drop_table("game_snapshots")

    op.drop_index("idx_prompt_created", table_name="prompt_logs")
    op.drop_index("idx_prompt_provider", table_name="prompt_logs")
    op.drop_index("idx_prompt_turn", table_name="prompt_logs")
    op.drop_index("idx_prompt_game_player", table_name="prompt_logs")
    op.drop_table("prompt_logs")

    op.drop_index("idx_action_submitted", table_name="player_actions")
    op.drop_index("idx_action_type", table_name="player_actions")
    op.drop_index("idx_action_game_turn_player", table_name="player_actions")
    op.drop_table("player_actions")

    op.drop_index("idx_turn_completed", table_name="game_turns")
    op.drop_index("idx_turn_game_turn", table_name="game_turns")
    op.drop_table("game_turns")

    op.drop_index("idx_game_updated", table_name="games")
    op.drop_index("idx_game_created", table_name="games")
    op.drop_index("idx_game_status", table_name="games")
    op.drop_table("games")
