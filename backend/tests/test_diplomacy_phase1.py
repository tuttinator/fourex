"""Tests for Diplomacy Phase 1: relations foundation.

Covers acceptance criteria from ``plans/diplomacy-plan.md`` Phase 1:

* deterministic id counter, discovered set, and event log on ``GameState``;
* ``DECLARE_WAR`` action: immediate effect, undiscovered rejection, self/missing
  rejection, already-at-war rejection, public ``WAR_DECLARED`` event;
* treacherous-attack auto-flip from PEACE to WAR for both unit and city targets;
* ``redact_state`` per-viewer filtering of relations, discovered set, and the
  diplomatic event feed;
* ``update_discovery`` is permanent and one-directional per observation;
* MCP ``declare_war`` + ``get_diplomacy_state`` and REST ``/diplomacy`` parity;
* replay determinism: identical seed + actions produce identical event ids.
"""

from __future__ import annotations

import json
import random
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, GameSnapshot, PlayerApiKey
from backend.src.game.models import (
    AttackAction,
    City,
    Coord,
    DeclareWarAction,
    DiplomaticEventType,
    DiplomaticState,
    GameState,
    Terrain,
    Tile,
    Unit,
    UnitType,
    UNIT_STATS,
)
from backend.src.game.rules import (
    emit_diplomatic_event,
    execute_attack,
    execute_declare_war,
    generate_map,
    has_discovered,
    place_starting_units,
    record_discovery,
    redact_state,
    resolve_turn,
    set_relation,
    update_discovery,
)
from backend.src.mcp_server.server import create_mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_state(
    players: list[str] | None = None,
    width: int = 12,
    height: int = 12,
    seed: int = 7,
) -> GameState:
    return GameState(
        rng_state=seed,
        tiles=generate_map(width, height, seed),
        players=players or [],
        map_width=width,
        map_height=height,
    )


def _state_with_two_players(seed: int = 11) -> GameState:
    state = _fresh_state(players=["alice", "bob"], seed=seed)
    rng = random.Random(seed)
    place_starting_units(state, "alice", rng)
    place_starting_units(state, "bob", rng)
    return state


# ---------------------------------------------------------------------------
# GameState carries new diplomatic fields
# ---------------------------------------------------------------------------


def test_game_state_has_diplomacy_fields_with_defaults():
    state = _fresh_state()
    assert state.next_event_id == 1
    assert state.diplomatic_events == []
    assert state.discovered == {}


def test_emit_event_increments_counter_and_records_turn():
    state = _fresh_state(players=["alice", "bob"], seed=1)
    state.turn = 4

    e1 = emit_diplomatic_event(
        state,
        DiplomaticEventType.WAR_DECLARED,
        actor="alice",
        counterparty="bob",
        payload={"cause": "declaration"},
    )
    e2 = emit_diplomatic_event(
        state,
        DiplomaticEventType.TREACHEROUS_ATTACK,
        actor="bob",
        counterparty="alice",
    )

    assert e1.id == 1
    assert e2.id == 2
    assert state.next_event_id == 3
    assert e1.turn == 4 and e2.turn == 4
    assert state.diplomatic_events == [e1, e2]


# ---------------------------------------------------------------------------
# Discovery: permanent, one-directional, idempotent
# ---------------------------------------------------------------------------


def test_record_discovery_is_idempotent_and_self_skipping():
    state = _fresh_state(players=["alice", "bob"])
    record_discovery(state, "alice", "bob")
    record_discovery(state, "alice", "bob")
    record_discovery(state, "alice", "alice")  # self -> noop
    assert state.discovered["alice"] == ["bob"]
    assert "alice" not in state.discovered.get("alice", [])


def test_has_discovered_self_and_target():
    state = _fresh_state(players=["alice", "bob"])
    record_discovery(state, "alice", "bob")
    assert has_discovered(state, "alice", "alice") is True
    assert has_discovered(state, "alice", "bob") is True
    assert has_discovered(state, "bob", "alice") is False


def test_update_discovery_records_visible_units_only():
    state = _fresh_state(players=["alice", "bob"], width=10, height=10)
    # Put alice's scout next to bob's worker so alice sees bob.
    state.tiles = [
        Tile(id=i, loc=Coord(x=i % 10, y=i // 10), terrain=Terrain.GRASS)
        for i in range(100)
    ]
    # Alice's scout (sight=3) at (1,1); Bob's worker (sight=2) at (1,4).
    # Manhattan distance is 3 — alice sees bob, but bob does not see alice.
    state.units[1] = Unit(
        id=1,
        owner="alice",
        type=UnitType.SCOUT,
        loc=Coord(x=1, y=1),
        hp=2,
        moves_left=3,
        stats=UNIT_STATS[UnitType.SCOUT],
    )
    state.units[2] = Unit(
        id=2,
        owner="bob",
        type=UnitType.WORKER,
        loc=Coord(x=1, y=4),
        hp=100,
        moves_left=1,
        stats=UNIT_STATS[UnitType.WORKER],
    )
    state.next_unit_id = 3

    update_discovery(state)

    assert "bob" in state.discovered.get("alice", [])
    # bob has no unit close enough to alice's scout to see her
    assert state.discovered.get("bob", []) == []


# ---------------------------------------------------------------------------
# DECLARE_WAR action validation
# ---------------------------------------------------------------------------


def test_declare_war_rejects_self():
    state = _state_with_two_players()
    update_discovery(state)
    result = execute_declare_war(
        state, "alice", DeclareWarAction(target_player="alice")
    )
    assert result.success is False
    assert "yourself" in result.message


def test_declare_war_rejects_missing_player():
    state = _state_with_two_players()
    result = execute_declare_war(
        state, "alice", DeclareWarAction(target_player="ghost")
    )
    assert result.success is False
    assert "not in this game" in result.message


def test_declare_war_rejects_undiscovered_target():
    state = _state_with_two_players()
    # Force-clear discovery so neither player has seen the other.
    state.discovered = {}
    result = execute_declare_war(
        state, "alice", DeclareWarAction(target_player="bob")
    )
    assert result.success is False
    assert "undiscovered" in result.message
    # No event should have been emitted.
    assert state.diplomatic_events == []


def test_declare_war_succeeds_and_emits_event():
    state = _state_with_two_players()
    record_discovery(state, "alice", "bob")
    state.turn = 3

    result = execute_declare_war(
        state, "alice", DeclareWarAction(target_player="bob")
    )

    assert result.success is True
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.WAR
    assert len(state.diplomatic_events) == 1
    event = state.diplomatic_events[0]
    assert event.type == DiplomaticEventType.WAR_DECLARED
    assert event.actor == "alice"
    assert event.counterparty == "bob"
    assert event.turn == 3
    assert event.payload == {"cause": "declaration"}


def test_declare_war_rejects_already_at_war():
    state = _state_with_two_players()
    record_discovery(state, "alice", "bob")
    set_relation(state, "alice", "bob", DiplomaticState.WAR)

    result = execute_declare_war(
        state, "alice", DeclareWarAction(target_player="bob")
    )
    assert result.success is False
    assert "Already at war" in result.message


def test_set_relation_clears_inverse_key():
    state = _fresh_state(players=["alice", "bob"])
    state.diplomacy[("bob", "alice")] = DiplomaticState.PEACE  # legacy unsorted

    set_relation(state, "alice", "bob", DiplomaticState.WAR)

    # Only the canonical sorted-pair key remains.
    assert state.diplomacy == {("alice", "bob"): DiplomaticState.WAR}


# ---------------------------------------------------------------------------
# Treacherous attack: unit and city targets
# ---------------------------------------------------------------------------


def _two_unit_combat_state(distance: int = 1) -> GameState:
    state = _fresh_state(players=["alice", "bob"], width=8, height=8)
    state.tiles = [
        Tile(id=i, loc=Coord(x=i % 8, y=i // 8), terrain=Terrain.GRASS)
        for i in range(64)
    ]
    state.units[1] = Unit(
        id=1,
        owner="alice",
        type=UnitType.SOLDIER,
        loc=Coord(x=2, y=2),
        hp=10,
        moves_left=1,
        stats=UNIT_STATS[UnitType.SOLDIER],
    )
    state.units[2] = Unit(
        id=2,
        owner="bob",
        type=UnitType.SOLDIER,
        loc=Coord(x=2 + distance, y=2),
        hp=10,
        moves_left=1,
        stats=UNIT_STATS[UnitType.SOLDIER],
    )
    state.next_unit_id = 3
    return state


def test_treacherous_attack_on_unit_flips_to_war_and_emits_events():
    state = _two_unit_combat_state()
    state.turn = 2
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.PEACE

    result = execute_attack(
        state,
        AttackAction(attacker_id=1, target_id=2, target_type="unit"),
    )
    assert result.success is True
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.WAR

    types = [e.type for e in state.diplomatic_events]
    assert DiplomaticEventType.TREACHEROUS_ATTACK in types
    assert DiplomaticEventType.WAR_DECLARED in types
    war_evt = next(
        e for e in state.diplomatic_events
        if e.type == DiplomaticEventType.WAR_DECLARED
    )
    assert war_evt.payload == {"cause": "treacherous_attack"}


def test_treacherous_attack_on_city_flips_to_war():
    state = _fresh_state(players=["alice", "bob"], width=8, height=8)
    state.tiles = [
        Tile(id=i, loc=Coord(x=i % 8, y=i // 8), terrain=Terrain.GRASS)
        for i in range(64)
    ]
    state.units[1] = Unit(
        id=1,
        owner="alice",
        type=UnitType.SOLDIER,
        loc=Coord(x=2, y=2),
        hp=10,
        moves_left=1,
        stats=UNIT_STATS[UnitType.SOLDIER],
    )
    state.cities[1] = City(
        id=1,
        owner="bob",
        loc=Coord(x=3, y=2),
        hp=20,
        max_hp=20,
        culture=0,
        border_radius=1,
    )
    state.next_unit_id = 2
    state.next_city_id = 2

    result = execute_attack(
        state,
        AttackAction(attacker_id=1, target_id=1, target_type="city"),
    )
    assert result.success is True
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.WAR
    assert any(
        e.type == DiplomaticEventType.TREACHEROUS_ATTACK
        and e.payload.get("target_type") == "city"
        for e in state.diplomatic_events
    )


def test_attack_already_at_war_emits_no_treacherous_event():
    state = _two_unit_combat_state()
    set_relation(state, "alice", "bob", DiplomaticState.WAR)
    execute_attack(
        state, AttackAction(attacker_id=1, target_id=2, target_type="unit")
    )
    assert all(
        e.type != DiplomaticEventType.TREACHEROUS_ATTACK
        for e in state.diplomatic_events
    )


def test_attack_on_ally_still_blocked():
    state = _two_unit_combat_state()
    set_relation(state, "alice", "bob", DiplomaticState.ALLIANCE)
    result = execute_attack(
        state, AttackAction(attacker_id=1, target_id=2, target_type="unit")
    )
    assert result.success is False
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.ALLIANCE
    assert state.diplomatic_events == []


# ---------------------------------------------------------------------------
# redact_state filtering
# ---------------------------------------------------------------------------


def test_redact_state_filters_discovered_relations_and_events():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=1)
    state.turn = 5

    # alice has discovered bob only; bob has discovered alice + carol.
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    record_discovery(state, "bob", "carol")
    record_discovery(state, "carol", "bob")

    set_relation(state, "alice", "bob", DiplomaticState.WAR)
    set_relation(state, "bob", "carol", DiplomaticState.PEACE)

    # Events alice should not see (carol-only, both undiscovered to her).
    emit_diplomatic_event(
        state,
        DiplomaticEventType.WAR_DECLARED,
        actor="bob",
        counterparty="carol",
        payload={"cause": "declaration"},
    )
    # Event involving alice — she should see it.
    emit_diplomatic_event(
        state,
        DiplomaticEventType.WAR_DECLARED,
        actor="alice",
        counterparty="bob",
        payload={"cause": "declaration"},
    )

    redacted = redact_state(state, "alice")

    # Alice's discovered set is preserved; nobody else's is.
    assert redacted.discovered == {"alice": ["bob"]}

    # Alice sees alice<->bob; bob<->carol involves carol whom alice has not
    # discovered, so it is filtered.
    assert ("alice", "bob") in redacted.diplomacy
    assert ("bob", "carol") not in redacted.diplomacy

    # Alice sees the war involving herself but not the bob-vs-carol war.
    seen_pairs = {(e.actor, e.counterparty) for e in redacted.diplomatic_events}
    assert ("alice", "bob") in seen_pairs
    assert ("bob", "carol") not in seen_pairs


def test_redact_state_shows_third_party_war_when_both_discovered():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=2)
    record_discovery(state, "alice", "bob")
    record_discovery(state, "alice", "carol")
    set_relation(state, "bob", "carol", DiplomaticState.WAR)
    emit_diplomatic_event(
        state,
        DiplomaticEventType.WAR_DECLARED,
        actor="bob",
        counterparty="carol",
    )

    redacted = redact_state(state, "alice")

    assert ("bob", "carol") in redacted.diplomacy
    assert any(
        e.actor == "bob" and e.counterparty == "carol"
        for e in redacted.diplomatic_events
    )


# ---------------------------------------------------------------------------
# Determinism: replay reproduces identical event ids
# ---------------------------------------------------------------------------


def test_replay_with_same_seed_and_actions_produces_identical_events():
    def run() -> list[tuple[int, str, str | None]]:
        state = _state_with_two_players(seed=99)
        update_discovery(state)
        record_discovery(state, "alice", "bob")
        record_discovery(state, "bob", "alice")
        actions = {
            "alice": [DeclareWarAction(target_player="bob")],
            "bob": [],
        }
        resolve_turn(state, actions)
        return [(e.id, e.type.value, e.counterparty) for e in state.diplomatic_events]

    assert run() == run()


# ---------------------------------------------------------------------------
# MCP + REST surface for Phase 1
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("game_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("game_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("game_%")))
        await session.commit()


@pytest.fixture
def mcp():
    return create_mcp_server()


async def _call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_mcp_get_diplomacy_state_initial_shape(db_session, mcp):
    data = await _call(mcp, "create_game", {"players": ["alice", "bob"], "seed": 31})
    alice_key = data["api_keys"]["alice"]

    dip = await _call(mcp, "get_diplomacy_state", {"api_key": alice_key})
    assert dip["player"] == "alice"
    assert "discovered" in dip
    assert "relations" in dip
    assert "events" in dip
    # Initial state: no events yet
    assert dip["events"] == []


@pytest.mark.asyncio
async def test_mcp_declare_war_returns_action_payload(db_session, mcp):
    data = await _call(mcp, "create_game", {"players": ["alice", "bob"], "seed": 32})
    alice_key = data["api_keys"]["alice"]

    out = await _call(
        mcp,
        "declare_war",
        {"api_key": alice_key, "target_player": "bob"},
    )
    # The MCP tool returns an action payload; submission happens via submit_actions.
    assert "action" in out
    assert out["action"]["type"] == "DECLARE_WAR"
    assert out["action"]["target_player"] == "bob"
