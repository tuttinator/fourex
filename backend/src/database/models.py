"""
SQLAlchemy database models for 4X game persistence.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""


class Game(Base):
    """Game instance table."""

    __tablename__ = "games"

    # Primary fields
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # Map configuration
    map_width: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    map_height: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    rng_state: Mapped[int] = mapped_column(Integer, nullable=False)

    # Lobby configuration
    player_slots: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    creator: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Game state
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    players: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Lobby slot configuration. Each entry is a dict with at least
    # ``slot_index`` (int), ``type`` ("human" | "agent"), ``name`` (str |
    # None — the seated player's display name), ``reserved_email`` (str |
    # None) and ``player_api_key_id`` (int | None) referencing the active
    # ``PlayerApiKey`` row for that slot. Nullable for backwards
    # compatibility — legacy rows are interpreted as all-Human slots
    # derived from ``players`` (see ``derive_slots_from_players``).
    lobby_slots: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )

    # Status and metadata
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    winner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    victory_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Phase 3 (spectated-agents): resignation audit + canonical end-of-game
    # reason. ``end_reason`` is the single enum the frontend reads to know
    # *why* a game ended: ``domination`` | ``score`` | ``resignation`` |
    # ``abandoned``. Reverse-engineering that from ``resigned_at`` +
    # ``archived_reason`` is brittle, so the column is introduced alongside
    # the resignation feature.
    resigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Phase 4 (spectated-agents): soft archive. ``archived_at`` flags the
    # game as hidden from the default list; ``archived_reason`` is the
    # canonical enum ``manual`` | ``stale_waiting`` | ``stale_active``.
    # Archiving preserves all snapshot/turn history; there is no hard
    # delete path.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Turn timing (set when the game becomes active or a new turn starts)
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    turns = relationship(
        "GameTurn", back_populates="game", cascade="all, delete-orphan"
    )
    agent_memories = relationship(
        "AgentMemory", back_populates="game", cascade="all, delete-orphan"
    )
    turn_snapshots = relationship(
        "TurnSnapshot", back_populates="game", cascade="all, delete-orphan"
    )
    turn_actions = relationship(
        "TurnAction", back_populates="game", cascade="all, delete-orphan"
    )
    player_api_keys = relationship(
        "PlayerApiKey", back_populates="game", cascade="all, delete-orphan"
    )
    prompt_logs = relationship(
        "PromptLog", back_populates="game", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_game_status", "status"),
        Index("idx_game_created", "created_at"),
        Index("idx_game_updated", "updated_at"),
        Index("idx_game_archived_at", "archived_at"),
    )


class GameTurn(Base):
    """Game turn processing results."""

    __tablename__ = "game_turns"

    # Primary fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Turn data
    player_actions: Mapped[dict[str, list[dict[str, Any]]]] = mapped_column(
        JSON, nullable=False
    )
    action_results: Mapped[dict[str, list[dict[str, Any]]]] = mapped_column(
        JSON, nullable=False
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Processing metrics
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    game = relationship("Game", back_populates="turns")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("game_id", "turn_number", name="uq_game_turn"),
        Index("idx_turn_game_turn", "game_id", "turn_number"),
        Index("idx_turn_completed", "completed_at"),
    )


class PlayerAction(Base):
    """Individual player actions submitted during a turn."""

    __tablename__ = "player_actions"

    # Primary fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Action data
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Processing results
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Indexes
    __table_args__ = (
        Index("idx_action_game_turn_player", "game_id", "turn_number", "player_id"),
        Index("idx_action_type", "action_type"),
        Index("idx_action_submitted", "submitted_at"),
    )


class PromptLog(Base):
    """LLM prompt and response logs."""

    __tablename__ = "prompt_logs"

    # Primary fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # LLM interaction data
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)

    # Token and performance metrics
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Additional context
    turn_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thinking_tokens: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    # Relationships
    game = relationship("Game", back_populates="prompt_logs")

    # Indexes
    __table_args__ = (
        Index("idx_prompt_game_player", "game_id", "player_id"),
        Index("idx_prompt_turn", "turn_number"),
        Index("idx_prompt_provider", "llm_provider"),
        Index("idx_prompt_created", "created_at"),
    )


class AgentMemory(Base):
    """Per-player scratchpad and structured memory persisted for a specific turn."""

    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scratchpad_text: Mapped[str] = mapped_column(String(4000), nullable=False)
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    game = relationship("Game", back_populates="agent_memories")

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", "turn_number", name="uq_agent_memory"),
        CheckConstraint(
            "char_length(scratchpad_text) <= 4000", name="ck_agent_memory_text_len"
        ),
        Index("idx_agent_memory_lookup", "game_id", "player_id", "turn_number"),
    )


class TurnSnapshot(Base):
    """Fog-of-war-redacted game state for a player on a turn."""

    __tablename__ = "turn_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    game = relationship("Game", back_populates="turn_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "player_id", "turn_number", name="uq_turn_snapshot"
        ),
        Index("idx_turn_snapshot_lookup", "game_id", "player_id", "turn_number"),
    )


class TurnAction(Base):
    """Submitted player actions for a turn."""

    __tablename__ = "turn_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    actions_json: Mapped[list[dict[str, Any]] | dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    game = relationship("Game", back_populates="turn_actions")

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", "turn_number", name="uq_turn_action"),
        Index("idx_turn_action_lookup", "game_id", "player_id", "turn_number"),
    )


class PlayerApiKey(Base):
    """Hashed API key for a player within a game."""

    __tablename__ = "player_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_identity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_identities.id"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    game = relationship("Game", back_populates="player_api_keys")
    user_identity = relationship("UserIdentity", back_populates="api_keys")

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_player_api_keys_game_player"),
        UniqueConstraint("key_hash", name="uq_player_api_keys_hash"),
        Index("idx_player_api_keys_lookup", "game_id", "player_id"),
        Index("idx_player_api_keys_expiry", "expires_at"),
        Index("idx_player_api_keys_user_identity", "user_identity_id"),
    )


class UserIdentity(Base):
    """Verified human identity behind a browser session.

    Populated by a Next.js server route the first time an Auth.js magic-link
    verify succeeds for a given email. Referenced by PlayerApiKey so that
    human-minted keys can be attributed back to the user; MCP-minted keys
    leave user_identity_id null.
    """

    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    api_keys = relationship("PlayerApiKey", back_populates="user_identity")

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_identities_email"),
        Index("idx_user_identities_email", "email"),
    )


class AuthVerificationToken(Base):
    """Auth.js magic-link verification tokens.

    Written by the Next.js Auth.js adapter when the Resend provider issues a
    magic link; consumed (atomically read + delete) when the user clicks it.
    A composite (identifier, token) primary key matches the Auth.js adapter
    contract where ``useVerificationToken({identifier, token})`` looks the
    row up by both.
    """

    __tablename__ = "auth_verification_tokens"

    identifier: Mapped[str] = mapped_column(String(320), primary_key=True)
    token: Mapped[str] = mapped_column(String(255), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_auth_verification_tokens_expiry", "expires_at"),)


class GameSnapshot(Base):
    """Periodic snapshots of complete game state for recovery."""

    __tablename__ = "game_snapshots"

    # Primary fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("games.id"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot data
    complete_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Metadata
    snapshot_type: Mapped[str] = mapped_column(
        String(50), default="periodic", nullable=False
    )  # periodic, manual, pre_critical

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("idx_snapshot_game_turn", "game_id", "turn_number"),
        Index("idx_snapshot_hash", "state_hash"),
        Index("idx_snapshot_created", "created_at"),
    )


class PlayerStats(Base):
    """Aggregated player statistics across games."""

    __tablename__ = "player_stats"

    # Primary fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Game statistics
    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    games_won: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_turns: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Performance metrics
    avg_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_game_duration: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # minutes

    # Victory types
    domination_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("player_id", name="uq_player_stats"),
        Index("idx_player_stats_wins", "games_won"),
        Index("idx_player_stats_played", "games_played"),
    )
