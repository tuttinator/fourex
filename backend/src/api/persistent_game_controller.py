"""
Persistent game controller using database storage.
"""

import random
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_player_key
from ..database.models import Game as DBGame
from ..database.models import SavedMap
from ..database.repository import GameRepository
from ..game.models import (
    Action,
    Coord,
    GameState,
    PlayerId,
    PromptLog,
    Resource,
    Terrain,
    Tile,
)
from ..game.rules import (
    STARTING_STOCKPILE,
    eliminate_player,
    generate_map,
    place_starting_units,
    seed_research,
    update_discovery,
)
from .lobby_slots import (
    SlotDict,
    clear_slot_by_name,
    coerce_slots,
    derive_slots_from_players,
    fill_slot,
    find_slot_by_index,
    first_empty_slot_index,
    make_agent_slot,
    make_human_slot,
    strip_plaintext_keys,
)
from .turn_resolution import check_and_resolve_turn
from .websocket import (
    broadcast_lobby_player_joined,
    broadcast_lobby_player_left,
    broadcast_lobby_started,
    broadcast_turn_submitted,
)

SAVED_MAP_PREFIX = "saved:"


def _saved_map_id_from_template(template: str) -> int | None:
    """Return the int id encoded in a ``saved:<id>`` template, or ``None``.

    Phase 4 (map system overhaul): the lobby's ``map_template`` field is
    a free string so future namespaces (``scenario:<id>``) stay
    additive. The lobby resolver checks for the ``saved:`` prefix; a
    well-formed integer is required, otherwise the caller treats the
    string as a parametric template name and lets the engine raise.
    """
    if not template.startswith(SAVED_MAP_PREFIX):
        return None
    suffix = template[len(SAVED_MAP_PREFIX) :]
    try:
        return int(suffix)
    except ValueError:
        return None


def _saved_map_to_tiles(saved_map: SavedMap) -> list[Tile]:
    """Materialise a ``SavedMap`` row's tile JSON into engine ``Tile``s.

    Tile ids are reassigned in row-major (y, x) order so the engine's
    ``state.tiles`` list stays index-addressable regardless of the
    order admins painted them in. Unknown coordinates / terrains are
    rejected at create/update time, so this helper trusts the row.
    """
    by_loc: dict[tuple[int, int], dict[str, Any]] = {
        (int(t["x"]), int(t["y"])): t for t in (saved_map.tiles or [])
    }
    tiles: list[Tile] = []
    tile_id = 0
    for y in range(saved_map.height):
        for x in range(saved_map.width):
            row = by_loc.get((x, y))
            if row is None:
                # Saved-map validation guarantees full coverage, but
                # fall back to grass so a partial row never crashes
                # the lobby flow.
                terrain = Terrain.GRASS
                resource: Resource | None = None
            else:
                terrain = Terrain(row["terrain"])
                raw_resource = row.get("resource")
                resource = Resource(raw_resource) if raw_resource else None
            tiles.append(
                Tile(
                    id=tile_id,
                    loc=Coord(x=x, y=y),
                    terrain=terrain,
                    resource=resource,
                )
            )
            tile_id += 1
    return tiles


def _saved_map_spawn_zones(saved_map: SavedMap) -> list[Coord]:
    """Project the saved-map JSON spawn zones into ``Coord`` rows."""
    return [Coord(x=int(z["x"]), y=int(z["y"])) for z in (saved_map.spawn_zones or [])]


def _select_saved_spawn_subset(
    spawn_zones: list[Coord],
    player_count: int,
    seed: int,
) -> list[Coord]:
    """Deterministic seeded subset selection for saved-map lobbies.

    The PRD calls for a deterministic random subset when a saved map
    has more spawn zones than the lobby has players. ``seed`` and
    ``player_count`` together fully determine the subset, so the
    same lobby seed with the same map and player count always picks
    the same opening tiles.
    """
    if player_count > len(spawn_zones):
        raise ValueError(
            f"saved map provides {len(spawn_zones)} spawn zone(s) but the "
            f"lobby needs {player_count}; pick a smaller player count or "
            f"add more spawn zones to the map"
        )
    if player_count == len(spawn_zones):
        return list(spawn_zones)
    # Mix seed + player_count + len(spawn_zones) deterministically.
    # ``random.Random`` accepts tuples but hash()-based seeding is
    # process-randomised unless PYTHONHASHSEED=0; explicit integer
    # mixing keeps the determinism contract independent of the
    # interpreter's hash randomisation setting.
    mixed_seed = (seed * 1_000_003) ^ (player_count * 31) ^ (len(spawn_zones) * 17)
    rng = random.Random(mixed_seed)
    indices = list(range(len(spawn_zones)))
    rng.shuffle(indices)
    chosen = sorted(indices[:player_count])
    return [spawn_zones[i] for i in chosen]


class PersistentGameController:
    """Manages multiple game instances with database persistence."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = GameRepository(session)

        # In-memory cache of authoritative GameState, keyed by game_id.
        # Turn submissions are no longer held in memory — they live in the
        # ``turn_actions`` table and are consulted by
        # ``turn_resolution.check_and_resolve_turn``.
        self._game_cache: dict[str, GameState] = {}

    async def create_lobby(
        self,
        game_id: str,
        player_slots: int,
        map_width: int,
        map_height: int,
        seed: int,
        creator: str | None,
        creator_user_identity_id: int | None = None,
        slot_configs: list[SlotDict] | None = None,
        map_template: str = "random",
    ) -> None:
        """Create a game lobby in waiting status.

        Map is generated but no units are placed. ``slot_configs``
        carries the Phase 3 per-slot type/name array; when omitted the
        lobby seeds an all-Human slate (legacy behaviour). Agent slots
        in ``slot_configs`` are written with their display name but
        their ``player_api_key_id`` / ``plaintext_key`` are populated
        separately by the REST/MCP caller after a key is minted —
        keeping the auth layer as the single key-minting site.

        ``map_template`` (Phase 2 of the map system overhaul) selects a
        parametric generator from ``MAP_TEMPLATES``. Spawn zones are
        not persisted — they are re-derived deterministically from
        ``(map_template, map_width, map_height, seed, player_slots)``
        whenever a player is seated, so we never have to store a
        spawn-zone list and risk it drifting from the tile data.
        """
        if player_slots < 2 or player_slots > 8:
            raise ValueError("Games require 2-8 player slots")

        existing_game = await self.repo.get_game(game_id)
        if existing_game:
            raise ValueError(f"Game {game_id} already exists")

        saved_map_id = _saved_map_id_from_template(map_template)
        if saved_map_id is not None:
            # Phase 4 (map system overhaul): saved-map lobbies pull
            # tiles + spawn zones from the row and override the
            # caller's dimensions with whatever the saved map was
            # authored at. The lobby-creation request's ``map_width``
            # / ``map_height`` are intentionally ignored (the UI
            # disables the inputs once a saved map is selected — see
            # the create-game dialog).
            saved_map = await self.repo.get_saved_map(saved_map_id)
            if saved_map is None:
                raise ValueError(f"Saved map {saved_map_id} not found")
            tiles = _saved_map_to_tiles(saved_map)
            zones = _saved_map_spawn_zones(saved_map)
            # Validate up-front so create-lobby fails fast if the map
            # can't seat the requested player count, rather than
            # surfacing the error at start time.
            _select_saved_spawn_subset(zones, player_slots, seed)
            map_width = saved_map.width
            map_height = saved_map.height
        else:
            # Generate map at creation time
            tiles, _spawn_zones = generate_map(
                map_template, map_width, map_height, seed, player_count=player_slots
            )

        # Create game state with no players yet (they join via /join)
        state = GameState(
            rng_state=seed,
            tiles=tiles,
            players=[],
            map_width=map_width,
            map_height=map_height,
            max_turns=100,
        )

        # Save to database with waiting status
        await self.repo.create_game(
            game_id=game_id,
            players=[],
            seed=seed,
            map_width=map_width,
            map_height=map_height,
            max_turns=100,
            player_slots=player_slots,
            creator=creator,
            creator_user_identity_id=creator_user_identity_id,
            status="waiting",
            map_template=map_template,
        )

        # Seed lobby_slots: when the caller provides a per-slot config
        # array (Phase 3 create dialog) we honour it; otherwise we fall
        # back to all-Human (Phase 2 / legacy behaviour).
        if slot_configs is None:
            initial_slots = derive_slots_from_players([], player_slots)
        else:
            initial_slots = list(slot_configs)
        await self.repo.update_lobby_slots(game_id, initial_slots)

        # Update game state in database
        await self.repo.update_game_state(game_id, state)

        # Cache the game state
        self._game_cache[game_id] = state

    async def seat_agent(
        self,
        game_id: str,
        slot_index: int,
        player_id: str,
    ) -> None:
        """Append an Agent player to ``Game.players`` for a pre-created Agent slot.

        Phase 3 creates Agent slots up front in ``create_lobby`` (with a
        name but no key); this helper mirrors that name into the
        ``players`` roster so the engine, fog-of-war, and ``whoami``
        slot-index lookup all see the agent as a real seat. The slot's
        ``player_api_key_id`` is patched separately via
        ``link_slot_api_key`` once the REST/MCP caller has minted the
        key.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")
        if db_game.status != "waiting":
            raise ValueError(f"Game {game_id} is not in waiting status")

        players = list(db_game.players)
        if player_id in players:
            raise ValueError(f"Player {player_id} is already in the game")
        if len(players) >= db_game.player_slots:
            raise ValueError(f"Game {game_id} is full")

        players.append(player_id)
        await self.repo.update_game_players(game_id, players)

        # Update the cached state's players list so subsequent reads stay
        # consistent — start_game will overwrite this from the canonical
        # roster anyway.
        if game_id in self._game_cache:
            self._game_cache[game_id].players = players

        await broadcast_lobby_player_joined(game_id, player_id, players)

    async def store_slot_plaintext(
        self,
        game_id: str,
        slot_index: int,
        plaintext_key: str | None,
    ) -> None:
        """Set or clear the transient ``plaintext_key`` on an Agent slot.

        Stored on the slot (rather than on ``PlayerApiKey``) because the
        plaintext is intentionally short-lived: ``start_game`` strips
        every slot's ``plaintext_key`` when the game flips to ``active``,
        so the lobby endpoint can't double as a long-lived secret store.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            return
        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        updated: list[SlotDict] = []
        for slot in slots:
            if slot.get("slot_index") == slot_index:
                updated.append({**slot, "plaintext_key": plaintext_key})
            else:
                updated.append(dict(slot))
        await self.repo.update_lobby_slots(game_id, updated)

    async def regenerate_agent_key(
        self,
        game_id: str,
        slot_index: int,
    ) -> str:
        """Mint a fresh API key for an Agent slot, invalidating the previous.

        Returns the plaintext so the REST handler can echo it back to the
        creator. Restricted by the caller's auth layer — this method
        trusts that the creator check has already been done.

        The previous key is rotated in place (same ``PlayerApiKey`` row,
        new hash + new TTL) so the slot's ``player_api_key_id`` doesn't
        need updating. The new plaintext is stashed on the slot's
        transient ``plaintext_key`` so the GET endpoint surfaces it
        until the game starts.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")
        if db_game.status != "waiting":
            raise ValueError("Slot keys can only be regenerated while waiting")

        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        slot = next((s for s in slots if s.get("slot_index") == slot_index), None)
        if slot is None:
            raise ValueError(f"Slot {slot_index} not found")
        if slot.get("type") != "agent":
            raise ValueError("Only Agent slots have a regenerable API key")
        name = slot.get("name")
        if not name:
            raise ValueError(f"Slot {slot_index} has no agent name")

        # ``create_player_key`` is upsert-on-(game, player) — it replaces
        # the existing row's hash + expiry, which is exactly what
        # "regenerate" means here.
        plaintext = await create_player_key(
            self.repo.session, game_id, name, user_identity_id=None
        )
        await self.link_slot_api_key(game_id, name)
        await self.store_slot_plaintext(game_id, slot_index, plaintext)
        return plaintext

    async def reconfigure_slots(
        self,
        game_id: str,
        new_configs: list[SlotDict],
    ) -> None:
        """Apply a slot-reconfiguration diff while the game is ``waiting``.

        Phase 4: the creator can flip slot types and rename Agent slots
        in the lobby. The legal transitions are:

        * Human (empty) → Agent: mint a fresh key, append the agent
          name to ``Game.players``, write the slot record.
        * Agent → Human: invalidate the agent's key (so its bearer
          stops working), drop the agent name from ``Game.players``,
          clear the slot's name + ``player_api_key_id``.
        * Agent rename (Agent → Agent with a different name): re-bind
          the existing ``PlayerApiKey`` row to the new name (the
          plaintext key is preserved — only the in-game identity
          changes). Rotate ``Game.players`` to match.
        * Human (occupied) → Agent: rejected with 400; the seated
          human must leave first.
        * Human (empty / occupied) → Human: no-op for the player /
          key, ``reserved_email`` is updated for forward-compat with
          Phase 5 invites.

        The whole reconfiguration is built up as a fresh slot array
        before any commit so a validation failure mid-loop doesn't
        leave the lobby half-mutated. Cross-slot uniqueness (Agent
        names, Agent vs seated-Human collision) is checked up front.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")
        if db_game.status != "waiting":
            raise ValueError("Slots can only be reconfigured while waiting")

        if len(new_configs) != db_game.player_slots:
            raise ValueError(
                f"slots length ({len(new_configs)}) must equal "
                f"player_slots ({db_game.player_slots})"
            )

        current_slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        current_by_idx = {s["slot_index"]: s for s in current_slots}
        new_indices: list[int] = []
        for s in new_configs:
            idx = s.get("slot_index")
            if not isinstance(idx, int):
                raise ValueError("each slot must carry an integer slot_index")
            new_indices.append(idx)
        if sorted(new_indices) != sorted(current_by_idx.keys()):
            raise ValueError("slot indices must match the existing slots exactly")

        # Up-front cross-slot validation.
        agent_names: list[str] = []
        seated_human_names: list[str] = []
        for new_slot in new_configs:
            idx = new_slot["slot_index"]
            old = current_by_idx[idx]
            if new_slot["type"] == "agent":
                name = (new_slot.get("name") or "").strip()
                if not name:
                    raise ValueError(f"Agent slot {idx} requires a name")
                if name in agent_names:
                    raise ValueError(f"Agent name '{name}' is duplicated across slots")
                agent_names.append(name)
            elif old.get("type") == "human" and old.get("name"):
                seated_human_names.append(old["name"])
        collision = sorted(set(agent_names) & set(seated_human_names))
        if collision:
            raise ValueError(
                f"Agent name(s) {collision} collide with seated human player names"
            )

        # Reject blocked transitions before mutating anything.
        for new_slot in new_configs:
            idx = new_slot["slot_index"]
            old = current_by_idx[idx]
            if (
                old.get("type") == "human"
                and new_slot["type"] == "agent"
                and old.get("name")
            ):
                raise ValueError(
                    f"Slot {idx} is occupied by '{old['name']}' — "
                    f"that player must leave before flipping the slot to Agent"
                )

        # Apply the diff. Players list is rebuilt as we go so the
        # broadcast at the end reflects the final state.
        players = list(db_game.players)
        output_slots: list[SlotDict] = []
        for new_slot in new_configs:
            idx = new_slot["slot_index"]
            old = current_by_idx[idx]
            old_type = old.get("type")
            new_type = new_slot["type"]
            new_email = new_slot.get("reserved_email")

            if old_type == "human" and new_type == "human":
                output_slots.append({**old, "reserved_email": new_email})

            elif old_type == "human" and new_type == "agent":
                new_name = (new_slot.get("name") or "").strip()
                players.append(new_name)
                plaintext = await create_player_key(
                    self.repo.session, game_id, new_name, user_identity_id=None
                )
                api_key_row = await self.repo.get_player_api_key(game_id, new_name)
                output_slots.append(
                    make_agent_slot(
                        idx,
                        name=new_name,
                        player_api_key_id=api_key_row.id if api_key_row else None,
                        plaintext_key=plaintext,
                    )
                )

            elif old_type == "agent" and new_type == "human":
                old_name = old.get("name")
                if old_name:
                    await self.repo.expire_player_api_keys(game_id, player_id=old_name)
                    players = [p for p in players if p != old_name]
                output_slots.append(make_human_slot(idx, reserved_email=new_email))

            else:  # agent → agent
                old_name = old.get("name")
                new_name = (new_slot.get("name") or "").strip()
                if old_name == new_name:
                    output_slots.append(dict(old))
                else:
                    if old_name:
                        await self.repo.rename_player_api_key(
                            game_id, old_name, new_name
                        )
                        players = [new_name if p == old_name else p for p in players]
                    output_slots.append({**old, "name": new_name})

        await self.repo.update_game_players(game_id, players)
        await self.repo.update_lobby_slots(game_id, output_slots)

        if game_id in self._game_cache:
            self._game_cache[game_id].players = players

    async def join_game(
        self,
        game_id: str,
        player_id: str,
        *,
        slot_index: int | None = None,
    ) -> None:
        """A player joins a joinable game.

        Accepts both ``waiting`` lobbies (created via the frontend's
        ``create_lobby`` path) and ``created`` games (the legacy MCP
        ``create_game`` path, where starting units were placed for every
        initial player at creation time). Phase 4.5 unifies the two front
        doors: the MCP ``join_game`` tool now delegates here so roster
        mutation, starting-unit placement for ``created`` games, and the
        ``lobby.player_joined`` broadcast all share one implementation.

        ``waiting`` games: only the roster changes — unit placement is
        deferred to ``start_game`` so the creator can finalise the slate
        before play begins.

        ``created`` games: legacy MCP semantics — the new player gets
        stockpiles and a worker+scout pair seeded immediately, since the
        game has no separate "start" transition.
        """
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status not in ("waiting", "created"):
            raise ValueError(
                f"Game {game_id} is '{db_game.status}' — only 'waiting' or "
                f"'created' games can be joined"
            )

        players = list(db_game.players)
        if player_id in players:
            raise ValueError(f"Player {player_id} is already in the game")

        # Legacy MCP-created games don't set a meaningful ``player_slots``
        # (the repo default is 2) and instead cap at the engine-wide
        # 8-player maximum. Waiting lobbies enforce the creator's chosen
        # slate size.
        max_slots = db_game.player_slots if db_game.status == "waiting" else 8
        if len(players) >= max_slots:
            raise ValueError(f"Game {game_id} is full ({max_slots} slots)")

        # Phase 5: when ``slot_index`` is supplied (the invite-redemption
        # path) we seat the caller into that specific slot rather than
        # falling into the next open one. The slot must be a Human slot
        # with no current occupant; reserved-email slots are explicitly
        # allowed here because that's the whole point of redemption.
        if slot_index is not None:
            current_slots = coerce_slots(
                db_game.lobby_slots, list(db_game.players), db_game.player_slots
            )
            target = find_slot_by_index(current_slots, slot_index)
            if target is None:
                raise ValueError(f"Slot {slot_index} not found in game {game_id}")
            if target.get("type") != "human":
                raise ValueError(f"Slot {slot_index} is not a Human slot")
            if target.get("name"):
                raise ValueError(f"Slot {slot_index} is already occupied")
        elif db_game.status == "waiting":
            # Open-join path: reject when every Human slot is either
            # filled or reserved for an invitee. Without this guard the
            # slot array would stay unchanged but ``Game.players`` would
            # gain a name that has no seat — a silent inconsistency.
            # Skipped when ``player_id`` already names a slot (the
            # create-lobby flow pre-seats the creator into slot 0 then
            # invokes join_game to wire up the API key — the slot is
            # already reserved by name, so no open seat is needed).
            current_slots = coerce_slots(
                db_game.lobby_slots, list(db_game.players), db_game.player_slots
            )
            already_seated_by_name = any(
                s.get("name") == player_id for s in current_slots
            )
            if (
                not already_seated_by_name
                and first_empty_slot_index(current_slots) is None
            ):
                raise ValueError(
                    f"Game {game_id} has no open Human slots — every "
                    f"unfilled slot is reserved for an invited human"
                )

        players.append(player_id)
        await self.repo.update_game_players(game_id, players)

        # Mirror the roster change into ``lobby_slots`` so downstream
        # readers stay consistent. ``player_api_key_id`` is wired up
        # separately by ``link_slot_api_key`` once the REST/MCP caller
        # has minted the key — this method runs before that.
        if slot_index is not None:
            await self._fill_specific_slot(db_game, player_id, slot_index)
        else:
            await self._fill_next_open_slot(db_game, player_id, players)

        if db_game.status == "created":
            state = await self.get_game_state(game_id)
            if state is None:
                raise ValueError(f"Game state for {game_id} not found")

            state.players = list(players)
            state.stockpiles[player_id] = STARTING_STOCKPILE.model_copy()
            seed_research(state, [player_id])

            # Avoid colliding with pre-placed unit ids from the original
            # create_game roster.
            if state.units:
                state.next_unit_id = max(
                    state.next_unit_id, max(state.units.keys()) + 1
                )

            rng = random.Random(db_game.seed + len(players))
            # Re-derive spawn zones for the per-player join path so each
            # joiner lands on their own template-chosen tile rather than
            # rolling random placement. Position in the zone list maps
            # to the joiner's slot index (the player just appended at
            # ``len(players) - 1``).
            spawn_zones = await self._resolve_spawn_zones(
                db_game.map_template,
                db_game.map_width,
                db_game.map_height,
                db_game.seed,
                db_game.player_slots,
            )
            zone_idx = len(players) - 1
            zone = spawn_zones[zone_idx] if 0 <= zone_idx < len(spawn_zones) else None
            place_starting_units(state, player_id, rng, spawn_zone=zone)
            update_discovery(state)

            await self.repo.update_game_state(game_id, state)
            self._game_cache[game_id] = state
        else:
            # Update cached state for waiting lobbies (no state mutation
            # beyond the roster).
            if game_id in self._game_cache:
                self._game_cache[game_id].players = players

        await broadcast_lobby_player_joined(game_id, player_id, players)

    async def leave_game(self, game_id: str, player_id: str) -> None:
        """A player leaves a waiting game."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status != "waiting":
            raise ValueError(f"Game {game_id} is not in waiting status")

        players = list(db_game.players)
        if player_id not in players:
            raise ValueError(f"Player {player_id} is not in the game")

        players.remove(player_id)
        await self.repo.update_game_players(game_id, players)

        # Mirror the roster change into ``lobby_slots`` — clear name +
        # api_key_id but preserve the slot index/type so the seat can
        # be re-filled later in the same lobby.
        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        cleared = clear_slot_by_name(slots, player_id)
        await self.repo.update_lobby_slots(game_id, cleared)

        # Update cached state if present
        if game_id in self._game_cache:
            self._game_cache[game_id].players = players

        await broadcast_lobby_player_left(game_id, player_id, players)

    async def start_game(
        self,
        game_id: str,
        creator: str | None = None,
        creator_user_identity_id: int | None = None,
    ) -> None:
        """Creator starts a waiting game.

        Authorises by either ``creator`` (per-game player_id from the
        seated creator's API key — legacy path) or
        ``creator_user_identity_id`` (Auth.js JWT — Phase 3 all-Agent
        games where the creator isn't seated). Validates that every
        slot is filled, places units, transitions to ``active``, and
        strips the transient ``plaintext_key`` from each slot so the
        lobby UI stops showing keys.
        """
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status != "waiting":
            raise ValueError(f"Game {game_id} is not in waiting status")

        is_creator = False
        if creator is not None and db_game.creator == creator:
            is_creator = True
        elif (
            creator_user_identity_id is not None
            and db_game.creator_user_identity_id is not None
            and db_game.creator_user_identity_id == creator_user_identity_id
        ):
            is_creator = True
        if not is_creator:
            raise ValueError("Only the game creator can start the game")

        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        unfilled = [
            s["slot_index"]
            for s in slots
            if not s.get("name")
            or (s.get("type") == "agent" and not s.get("player_api_key_id"))
        ]
        if unfilled:
            raise ValueError(
                f"All slots must be filled before starting (slots without "
                f"a player or agent key: {unfilled})"
            )

        players = [s["name"] for s in slots if s.get("name")]

        # Load the game state (map was generated at lobby creation)
        state = await self.get_game_state(game_id)
        if not state:
            raise ValueError(f"Game state for {game_id} not found")

        # Lobbies are created with an empty roster in the state snapshot;
        # the authoritative roster lives on the DB row and is only synced
        # into state.players here, at start.
        state.players = list(players)

        # Initialize player stockpiles
        for player in players:
            state.stockpiles[player] = STARTING_STOCKPILE.model_copy()
        seed_research(state, players)

        # Place starting units. Spawn zones are re-derived from the
        # template + dimensions + seed + slot count so the placement
        # matches what the per-template generator picked at create_lobby
        # time. Tiles are already in ``state``; we only need the zone
        # list, so the recomputed tiles are discarded.
        spawn_zones = await self._resolve_spawn_zones(
            db_game.map_template,
            db_game.map_width,
            db_game.map_height,
            db_game.seed,
            db_game.player_slots,
        )
        self._place_starting_units(state, players, db_game.seed, spawn_zones)

        # Seed discovered-players sets from starting visibility.
        update_discovery(state)

        # Transition to active. The DB roster also needs to be synced so
        # ``state.players`` and ``Game.players`` agree once Agent slots
        # are part of the equation.
        await self.repo.update_game_players(game_id, players)
        await self.repo.update_game_status(game_id, "active")
        await self.repo.update_game_state(game_id, state)

        # Strip plaintext keys from the slot array — the lobby endpoint
        # must stop returning them the instant the game flips to active.
        await self.repo.update_lobby_slots(game_id, strip_plaintext_keys(slots))

        # Cache
        self._game_cache[game_id] = state

        # Create initial snapshot
        await self.repo.create_game_snapshot(
            game_id=game_id, turn_number=0, state=state, snapshot_type="initial"
        )

        # Notify every subscribed client that the lobby has gone live.
        await broadcast_lobby_started(game_id)

    async def _fill_next_open_slot(
        self,
        db_game: DBGame,
        player_id: PlayerId,
        players_after_join: list[str],
    ) -> None:
        """Seat ``player_id`` in the next open Human slot of ``lobby_slots``.

        Phase 2 maintains the slot array in lock-step with ``players``
        without altering join semantics — every slot is Human, so the
        next-open helper is sufficient. ``player_api_key_id`` is left
        null here; the REST/MCP caller invokes
        ``link_slot_api_key(...)`` once the key row exists. Tolerates
        legacy rows by deriving slots from the pre-join roster, which
        excludes the new player so the next-open lookup still finds an
        empty slot.

        Phase 3: when the slot was already pre-named (e.g. the create
        dialog put the creator into a specific Human slot at create
        time), this helper is a no-op — re-filling would double-seat
        the player into a second slot. The check matches by name so
        re-joins after a leave still find the slot.
        """
        pre_join_players = [p for p in players_after_join if p != player_id]
        slots = coerce_slots(
            db_game.lobby_slots, pre_join_players, db_game.player_slots
        )
        if any(s.get("name") == player_id for s in slots):
            return
        idx = first_empty_slot_index(slots)
        if idx is None:
            return
        updated = fill_slot(slots, idx, name=player_id, player_api_key_id=None)
        await self.repo.update_lobby_slots(db_game.id, updated)

    async def _fill_specific_slot(
        self,
        db_game: DBGame,
        player_id: PlayerId,
        slot_index: int,
    ) -> None:
        """Seat ``player_id`` in a specific slot (Phase 5 invite redemption).

        Mirrors ``_fill_next_open_slot`` but lets the caller name the
        slot — needed so an invitee lands in the slot reserved for
        their email rather than the first open one in index order. The
        slot's ``reserved_email`` is preserved so the lobby UI can keep
        showing "claimed by alice@..." after redemption (the
        invite row is what actually changes state — see
        ``mark_lobby_invite_redeemed``).
        """
        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        updated = fill_slot(slots, slot_index, name=player_id, player_api_key_id=None)
        await self.repo.update_lobby_slots(db_game.id, updated)

    async def link_slot_api_key(self, game_id: str, player_id: PlayerId) -> None:
        """Patch ``player_api_key_id`` onto the slot owned by ``player_id``.

        Called by the REST/MCP layer after a key has been minted so
        the slot record knows which ``PlayerApiKey`` row backs it.
        Idempotent — a missing slot or missing key row is a silent
        no-op rather than an error, which keeps the call site simple
        even when invoked against a freshly-derived legacy row that
        lacks a slot entry yet.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            return
        api_key_row = await self.repo.get_player_api_key(game_id, player_id)
        if api_key_row is None:
            return
        slots = coerce_slots(
            db_game.lobby_slots, list(db_game.players), db_game.player_slots
        )
        updated: list[dict[str, Any]] = []
        for slot in slots:
            if slot.get("name") == player_id:
                updated.append({**slot, "player_api_key_id": api_key_row.id})
            else:
                updated.append(dict(slot))
        await self.repo.update_lobby_slots(game_id, updated)

    async def _resolve_spawn_zones(
        self,
        map_template: str,
        map_width: int,
        map_height: int,
        seed: int,
        player_count: int,
    ) -> list[Coord]:
        """Return the deterministic spawn zones for a lobby's template.

        Phase 4 (map system overhaul): saved-map lobbies look the row
        up and pick a deterministic subset of the saved spawn zones
        when there are more zones than players. Parametric templates
        delegate to ``generate_map`` so the legacy registry behaviour
        is unchanged.
        """
        saved_map_id = _saved_map_id_from_template(map_template)
        if saved_map_id is not None:
            saved_map = await self.repo.get_saved_map(saved_map_id)
            if saved_map is None:
                raise ValueError(f"Saved map {saved_map_id} no longer exists")
            zones = _saved_map_spawn_zones(saved_map)
            return _select_saved_spawn_subset(zones, player_count, seed)
        _tiles, zones = generate_map(
            map_template,
            map_width,
            map_height,
            seed,
            player_count=player_count,
        )
        return zones

    @staticmethod
    def _place_starting_units(
        state: GameState,
        players: list[PlayerId],
        seed: int,
        spawn_zones: list[Any] | None = None,
    ) -> None:
        """Place a starting worker + scout per player on suitable terrain.

        ``spawn_zones`` (Phase 2 of the map system overhaul) is a list of
        per-template spawn coords from ``generate_map``. When provided,
        each player is seated on their indexed zone; falls back to the
        legacy random-roll placement when omitted.
        """
        rng = random.Random(seed)
        for idx, player in enumerate(players):
            zone = (
                spawn_zones[idx]
                if spawn_zones is not None and idx < len(spawn_zones)
                else None
            )
            place_starting_units(state, player, rng, spawn_zone=zone)

    async def create_game(
        self,
        game_id: str,
        players: list[PlayerId],
        seed: int = 42,
        map_template: str = "random",
    ) -> None:
        """Create a new game instance with database persistence (legacy: immediate start)."""
        if len(players) < 2 or len(players) > 8:
            raise ValueError("Games require 2-8 players")

        # Check if game already exists
        existing_game = await self.repo.get_game(game_id)
        if existing_game:
            raise ValueError(f"Game {game_id} already exists")

        saved_map_id = _saved_map_id_from_template(map_template)
        if saved_map_id is not None:
            saved_map = await self.repo.get_saved_map(saved_map_id)
            if saved_map is None:
                raise ValueError(f"Saved map {saved_map_id} not found")
            tiles = _saved_map_to_tiles(saved_map)
            zones = _saved_map_spawn_zones(saved_map)
            spawn_zones = _select_saved_spawn_subset(zones, len(players), seed)
            map_width = saved_map.width
            map_height = saved_map.height
        else:
            map_width = 20
            map_height = 20
            tiles, spawn_zones = generate_map(
                map_template, map_width, map_height, seed, player_count=len(players)
            )

        # Create initial game state
        state = GameState(
            rng_state=seed,
            tiles=tiles,
            players=players.copy(),
            map_width=map_width,
            map_height=map_height,
        )

        # Initialize player stockpiles
        for player in players:
            state.stockpiles[player] = STARTING_STOCKPILE.model_copy()
        seed_research(state, players)

        # Place starting units
        self._place_starting_units(state, players, seed, spawn_zones)

        # Seed discovered-players sets from starting visibility.
        update_discovery(state)

        # Save to database
        await self.repo.create_game(
            game_id=game_id,
            players=players,
            seed=seed,
            map_width=map_width,
            map_height=map_height,
            max_turns=100,
            player_slots=len(players),
            map_template=map_template,
        )

        # Phase 2: keep ``lobby_slots`` in lock-step with ``players`` for
        # the legacy create-and-go path. Keys are minted lazily in this
        # branch (or not at all in tests), so each slot's
        # ``player_api_key_id`` stays null until the API surface fills it.
        initial_slots = derive_slots_from_players(players, len(players))
        await self.repo.update_lobby_slots(game_id, initial_slots)

        # Update game state in database
        await self.repo.update_game_state(game_id, state)

        # Cache the game state
        self._game_cache[game_id] = state

        # Create initial snapshot
        await self.repo.create_game_snapshot(
            game_id=game_id, turn_number=0, state=state, snapshot_type="initial"
        )

    async def get_game_state(self, game_id: str) -> GameState | None:
        """Get the current state of a game.

        Always loads from the DB. The controller used to hold an in-memory
        ``_game_cache`` but the MCP submit path writes to the DB with a
        separate session, so the REST controller's cache could go stale
        across turn advances — submissions would then upsert against a
        stale ``state.turn`` and silently overwrite the wrong row. The
        cache is kept as a write-through mirror only; reads bypass it.
        """
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            return None

        try:
            state = GameState.model_validate(db_game.state)
            self._game_cache[game_id] = state
            return state
        except Exception as e:
            print(f"Error loading game state for {game_id}: {e}")
            return None

    async def load_game_from_database(self, game_id: str) -> GameState | None:
        """Explicitly load game from database, bypassing cache."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            return None

        try:
            state = GameState.model_validate(db_game.state)
            self._game_cache[game_id] = state
            return state
        except Exception as e:
            print(f"Error loading game state for {game_id}: {e}")
            return None

    async def resign_player(self, game_id: str, player_id: PlayerId) -> dict[str, Any]:
        """Apply a resignation immediately.

        Removes the resigner's cities, units, and tile ownership (shared
        ``eliminate_player`` path) and persists the updated state. In a
        2-player game the remaining seat is declared winner and the game
        is ended with ``end_reason='resignation'``. In a 3+ player game
        play continues — victory resolves when only one player has
        cities, matching the existing domination condition.

        Returns a summary dict for callers that want to echo the outcome
        back to the user. Raises ``ValueError`` for unseated callers or
        already-ended games; the caller (REST / MCP) translates this into
        the appropriate HTTP / error payload.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")
        if db_game.status == "ended":
            raise ValueError("Game has already ended")

        state = GameState.model_validate(db_game.state)
        if player_id not in state.players:
            raise ValueError(f"Player {player_id} not in game {game_id}")
        if player_id in state.eliminated_players:
            raise ValueError(f"Player {player_id} has already been eliminated")

        eliminate_player(state, player_id)
        await self.repo.update_game_state(game_id, state)

        active_players = [p for p in state.players if p not in state.eliminated_players]
        game_ended = False
        winner: PlayerId | None = None
        # 2-seat games end immediately with the other seat as winner. 3+
        # seat games continue — eliminate_player has already razed the
        # resigner's assets so the remaining players fight it out.
        if len(state.players) == 2 and len(active_players) == 1:
            winner = active_players[0]
            await self.repo.end_game(
                game_id,
                winner=winner,
                victory_type="resignation",
                end_reason="resignation",
                resigned_by=player_id,
            )
            game_ended = True
        elif db_game.status == "created":
            # 3+ player game still going — promote a pre-play ``created``
            # row to ``active`` so the games-list and spectator UI know
            # the match is live. Matches the transition the MCP
            # ``submit_actions`` tool performs on the first regular
            # submission.
            from datetime import UTC, datetime

            from sqlalchemy import update as sa_update

            from ..database.models import Game as GameModel

            now = datetime.now(UTC).replace(tzinfo=None)
            await self.repo.session.execute(
                sa_update(GameModel)
                .where(GameModel.id == game_id)
                .values(status="active", turn_started_at=now)
            )

        # Keep the cache in sync so subsequent reads don't serve stale
        # entities belonging to the eliminated player.
        self._game_cache[game_id] = state

        return {
            "game_id": game_id,
            "resigned_by": player_id,
            "game_ended": game_ended,
            "winner": winner,
            "remaining_players": active_players,
        }

    async def submit_player_actions(
        self, game_id: str, player_id: PlayerId, actions: list[Action]
    ) -> None:
        """Submit actions for a player in the current turn.

        Writes to the ``turn_actions`` table (upsert — resubmitting
        overwrites) and then delegates to
        ``turn_resolution.check_and_resolve_turn``, which is the single
        source of truth shared with the MCP ``submit_actions`` tool.

        Resignation is special-cased: if a ``ResignAction`` is present
        anywhere in the submission it is applied immediately via
        ``resign_player`` and the rest of the submission is discarded.
        Resignation doesn't wait on other seats or on a turn resolution;
        the game either ends (2-player) or the resigner's assets are
        razed and play continues.

        Detection is by ``type`` string rather than ``isinstance`` —
        FastAPI's Pydantic smart-union coercion can classify a bare
        ``{"type": "RESIGN"}`` payload as a sibling type that has only
        an optional discriminator field, so the instance class alone is
        unreliable.
        """
        if any(getattr(a, "type", None) == "RESIGN" for a in actions):
            await self.resign_player(game_id, player_id)
            refreshed = await self.load_game_from_database(game_id)
            if refreshed is not None:
                self._game_cache[game_id] = refreshed
            return

        state = await self.get_game_state(game_id)
        if not state:
            raise ValueError(f"Game {game_id} not found")

        if player_id not in state.players:
            raise ValueError(f"Player {player_id} not in game {game_id}")

        actions_json = [a.model_dump(mode="json") for a in actions]
        await self.repo.upsert_turn_action(
            game_id=game_id,
            player_id=player_id,
            turn_number=state.turn,
            actions_json=actions_json,
        )

        # Phase 6: fan out turn.submitted so other players' UIs can flip
        # this seat from "deciding" to "submitted". Emitted before the
        # resolve check so subscribers always see the submission frame
        # whether or not this was the last seat (turn.resolved follows).
        submitted = await self.repo.get_all_turn_actions(game_id, state.turn)
        await broadcast_turn_submitted(
            game_id=game_id,
            player_id=player_id,
            turn=state.turn,
            submitted_players=[ta.player_id for ta in submitted],
        )

        await check_and_resolve_turn(self.repo, game_id)

        # Refresh the cache — the turn may have advanced.
        refreshed = await self.load_game_from_database(game_id)
        if refreshed is not None:
            self._game_cache[game_id] = refreshed

    async def log_prompt(self, game_id: str, prompt_log: PromptLog) -> None:
        """Log an LLM prompt and response for research."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        await self.repo.save_prompt_log(game_id, prompt_log)

    async def log_enhanced_prompt(
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
    ) -> None:
        """Log enhanced LLM prompt with additional context."""
        await self.repo.save_enhanced_prompt_log(
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

    async def list_games(self, status: str | None = None) -> list[str]:
        """List all active game IDs."""
        games = await self.repo.list_games(status=status)
        return [game.id for game in games]

    async def get_stats(self) -> dict[str, int]:
        """Aggregate counts for the public landing-page stats panel.

        ``games_played`` counts finished games (``status='ended'``);
        ``agents_in_field`` counts player seats currently in active games.
        Archived games are excluded from both, matching the games-list
        default.
        """
        games_played = await self.repo.count_games(status="ended")
        active_games = await self.repo.count_games(status="active")
        total_games = await self.repo.count_games()
        agents_in_field = await self.repo.count_active_agents()
        return {
            "games_played": games_played,
            "agents_in_field": agents_in_field,
            "active_games": active_games,
            "total_games": total_games,
        }

    async def list_games_with_metadata(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_archived: bool = False,
    ) -> tuple[list[DBGame], int, dict[str, list[tuple[str, int | None]]]]:
        """List games with full metadata, total count, and seat rosters.

        The third tuple element maps ``game_id`` to an ordered list of
        ``(player_id, user_identity_id)`` pairs; callers use it to tell
        Resume vs Observe apart (is the signed-in user seated?) and to
        detect agent-only games for the "Agent vs Agent" badge.
        """
        games = await self.repo.list_games(
            status=status,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            include_archived=include_archived,
        )
        total = await self.repo.count_games(
            status=status, include_archived=include_archived
        )
        seats = await self.repo.list_seats_for_games([g.id for g in games])
        return games, total, seats

    async def archive_game(
        self,
        game_id: str,
        user_identity_id: int,
        reason: str = "manual",
    ) -> DBGame:
        """Soft-archive a game on behalf of the signed-in caller.

        Creator-only: the caller's seat (resolved via their UserIdentity
        on a PlayerApiKey in this game) must equal ``Game.creator``. This
        matches the PRD's "creator-only" rule without introducing a
        separate admin role.

        Raises ``PermissionError`` when the caller is not the creator and
        ``ValueError`` when the game does not exist. REST translates these
        into 403 / 404 respectively.
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")

        if not await self._user_is_creator(db_game, user_identity_id):
            raise PermissionError("Only the game creator can archive this game")

        await self.repo.archive_game(game_id, reason=reason)
        refreshed = await self.repo.get_game(game_id)
        assert refreshed is not None
        return refreshed

    async def unarchive_game(
        self,
        game_id: str,
        user_identity_id: int,
    ) -> DBGame:
        """Restore a previously-archived game for the creator.

        Clears ``archived_at`` and ``archived_reason``; the game's prior
        ``status`` is untouched (Phase 5 stale-active games transition to
        ``ended`` at archive time, so restoring them leaves them ended —
        deliberate).
        """
        db_game = await self.repo.get_game(game_id)
        if db_game is None:
            raise ValueError(f"Game {game_id} not found")

        if not await self._user_is_creator(db_game, user_identity_id):
            raise PermissionError("Only the game creator can unarchive this game")

        await self.repo.unarchive_game(game_id)
        refreshed = await self.repo.get_game(game_id)
        assert refreshed is not None
        return refreshed

    async def _user_is_creator(self, db_game: DBGame, user_identity_id: int) -> bool:
        """Return True when ``user_identity_id`` owns the creator seat.

        ``Game.creator`` is a player_id (slot-0 display name). To attribute
        a creator check back to a signed-in user, we resolve the caller's
        seat in this game via ``get_player_api_key_by_user_identity`` and
        match its ``player_id`` against ``Game.creator``. MCP-minted keys
        (null identity) never win this check, which is the intended
        invariant: agents cannot archive.
        """
        if db_game.creator is None:
            return False
        seat = await self.repo.get_player_api_key_by_user_identity(
            db_game.id, user_identity_id
        )
        if seat is None:
            return False
        return seat.player_id == db_game.creator

    async def get_game_info(self, game_id: str) -> DBGame | None:
        """Get game database record with metadata."""
        return await self.repo.get_game(game_id)

    async def restore_game_state(self, game_id: str) -> GameState | None:
        """Restore game state from database snapshot if needed."""
        snapshot_state = await self.repo.restore_game_from_snapshot(game_id)
        if snapshot_state:
            self._game_cache[game_id] = snapshot_state
            return snapshot_state

        # Fallback to regular database load
        return await self.load_game_from_database(game_id)

    async def get_current_turn(self, game_id: str) -> int:
        """Get the current turn number for a game."""
        state = await self.get_game_state(game_id)
        return state.turn if state else 0

    def clear_cache(self, game_id: str | None = None) -> None:
        """Clear game state cache."""
        if game_id:
            self._game_cache.pop(game_id, None)
        else:
            self._game_cache.clear()


# Global controller instance - single controller for all sessions
_global_controller: PersistentGameController | None = None


def get_persistent_game_controller(session: AsyncSession) -> PersistentGameController:
    """Get or create a persistent game controller. Uses single global instance to share state."""
    global _global_controller

    if _global_controller is None:
        _global_controller = PersistentGameController(session)
    else:
        # Rebind the controller to the current request session while preserving
        # cached game state and pending actions across requests.
        _global_controller.session = session
        _global_controller.repo = GameRepository(session)

    return _global_controller
