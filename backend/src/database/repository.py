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
    AuthVerificationToken,
    Game,
    GameSnapshot,
    GameTurn,
    LobbyInvite,
    PlayerAction,
    PlayerApiKey,
    PromptLog,
    SavedMap,
    TurnAction,
    TurnSnapshot,
    UserIdentity,
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
        creator_user_identity_id: int | None = None,
        status: str = "created",
        map_template: str = "random",
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
            creator_user_identity_id=creator_user_identity_id,
            status=status,
            map_template=map_template,
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

    async def update_lobby_slots(
        self, game_id: str, lobby_slots: list[dict[str, Any]]
    ) -> None:
        """Replace the ``lobby_slots`` JSON column on a game.

        The column is JSON, so the new value must be JSON-serialisable
        (lists of plain dicts only — no Pydantic models). Callers go
        through ``api.lobby_slots`` helpers to keep the shape consistent.
        """
        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(lobby_slots=lobby_slots, updated_at=self._utcnow())
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
        include_archived: bool = False,
    ) -> list[Game]:
        """List games with optional filtering and sorting.

        ``include_archived=False`` (the default) omits rows where
        ``archived_at`` is non-null. Setting it to ``True`` surfaces every
        row regardless of archive state. The Archived-filter UI flips this
        flag AND passes ``status=None`` so archived rows of any prior
        status turn up in a single list.
        """
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

        if not include_archived:
            query = query.where(Game.archived_at.is_(None))

        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_games(
        self, status: str | None = None, include_archived: bool = False
    ) -> int:
        """Count games with optional status filter."""
        query = select(func.count(Game.id))

        if status:
            query = query.where(Game.status == status)

        if not include_archived:
            query = query.where(Game.archived_at.is_(None))

        result = await self.session.execute(query)
        return result.scalar_one()

    async def count_active_agents(self) -> int:
        """Count player seats currently in active, non-archived games.

        Backs the landing-page "agents in the field" stat. ``Game.players``
        is the authoritative roster; summing its length across active games
        counts every seated participant (human or agent) in a live match.
        Active games are few, so loading their rosters is cheap and keeps
        the query portable (no JSON-length functions).
        """
        result = await self.session.execute(
            select(Game.players).where(
                and_(Game.status == "active", Game.archived_at.is_(None))
            )
        )
        return sum(len(players or []) for players in result.scalars().all())

    async def archive_game(self, game_id: str, reason: str) -> None:
        """Soft-archive a game.

        Sets ``archived_at`` to now and stamps ``archived_reason``. Idempotent:
        re-archiving an already-archived row is a no-op — callers that care
        about the distinction should check ``Game.archived_at`` themselves.
        """
        now = self._utcnow()
        await self.session.execute(
            update(Game)
            .where(and_(Game.id == game_id, Game.archived_at.is_(None)))
            .values(archived_at=now, archived_reason=reason, updated_at=now)
        )

    async def unarchive_game(self, game_id: str) -> None:
        """Clear the archive flags on a game, restoring it to the default list."""
        await self.session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(
                archived_at=None,
                archived_reason=None,
                updated_at=self._utcnow(),
            )
        )

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
        self,
        game_id: str,
        winner: str | None = None,
        victory_type: str = "score",
        end_reason: str | None = None,
        resigned_by: str | None = None,
    ) -> None:
        """Mark game as ended.

        ``end_reason`` is the canonical enum read by the frontend
        (``domination`` | ``score`` | ``resignation`` | ``abandoned``). It
        defaults to ``victory_type`` when not supplied so callers that
        predate the column (everything except the resignation path) keep
        working without changes. ``resigned_by`` and ``resigned_at`` are
        only set when the end-reason is a resignation.
        """
        now = self._utcnow()
        values: dict[str, Any] = {
            "status": "ended",
            "winner": winner,
            "victory_type": victory_type,
            "ended_at": now,
            "updated_at": now,
            "end_reason": end_reason if end_reason is not None else victory_type,
        }
        if resigned_by is not None:
            values["resigned_by"] = resigned_by
            values["resigned_at"] = now
        await self.session.execute(
            update(Game).where(Game.id == game_id).values(**values)
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

    async def get_user_identity_by_email(self, email: str) -> UserIdentity | None:
        """Look up a UserIdentity by normalised email, or return None."""
        normalised = email.strip().lower()
        if not normalised:
            return None
        result = await self.session.execute(
            select(UserIdentity).where(UserIdentity.email == normalised)
        )
        return result.scalar_one_or_none()

    async def get_user_identity_by_id(self, identity_id: int) -> UserIdentity | None:
        """Look up a UserIdentity by primary-key id, or return None."""
        result = await self.session.execute(
            select(UserIdentity).where(UserIdentity.id == identity_id)
        )
        return result.scalar_one_or_none()

    async def create_verification_token(
        self, identifier: str, token: str, expires_at: datetime
    ) -> AuthVerificationToken:
        """Store an Auth.js magic-link verification token."""
        normalised = identifier.strip().lower()
        if not normalised:
            raise ValueError("identifier is required")
        row = AuthVerificationToken(
            identifier=normalised,
            token=token,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def consume_verification_token(
        self, identifier: str, token: str
    ) -> AuthVerificationToken | None:
        """Atomically look up and delete the (identifier, token) row.

        Returns the deleted row if it existed, otherwise None. Callers check
        ``expires_at`` themselves so a single round-trip resolves both the
        existence check and the one-time-use contract Auth.js requires.
        """
        normalised = identifier.strip().lower()
        if not normalised:
            return None
        result = await self.session.execute(
            select(AuthVerificationToken).where(
                and_(
                    AuthVerificationToken.identifier == normalised,
                    AuthVerificationToken.token == token,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        await self.session.delete(row)
        await self.session.flush()
        return row

    async def upsert_user_identity_by_email(
        self, email: str, *, admin_emails: list[str] | None = None
    ) -> UserIdentity:
        """Return the UserIdentity for an email, creating it if missing.

        Idempotent: successive calls with the same normalised email return the
        same row. Email is trimmed and lowercased so that ``Foo@Bar`` and
        ``foo@bar`` resolve to a single identity.

        When ``admin_emails`` is provided the row's ``is_admin`` flag is
        re-synced to ``email in admin_emails`` (case-insensitive). Phase 3 of
        the map system overhaul uses this on every Auth.js verify so the DB
        flag mirrors the env-var allowlist — removing an email demotes the
        user on their next sign-in without a redeploy.
        """
        normalised = email.strip().lower()
        if not normalised:
            raise ValueError("email is required")

        admin_set: set[str] | None = None
        if admin_emails is not None:
            admin_set = {a.strip().lower() for a in admin_emails if a and a.strip()}

        result = await self.session.execute(
            select(UserIdentity).where(UserIdentity.email == normalised)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            if admin_set is not None:
                desired = normalised in admin_set
                if existing.is_admin != desired:
                    existing.is_admin = desired
                    await self.session.flush()
            return existing

        identity = UserIdentity(
            email=normalised,
            is_admin=(admin_set is not None and normalised in admin_set),
        )
        self.session.add(identity)
        await self.session.flush()
        return identity

    async def list_saved_maps(self) -> list[SavedMap]:
        """Return every saved map ordered by ``updated_at`` desc.

        Phase 4 (map system overhaul): backs ``GET /api/v1/maps`` and
        the lobby drop-down population. Open to any authenticated user
        — see the route guard in ``rest.py``.
        """
        result = await self.session.execute(
            select(SavedMap).order_by(desc(SavedMap.updated_at))
        )
        return list(result.scalars().all())

    async def get_saved_map(self, saved_map_id: int) -> SavedMap | None:
        """Look up a SavedMap by primary key, or None."""
        result = await self.session.execute(
            select(SavedMap).where(SavedMap.id == saved_map_id)
        )
        return result.scalar_one_or_none()

    async def get_saved_map_by_name(self, name: str) -> SavedMap | None:
        """Look up a SavedMap by its unique ``name`` field, or None."""
        result = await self.session.execute(
            select(SavedMap).where(SavedMap.name == name)
        )
        return result.scalar_one_or_none()

    async def create_saved_map(
        self,
        *,
        name: str,
        description: str | None,
        width: int,
        height: int,
        tiles: list[dict[str, Any]],
        spawn_zones: list[dict[str, int]],
        created_by: int | None,
    ) -> SavedMap:
        """Insert a SavedMap row. Caller has already validated payload."""
        row = SavedMap(
            name=name,
            description=description,
            width=width,
            height=height,
            tiles=tiles,
            spawn_zones=spawn_zones,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_saved_map(
        self,
        saved_map_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        width: int | None = None,
        height: int | None = None,
        tiles: list[dict[str, Any]] | None = None,
        spawn_zones: list[dict[str, int]] | None = None,
    ) -> SavedMap | None:
        """Apply a partial update to a SavedMap row. Returns the row or None."""
        row = await self.get_saved_map(saved_map_id)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if width is not None:
            row.width = width
        if height is not None:
            row.height = height
        if tiles is not None:
            row.tiles = tiles
        if spawn_zones is not None:
            row.spawn_zones = spawn_zones
        await self.session.flush()
        # ``onupdate=func.now()`` populates ``updated_at`` server-side, so
        # SQLAlchemy expires the column after the UPDATE. Refresh
        # eagerly so callers can read the new timestamp without
        # triggering a lazy-load outside their async session scope.
        await self.session.refresh(row)
        return row

    async def delete_saved_map(self, saved_map_id: int) -> bool:
        """Delete a SavedMap row. Returns True iff a row was removed."""
        row = await self.get_saved_map(saved_map_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

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
        user_identity_id: int | None = None,
    ) -> PlayerApiKey:
        """Create or replace a hashed API key for a player.

        When ``user_identity_id`` is provided (human-minted keys from Auth.js),
        it's stored so the key can later be renewed via the JWT-gated
        renewal endpoint. MCP-minted keys leave it ``None``.

        On update of an existing row, ``user_identity_id`` is set only if
        not already populated — we never clear an existing attribution, but
        we do let a subsequent human join retroactively attribute a row
        that was previously keyless.
        """
        key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()

        existing = await self.get_player_api_key(game_id, player_id)
        if existing:
            existing.key_hash = key_hash
            existing.expires_at = expires_at
            if user_identity_id is not None and existing.user_identity_id is None:
                existing.user_identity_id = user_identity_id
            await self.session.flush()
            return existing

        api_key = PlayerApiKey(
            game_id=game_id,
            player_id=player_id,
            key_hash=key_hash,
            expires_at=expires_at,
            user_identity_id=user_identity_id,
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

    async def get_player_api_key_by_user_identity(
        self, game_id: str, user_identity_id: int
    ) -> PlayerApiKey | None:
        """Read the API key row a given UserIdentity owns in a game, if any.

        MCP-minted keys leave user_identity_id null, so this only resolves
        keys minted through the human/Auth.js path.
        """
        result = await self.session.execute(
            select(PlayerApiKey).where(
                and_(
                    PlayerApiKey.game_id == game_id,
                    PlayerApiKey.user_identity_id == user_identity_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def rotate_player_api_key(
        self,
        api_key: PlayerApiKey,
        plaintext_key: str,
        expires_at: datetime | None,
    ) -> PlayerApiKey:
        """Replace the hash and expiry on an existing PlayerApiKey row.

        Used by the renewal endpoint: keeps the same (game_id, player_id,
        user_identity_id) tuple so nothing else needs re-binding, and just
        swaps the plaintext binding and TTL.
        """
        api_key.key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
        api_key.expires_at = expires_at
        await self.session.flush()
        return api_key

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

    async def list_seats_for_games(
        self, game_ids: list[str]
    ) -> dict[str, list[tuple[str, int | None]]]:
        """Return seat rosters grouped by game.

        For each game id, yields the ordered list of ``(player_id,
        user_identity_id)`` pairs that have been minted a player API key.
        Seats whose key is MCP-minted have ``user_identity_id == None``;
        human-minted (Auth.js) keys carry the identity. Used by the games
        list endpoint so the frontend can distinguish Resume vs Observe
        and surface the "Agent vs Agent" badge with one query per page.
        """
        if not game_ids:
            return {}
        result = await self.session.execute(
            select(
                PlayerApiKey.game_id,
                PlayerApiKey.player_id,
                PlayerApiKey.user_identity_id,
            )
            .where(PlayerApiKey.game_id.in_(game_ids))
            .order_by(PlayerApiKey.game_id, PlayerApiKey.id)
        )
        seats: dict[str, list[tuple[str, int | None]]] = {gid: [] for gid in game_ids}
        for game_id, player_id, user_identity_id in result.all():
            seats.setdefault(game_id, []).append((player_id, user_identity_id))
        return seats

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

    async def get_player_api_key_by_id(self, api_key_id: int) -> PlayerApiKey | None:
        """Read a PlayerApiKey row by its primary key.

        Used by the Phase 3 regenerate-key endpoint, which already has
        the slot's ``player_api_key_id`` and wants to confirm the row
        exists (and belongs to the right game) before rotating it.
        """
        result = await self.session.execute(
            select(PlayerApiKey).where(PlayerApiKey.id == api_key_id)
        )
        return result.scalar_one_or_none()

    async def upsert_lobby_invite(
        self,
        game_id: str,
        slot_index: int,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> LobbyInvite:
        """Create or refresh the lobby invite for a slot.

        One live invite per (game, slot) — re-inviting the same address
        rotates the token hash and resets the expiry on the existing row
        so the redemption surface stays single-row. ``redeemed_at`` is
        always cleared on rotate, since the new token is unredeemed by
        definition.
        """
        normalised = email.strip().lower()
        existing = await self.get_lobby_invite(game_id, slot_index)
        if existing is not None:
            existing.email = normalised
            existing.token_hash = token_hash
            existing.expires_at = expires_at
            existing.redeemed_at = None
            await self.session.flush()
            return existing
        invite = LobbyInvite(
            game_id=game_id,
            slot_index=slot_index,
            email=normalised,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_lobby_invite(
        self, game_id: str, slot_index: int
    ) -> LobbyInvite | None:
        """Read the lobby invite for a (game, slot), or return None."""
        result = await self.session.execute(
            select(LobbyInvite).where(
                and_(
                    LobbyInvite.game_id == game_id,
                    LobbyInvite.slot_index == slot_index,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_lobby_invite_by_token_hash(
        self, token_hash: str
    ) -> LobbyInvite | None:
        """Read the lobby invite with a given token hash, or None."""
        result = await self.session.execute(
            select(LobbyInvite).where(LobbyInvite.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_lobby_invites_for_game(self, game_id: str) -> list[LobbyInvite]:
        """Return every invite row for a game."""
        result = await self.session.execute(
            select(LobbyInvite).where(LobbyInvite.game_id == game_id)
        )
        return list(result.scalars().all())

    async def delete_lobby_invite(self, game_id: str, slot_index: int) -> None:
        """Drop the invite row for a (game, slot) — used by ``invite/clear``."""
        existing = await self.get_lobby_invite(game_id, slot_index)
        if existing is None:
            return
        await self.session.delete(existing)
        await self.session.flush()

    async def mark_lobby_invite_redeemed(
        self, invite: LobbyInvite, now: datetime | None = None
    ) -> LobbyInvite:
        """Stamp ``redeemed_at`` on an invite row.

        Single-use is enforced by the caller (which must check
        ``redeemed_at IS NULL`` before invoking this). Returns the same
        row so callers don't have to re-fetch.
        """
        invite.redeemed_at = now or self._utcnow()
        await self.session.flush()
        return invite

    async def rename_player_api_key(
        self, game_id: str, old_player_id: str, new_player_id: str
    ) -> bool:
        """Re-bind a PlayerApiKey row to a new ``player_id`` in the same game.

        Used by Phase 4 slot reconfiguration when an Agent slot is
        renamed but its plaintext key is intentionally preserved — the
        key hash and TTL stay put, so the agent's existing bearer keeps
        working and ``authenticate`` resolves it to the new name. The
        ``(game_id, player_id)`` index also stays valid because we move
        the row rather than duplicate it.
        """
        result = await self.session.execute(
            update(PlayerApiKey)
            .where(
                and_(
                    PlayerApiKey.game_id == game_id,
                    PlayerApiKey.player_id == old_player_id,
                )
            )
            .values(player_id=new_player_id)
        )
        return (result.rowcount or 0) > 0

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
