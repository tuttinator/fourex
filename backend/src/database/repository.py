"""
Database repository for game data operations.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, asc, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..game.models import Action, GameState, TurnResult
from ..game.models import PromptLog as GamePromptLog
from .models import (
    AgentMemory,
    Game,
    GameSnapshot,
    GameTurn,
    PlayerAction,
    PlayerApiKey,
    PromptLog,
    TurnAction,
    TurnSnapshot,
)


class GameRepository:
    """Repository for game data persistence operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _utcnow() -> datetime:
        """Return a naive UTC timestamp for legacy timestamp columns."""
        return datetime.now(UTC).replace(tzinfo=None)

    async def create_game(
        self,
        game_id: str,
        players: list[str],
        seed: int = 42,
        max_turns: int = 100,
        map_width: int = 20,
        map_height: int = 20,
        player_slots: int = 2,
        creator: str | None = None,
        status: str = "created",
    ) -> Game:
        """Create a new game record."""
        # Create initial game state
        initial_state = {
            "turn": 0,
            "rng_state": seed,
            "map_width": map_width,
            "map_height": map_height,
            "tiles": [],
            "units": {},
            "cities": {},
            "players": players,
            "diplomacy": {},
            "stockpiles": {},
            "next_unit_id": 1,
            "next_city_id": 1,
            "max_turns": max_turns,
        }

        game = Game(
            id=game_id,
            seed=seed,
            max_turns=max_turns,
            map_width=map_width,
            map_height=map_height,
            rng_state=seed,
            state=initial_state,
            players=players,
            player_slots=player_slots,
            creator=creator,
            status=status,
        )

        self.session.add(game)
        await self.session.flush()
        return game

    async def update_game_players(self, game_id: str, players: list[str]) -> None:
        """Update the players list for a game."""
        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(players=players, updated_at=self._utcnow())
        )

    async def update_game_status(self, game_id: str, status: str) -> None:
        """Update the status of a game."""
        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(status=status, updated_at=self._utcnow())
        )

    async def get_game(self, game_id: str) -> Game | None:
        """Get game by ID."""
        result = await self.session.execute(select(Game).where(Game.id == game_id))
        return result.scalar_one_or_none()

    async def get_game_with_turns(self, game_id: str) -> Game | None:
        """Get game with all turns loaded."""
        result = await self.session.execute(
            select(Game).options(selectinload(Game.turns)).where(Game.id == game_id)
        )
        return result.scalar_one_or_none()

    async def list_games(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Game]:
        """List games with optional filtering and sorting."""
        # Map sort_by to column
        sort_columns = {
            "created_at": Game.created_at,
            "turn": Game.turn,
            "status": Game.status,
        }
        sort_col = sort_columns.get(sort_by, Game.created_at)
        order_fn = asc if sort_order == "asc" else desc

        query = select(Game).order_by(order_fn(sort_col))

        if status:
            query = query.where(Game.status == status)

        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_games(self, status: str | None = None) -> int:
        """Count games with optional status filter."""
        query = select(func.count(Game.id))

        if status:
            query = query.where(Game.status == status)

        result = await self.session.execute(query)
        return result.scalar_one()

    async def update_game_state(self, game_id: str, state: GameState) -> None:
        """Update game state."""
        state_dict = state.model_dump(mode="json")

        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(
                state=state_dict,
                turn=state.turn,
                rng_state=state.rng_state,
                updated_at=self._utcnow(),
            )
        )

    async def save_game_state(self, game_id: str, state: GameState) -> None:
        """Save complete game state (alias for update_game_state)."""
        await self.update_game_state(game_id, state)

    async def end_game(
        self, game_id: str, winner: str | None = None, victory_type: str = "score"
    ) -> None:
        """Mark game as ended."""
        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(
                status="ended",
                winner=winner,
                victory_type=victory_type,
                ended_at=self._utcnow(),
                updated_at=self._utcnow(),
            )
        )

    async def save_turn_result(
        self,
        game_id: str,
        turn_result: TurnResult,
        player_actions: dict[str, list[Action]],
    ) -> GameTurn:
        """Save turn processing results."""
        # Convert actions to serializable format
        actions_dict = {}
        for player, actions in player_actions.items():
            actions_dict[player] = [
                action.model_dump(mode="json") for action in actions
            ]

        # Convert action results to serializable format
        results_dict = {}
        for player, results in turn_result.player_actions.items():
            results_dict[player] = [
                result.model_dump(mode="json") for result in results
            ]

        game_turn = GameTurn(
            game_id=game_id,
            turn_number=turn_result.turn,
            player_actions=actions_dict,
            action_results=results_dict,
            state_hash=turn_result.state_hash,
            completed_at=self._utcnow(),
        )

        self.session.add(game_turn)
        await self.session.flush()
        return game_turn

    async def save_player_actions(
        self, game_id: str, turn_number: int, player_id: str, actions: list[Action]
    ) -> list[PlayerAction]:
        """Save individual player actions."""
        player_actions = []

        for action in actions:
            player_action = PlayerAction(
                game_id=game_id,
                turn_number=turn_number,
                player_id=player_id,
                action_type=action.type,
                action_data=action.model_dump(mode="json"),
            )
            player_actions.append(player_action)
            self.session.add(player_action)

        await self.session.flush()
        return player_actions

    async def save_prompt_log(
        self, game_id: str, prompt_log: GamePromptLog
    ) -> PromptLog:
        """Save LLM prompt log."""
        db_prompt_log = PromptLog(
            game_id=game_id,
            player_id=prompt_log.player,
            prompt=prompt_log.prompt,
            response=prompt_log.response,
            tokens_in=prompt_log.tokens_in,
            tokens_out=prompt_log.tokens_out,
            latency_ms=prompt_log.latency_ms,
        )

        self.session.add(db_prompt_log)
        await self.session.flush()
        return db_prompt_log

    async def upsert_agent_memory(
        self, game_id: str, player_id: str, turn_number: int, scratchpad_text: str
    ) -> AgentMemory:
        """Create or update scratchpad text for a specific player turn."""
        existing = await self.get_agent_memory(game_id, player_id, turn_number)

        if existing:
            existing.scratchpad_text = scratchpad_text
            existing.updated_at = self._utcnow()
            await self.session.flush()
            return existing

        memory = AgentMemory(
            game_id=game_id,
            player_id=player_id,
            turn_number=turn_number,
            scratchpad_text=scratchpad_text,
        )
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def get_agent_memory(
        self, game_id: str, player_id: str, turn_number: int
    ) -> AgentMemory | None:
        """Read scratchpad text for a specific player turn."""
        result = await self.session.execute(
            select(AgentMemory).where(
                and_(
                    AgentMemory.game_id == game_id,
                    AgentMemory.player_id == player_id,
                    AgentMemory.turn_number == turn_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def merge_agent_memory_structured(
        self,
        game_id: str,
        player_id: str,
        turn_number: int,
        patch: dict[str, Any],
    ) -> AgentMemory:
        """Merge top-level keys from patch into structured_data for the given turn.

        Creates a new row with an empty scratchpad if no row exists for the turn.
        Top-level keys in `patch` replace matching keys in `structured_data`.
        """
        existing = await self.get_agent_memory(game_id, player_id, turn_number)

        if existing is None:
            memory = AgentMemory(
                game_id=game_id,
                player_id=player_id,
                turn_number=turn_number,
                scratchpad_text="",
                structured_data=dict(patch),
            )
            self.session.add(memory)
            await self.session.flush()
            return memory

        merged = dict(existing.structured_data or {})
        merged.update(patch)
        existing.structured_data = merged
        existing.updated_at = self._utcnow()
        await self.session.flush()
        return existing

    async def get_player_agent_memories(
        self, game_id: str, player_id: str
    ) -> list[AgentMemory]:
        """Return all agent_memory rows for a player in a game, ordered by turn ascending."""
        result = await self.session.execute(
            select(AgentMemory)
            .where(
                and_(
                    AgentMemory.game_id == game_id,
                    AgentMemory.player_id == player_id,
                )
            )
            .order_by(AgentMemory.turn_number)
        )
        return list(result.scalars().all())

    async def upsert_turn_snapshot(
        self, game_id: str, player_id: str, turn_number: int, state_json: dict[str, Any]
    ) -> TurnSnapshot:
        """Create or update a fog-of-war-redacted snapshot."""
        existing = await self.get_turn_snapshot(game_id, player_id, turn_number)

        if existing:
            existing.state_json = state_json
            await self.session.flush()
            return existing

        snapshot = TurnSnapshot(
            game_id=game_id,
            player_id=player_id,
            turn_number=turn_number,
            state_json=state_json,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def get_turn_snapshot(
        self, game_id: str, player_id: str, turn_number: int
    ) -> TurnSnapshot | None:
        """Read a specific turn snapshot."""
        result = await self.session.execute(
            select(TurnSnapshot).where(
                and_(
                    TurnSnapshot.game_id == game_id,
                    TurnSnapshot.player_id == player_id,
                    TurnSnapshot.turn_number == turn_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_turn_action(
        self,
        game_id: str,
        player_id: str,
        turn_number: int,
        actions_json: list[dict[str, Any]] | dict[str, Any],
    ) -> TurnAction:
        """Create or update submitted actions for a player turn."""
        existing = await self.get_turn_action(game_id, player_id, turn_number)

        if existing:
            existing.actions_json = actions_json
            existing.submitted_at = self._utcnow()
            await self.session.flush()
            return existing

        turn_action = TurnAction(
            game_id=game_id,
            player_id=player_id,
            turn_number=turn_number,
            actions_json=actions_json,
        )
        self.session.add(turn_action)
        await self.session.flush()
        return turn_action

    async def get_all_turn_actions(
        self, game_id: str, turn_number: int
    ) -> list[TurnAction]:
        """Get all submitted actions for a specific turn."""
        result = await self.session.execute(
            select(TurnAction).where(
                and_(
                    TurnAction.game_id == game_id,
                    TurnAction.turn_number == turn_number,
                )
            )
        )
        return list(result.scalars().all())

    async def get_turn_action(
        self, game_id: str, player_id: str, turn_number: int
    ) -> TurnAction | None:
        """Read submitted actions for a specific player turn."""
        result = await self.session.execute(
            select(TurnAction).where(
                and_(
                    TurnAction.game_id == game_id,
                    TurnAction.player_id == player_id,
                    TurnAction.turn_number == turn_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_player_turn_actions(
        self, game_id: str, player_id: str
    ) -> list[TurnAction]:
        """Get all submitted actions for a player across all turns, ordered by turn."""
        result = await self.session.execute(
            select(TurnAction)
            .where(
                and_(
                    TurnAction.game_id == game_id,
                    TurnAction.player_id == player_id,
                )
            )
            .order_by(TurnAction.turn_number)
        )
        return list(result.scalars().all())

    async def create_player_api_key(
        self,
        game_id: str,
        player_id: str,
        plaintext_key: str,
        expires_at: datetime | None,
    ) -> PlayerApiKey:
        """Create or replace a hashed API key for a player."""
        key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()

        existing = await self.get_player_api_key(game_id, player_id)
        if existing:
            existing.key_hash = key_hash
            existing.expires_at = expires_at
            await self.session.flush()
            return existing

        api_key = PlayerApiKey(
            game_id=game_id,
            player_id=player_id,
            key_hash=key_hash,
            expires_at=expires_at,
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def get_player_api_key(
        self, game_id: str, player_id: str
    ) -> PlayerApiKey | None:
        """Read a player API key row by game and player."""
        result = await self.session.execute(
            select(PlayerApiKey).where(
                and_(
                    PlayerApiKey.game_id == game_id,
                    PlayerApiKey.player_id == player_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def validate_player_api_key(
        self, plaintext_key: str, now: datetime | None = None
    ) -> PlayerApiKey | None:
        """Validate a plaintext key by matching its hash and checking expiry."""
        key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
        current_time = now or self._utcnow()

        result = await self.session.execute(
            select(PlayerApiKey).where(PlayerApiKey.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            return None

        if api_key.expires_at and api_key.expires_at <= current_time:
            return None

        return api_key

    async def expire_player_api_keys(
        self,
        game_id: str,
        player_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> int:
        """Expire one player's key or all keys for a game."""
        expiry = expires_at or self._utcnow()
        stmt = update(PlayerApiKey).where(PlayerApiKey.game_id == game_id)

        if player_id is not None:
            stmt = stmt.where(PlayerApiKey.player_id == player_id)

        result = await self.session.execute(stmt.values(expires_at=expiry))
        return result.rowcount or 0

    async def save_enhanced_prompt_log(
        self,
        game_id: str,
        player_id: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        turn_number: int | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        thinking_tokens: str | None = None,
    ) -> PromptLog:
        """Save enhanced LLM prompt log with additional context."""
        db_prompt_log = PromptLog(
            game_id=game_id,
            player_id=player_id,
            prompt=prompt,
            response=response,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            turn_number=turn_number,
            llm_provider=llm_provider,
            llm_model=llm_model,
            thinking_tokens=thinking_tokens,
        )

        self.session.add(db_prompt_log)
        await self.session.flush()
        return db_prompt_log

    async def create_game_snapshot(
        self,
        game_id: str,
        turn_number: int,
        state: GameState,
        snapshot_type: str = "periodic",
    ) -> GameSnapshot:
        """Create a game state snapshot."""
        snapshot = GameSnapshot(
            game_id=game_id,
            turn_number=turn_number,
            complete_state=state.model_dump(mode="json"),
            state_hash=state.hash_state(),
            snapshot_type=snapshot_type,
        )

        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def get_latest_snapshot(self, game_id: str) -> GameSnapshot | None:
        """Get the most recent snapshot for a game."""
        result = await self.session.execute(
            select(GameSnapshot)
            .where(GameSnapshot.game_id == game_id)
            .order_by(desc(GameSnapshot.turn_number))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_turn_history(self, game_id: str) -> list[GameTurn]:
        """Get all turns for a game."""
        result = await self.session.execute(
            select(GameTurn)
            .where(GameTurn.game_id == game_id)
            .order_by(GameTurn.turn_number)
        )
        return list(result.scalars().all())

    async def get_turn_history_paginated(
        self,
        game_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GameTurn]:
        """Get turns for a game with pagination."""
        result = await self.session.execute(
            select(GameTurn)
            .where(GameTurn.game_id == game_id)
            .order_by(GameTurn.turn_number)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_turns(self, game_id: str) -> int:
        """Count total turns for a game."""
        result = await self.session.execute(
            select(func.count(GameTurn.id)).where(GameTurn.game_id == game_id)
        )
        return result.scalar_one()

    async def get_game_turn(self, game_id: str, turn_number: int) -> GameTurn | None:
        """Get a specific turn by game and turn number."""
        result = await self.session.execute(
            select(GameTurn).where(
                and_(
                    GameTurn.game_id == game_id,
                    GameTurn.turn_number == turn_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_game_snapshot_at_turn(
        self, game_id: str, turn_number: int
    ) -> GameSnapshot | None:
        """Get the game snapshot at a specific turn."""
        result = await self.session.execute(
            select(GameSnapshot).where(
                and_(
                    GameSnapshot.game_id == game_id,
                    GameSnapshot.turn_number == turn_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_prompt_logs_for_turn(
        self, game_id: str, turn_number: int
    ) -> list[PromptLog]:
        """Get all prompt logs for a specific turn."""
        result = await self.session.execute(
            select(PromptLog)
            .where(
                and_(
                    PromptLog.game_id == game_id,
                    PromptLog.turn_number == turn_number,
                )
            )
            .order_by(PromptLog.player_id)
        )
        return list(result.scalars().all())

    async def get_player_prompt_logs(
        self, game_id: str, player_id: str, limit: int = 100
    ) -> list[PromptLog]:
        """Get prompt logs for a specific player in a game."""
        result = await self.session.execute(
            select(PromptLog)
            .where(and_(PromptLog.game_id == game_id, PromptLog.player_id == player_id))
            .order_by(desc(PromptLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_player_stats(
        self, player_id: str, game_result: dict[str, Any]
    ) -> None:
        """Update or create player statistics."""
        # This would be implemented to aggregate player performance
        # For now, we'll keep it as a placeholder
        pass

    async def restore_game_from_snapshot(self, game_id: str) -> GameState | None:
        """Restore game state from the latest snapshot."""
        snapshot = await self.get_latest_snapshot(game_id)
        if not snapshot:
            return None

        # Convert snapshot back to GameState
        try:
            return GameState.model_validate(snapshot.complete_state)
        except Exception:
            return None
