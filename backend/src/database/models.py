"""
SQLAlchemy database models for 4X game persistence.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()


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

    # Game state
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    players: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Status and metadata
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    winner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    victory_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    turns = relationship(
        "GameTurn", back_populates="game", cascade="all, delete-orphan"
    )
    prompt_logs = relationship(
        "PromptLog", back_populates="game", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_game_status", "status"),
        Index("idx_game_created", "created_at"),
        Index("idx_game_updated", "updated_at"),
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
        DateTime, default=func.now(), nullable=False
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
        DateTime, default=func.now(), nullable=False
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
        DateTime, default=func.now(), nullable=False
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
        DateTime, default=func.now(), nullable=False
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
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("player_id", name="uq_player_stats"),
        Index("idx_player_stats_wins", "games_won"),
        Index("idx_player_stats_played", "games_played"),
    )  # Timestamps
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("player_id", name="uq_player_stats"),
        Index("idx_player_stats_wins", "games_won"),
        Index("idx_player_stats_played", "games_played"),
    )
