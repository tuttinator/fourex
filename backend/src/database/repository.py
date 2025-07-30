"""
Database repository for game data operations.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..game.models import Action, GameState, TurnResult
from ..game.models import PromptLog as GamePromptLog
from .models import Game, GameSnapshot, GameTurn, PlayerAction, PromptLog


class GameRepository:
    """Repository for game data persistence operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_game(
        self,
        game_id: str,
        players: list[str],
        seed: int = 42,
        max_turns: int = 100,
        map_width: int = 20,
        map_height: int = 20,
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
            status="created",
        )

        self.session.add(game)
        await self.session.flush()
        return game

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
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Game]:
        """List games with optional filtering."""
        query = select(Game).order_by(desc(Game.created_at))

        if status:
            query = query.where(Game.status == status)

        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

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
                updated_at=datetime.utcnow(),
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
                ended_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
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
            completed_at=datetime.utcnow(),
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
