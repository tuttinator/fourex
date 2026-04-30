"""wipe legacy game data for terrain enum overhaul

Revision ID: 20260430_000001
Revises: 20260426_000003
Create Date: 2026-04-30 00:00:01

Phase 1 of the map system overhaul renames the ``PLAINS`` terrain enum
value to ``GRASS`` and adds ``HILLS`` / ``DESERT`` / ``SWAMP``. Existing
games and snapshots reference the old values inside JSONB blobs and
would render incorrectly (or trip enum validation) under the new
schema. Per the PRD: "existing games are abandoned (database wipe) — no
data migration." This revision truncates every table that holds game,
turn, snapshot, action, prompt, agent-memory, lobby-invite, or
verification-token state. Identity tables (``user_identities``,
``player_api_keys``) are preserved so signed-in users keep their
session and admin assignment.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260430_000001"
down_revision: str | None = "20260426_000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables wiped, ordered so FK-dependent rows go first. ``games`` is the
# anchor of the FK graph; everything else references it.
_WIPE_TABLES: tuple[str, ...] = (
    "lobby_invites",
    "agent_memory",
    "turn_snapshots",
    "turn_actions",
    "player_actions",
    "prompt_logs",
    "game_turns",
    "game_snapshots",
    "auth_verification_tokens",
    "games",
)


def upgrade() -> None:
    # ``TRUNCATE ... CASCADE`` drops dependent rows in one shot regardless of
    # the iteration order, but iterating explicitly keeps the operator-facing
    # log readable when a table doesn't exist on a given environment.
    for table in _WIPE_TABLES:
        op.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")


def downgrade() -> None:
    # Wipes are not reversible. The downgrade is a no-op so re-running
    # ``alembic downgrade`` doesn't error out, but the data is gone.
    pass
