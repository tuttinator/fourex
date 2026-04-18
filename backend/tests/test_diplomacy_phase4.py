"""Tests for Diplomacy Phase 4: resource clauses (swap + recurring tribute).

Covers acceptance criteria from ``plans/diplomacy-plan.md`` Phase 4:

* ``ResourceSwapClause`` executes atomically at ratification (both parties
  pay simultaneously);
* swap unfundable on the non-ally route at acceptance →
  ``PROPOSAL_FAILED_UNFUNDABLE``, no treaty, no one charged;
* swap between allies is pre-validated at proposal time (caller sees the
  error before the proposal is queued);
* ``RecurringTributeClause`` transfers the specified amount each turn for
  ``duration_turns`` turns;
* unfundable tribute emits ``TRIBUTE_FAILED`` + ``TREATY_VIOLATED``, cancels
  the treaty, and does not partially pay the failing clause;
* auto-expiry: swap-only treaty expires at end of ratification turn; tribute
  treaty expires when the final payment is made;
* MCP + REST surfaces accept swap + tribute clause dicts;
* replay determinism with the same seed and action sequences.
"""

from __future__ import annotations

import json
import random
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    PromptLog,
)
from backend.src.game.models import (
    DiplomaticEventType,
    DiplomaticState,
    FreeTextClause,
    GameState,
    PeaceClause,
    ProposeTreatyAction,
    RecurringTributeClause,
    ResourceBag,
    ResourceSwapClause,
    RespondToTreatyAction,
)
from backend.src.game.rules import (
    execute_propose_treaty,
    execute_respond_to_treaty,
    generate_map,
    place_starting_units,
    record_discovery,
    resolve_diplomacy_phase,
    resolve_turn,
    set_relation,
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


def _state_with_two_players(
    seed: int = 41,
    alice_bag: ResourceBag | None = None,
    bob_bag: ResourceBag | None = None,
) -> GameState:
    state = _fresh_state(players=["alice", "bob"], seed=seed)
    rng = random.Random(seed)
    place_starting_units(state, "alice", rng)
    place_starting_units(state, "bob", rng)
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    if alice_bag is not None:
        state.stockpiles["alice"] = alice_bag
    if bob_bag is not None:
        state.stockpiles["bob"] = bob_bag
    return state


def _swap(
    proposer_gives: ResourceBag | None = None,
    recipient_gives: ResourceBag | None = None,
) -> ResourceSwapClause:
    return ResourceSwapClause(
        proposer_gives=proposer_gives or ResourceBag(),
        recipient_gives=recipient_gives or ResourceBag(),
    )


def _tribute(
    payer: str,
    amount: ResourceBag,
    duration: int = 3,
) -> RecurringTributeClause:
    return RecurringTributeClause(
        payer=payer,
        amount=amount,
        duration_turns=duration,
        turns_remaining=duration,
    )


def _accept_latest(state: GameState, responder: str) -> None:
    proposal_id = state.pending_proposals[-1].id
    execute_respond_to_treaty(
        state,
        responder,
        RespondToTreatyAction(proposal_id=proposal_id, accept=True),
    )


# ---------------------------------------------------------------------------
# Shape validation at proposal time
# ---------------------------------------------------------------------------


def test_propose_rejects_swap_with_no_resources():
    state = _state_with_two_players()
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_swap()]),
    )
    assert result.success is False
    assert "at least one resource" in result.message


def test_propose_rejects_swap_with_negative_amount():
    state = _state_with_two_players()
    clause = ResourceSwapClause(
        proposer_gives=ResourceBag(food=-1),
        recipient_gives=ResourceBag(wood=1),
    )
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    assert result.success is False
    assert "negative" in result.message


def test_propose_rejects_tribute_with_third_party_payer():
    state = _fresh_state(players=["alice", "bob", "carol"])
    rng = random.Random(99)
    place_starting_units(state, "alice", rng)
    place_starting_units(state, "bob", rng)
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    bad = RecurringTributeClause(
        payer="carol",
        amount=ResourceBag(food=1),
        duration_turns=3,
        turns_remaining=3,
    )
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[bad]),
    )
    assert result.success is False
    assert "payer" in result.message.lower()


def test_propose_rejects_tribute_with_zero_amount():
    state = _state_with_two_players()
    bad = RecurringTributeClause(
        payer="alice",
        amount=ResourceBag(),
        duration_turns=3,
        turns_remaining=3,
    )
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[bad]),
    )
    assert result.success is False
    assert "positive" in result.message.lower()


# ---------------------------------------------------------------------------
# Ally pre-validation vs bluff
# ---------------------------------------------------------------------------


def test_ally_swap_prevalidated_when_unfundable():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=1),
        bob_bag=ResourceBag(food=50),
    )
    set_relation(state, "alice", "bob", DiplomaticState.ALLIANCE)
    clause = _swap(
        proposer_gives=ResourceBag(food=10),
        recipient_gives=ResourceBag(wood=1),
    )
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    assert result.success is False
    assert "afford" in result.message.lower()
    assert state.pending_proposals == []


def test_non_ally_swap_bluff_is_allowed_at_proposal_time():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=1),
        bob_bag=ResourceBag(food=50),
    )
    # default relation is PEACE — non-ally route, bluffing permitted
    clause = _swap(
        proposer_gives=ResourceBag(food=10),
        recipient_gives=ResourceBag(wood=1),
    )
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    assert result.success is True
    assert len(state.pending_proposals) == 1


def test_ally_tribute_prevalidated_when_unfundable():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=2),
        bob_bag=ResourceBag(food=50),
    )
    set_relation(state, "alice", "bob", DiplomaticState.ALLIANCE)
    clause = _tribute("alice", ResourceBag(food=10), duration=3)
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    assert result.success is False
    assert "afford" in result.message.lower()


# ---------------------------------------------------------------------------
# Atomic swap at ratification
# ---------------------------------------------------------------------------


def test_swap_transfers_simultaneously_on_accept():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=20, wood=0),
        bob_bag=ResourceBag(food=0, wood=15),
    )
    clause = _swap(
        proposer_gives=ResourceBag(food=10),
        recipient_gives=ResourceBag(wood=5),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    _accept_latest(state, "bob")
    assert state.stockpiles["alice"] == ResourceBag(food=10, wood=5)
    assert state.stockpiles["bob"] == ResourceBag(food=10, wood=10)


def test_swap_unfundable_at_acceptance_emits_failed_and_charges_no_one():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=20),
        bob_bag=ResourceBag(wood=15),
    )
    clause = _swap(
        proposer_gives=ResourceBag(food=10),
        recipient_gives=ResourceBag(wood=5),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[clause]),
    )
    # Alice spends her food elsewhere before Bob accepts.
    state.stockpiles["alice"] = ResourceBag(food=1)
    alice_before = state.stockpiles["alice"].model_copy()
    bob_before = state.stockpiles["bob"].model_copy()
    _accept_latest(state, "bob")

    assert state.stockpiles["alice"] == alice_before
    assert state.stockpiles["bob"] == bob_before
    assert state.active_treaties == []
    assert any(
        e.type == DiplomaticEventType.PROPOSAL_FAILED_UNFUNDABLE
        for e in state.diplomatic_events
    )
    # No PROPOSAL_ACCEPTED event should have been emitted.
    assert not any(
        e.type == DiplomaticEventType.PROPOSAL_ACCEPTED
        for e in state.diplomatic_events
    )


def test_swap_only_treaty_auto_expires_after_ratification_turn():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=20),
        bob_bag=ResourceBag(wood=15),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[
                _swap(
                    proposer_gives=ResourceBag(food=5),
                    recipient_gives=ResourceBag(wood=3),
                )
            ],
        ),
    )
    _accept_latest(state, "bob")
    assert len(state.active_treaties) == 1
    resolve_diplomacy_phase(state)
    assert state.active_treaties == []
    assert any(
        e.type == DiplomaticEventType.TREATY_EXPIRED
        for e in state.diplomatic_events
    )


def test_swap_bundled_with_free_text_persists_after_ratification():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=20),
        bob_bag=ResourceBag(wood=15),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[
                _swap(
                    proposer_gives=ResourceBag(food=5),
                    recipient_gives=ResourceBag(wood=3),
                ),
                FreeTextClause(text="and open borders forever"),
            ],
        ),
    )
    _accept_latest(state, "bob")
    resolve_diplomacy_phase(state)
    assert len(state.active_treaties) == 1


# ---------------------------------------------------------------------------
# Recurring tribute
# ---------------------------------------------------------------------------


def test_tribute_transfers_each_turn_for_duration():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=30),
        bob_bag=ResourceBag(),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[_tribute("alice", ResourceBag(food=5), duration=3)],
        ),
    )
    _accept_latest(state, "bob")

    # Turn 1 tribute payment
    resolve_diplomacy_phase(state)
    assert state.stockpiles["alice"].food == 25
    assert state.stockpiles["bob"].food == 5
    # Turn 2
    resolve_diplomacy_phase(state)
    assert state.stockpiles["alice"].food == 20
    assert state.stockpiles["bob"].food == 10
    # Turn 3 — final payment; treaty expires this turn
    resolve_diplomacy_phase(state)
    assert state.stockpiles["alice"].food == 15
    assert state.stockpiles["bob"].food == 15
    assert state.active_treaties == []
    paid = [
        e for e in state.diplomatic_events
        if e.type == DiplomaticEventType.TRIBUTE_PAID
    ]
    assert len(paid) == 3


def test_tribute_unfundable_cancels_treaty_and_does_not_partially_pay():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=3),
        bob_bag=ResourceBag(),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[_tribute("alice", ResourceBag(food=5), duration=3)],
        ),
    )
    _accept_latest(state, "bob")

    resolve_diplomacy_phase(state)

    # No partial pay: Alice retains her 3 food, Bob gets nothing.
    assert state.stockpiles["alice"].food == 3
    assert state.stockpiles["bob"].food == 0
    # Treaty cancelled; both TRIBUTE_FAILED and TREATY_VIOLATED emitted.
    assert state.active_treaties == []
    types = [e.type for e in state.diplomatic_events]
    assert DiplomaticEventType.TRIBUTE_FAILED in types
    assert DiplomaticEventType.TREATY_VIOLATED in types


def test_tribute_decrement_is_independent_per_clause():
    # Two tribute clauses with different durations in the same treaty.
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=100, wood=100),
        bob_bag=ResourceBag(),
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[
                _tribute("alice", ResourceBag(food=1), duration=1),
                _tribute("alice", ResourceBag(wood=1), duration=3),
            ],
        ),
    )
    _accept_latest(state, "bob")

    resolve_diplomacy_phase(state)  # both pay; food clause expires
    resolve_diplomacy_phase(state)  # wood-only
    resolve_diplomacy_phase(state)  # wood final

    assert state.stockpiles["alice"].food == 99
    assert state.stockpiles["alice"].wood == 97
    assert state.stockpiles["bob"].food == 1
    assert state.stockpiles["bob"].wood == 3
    assert state.active_treaties == []


# ---------------------------------------------------------------------------
# Normalisation and discriminated union validation
# ---------------------------------------------------------------------------


def test_propose_normalises_tribute_turns_remaining_to_duration():
    state = _state_with_two_players()
    bad = RecurringTributeClause(
        payer="alice",
        amount=ResourceBag(food=1),
        duration_turns=5,
        turns_remaining=0,  # client-supplied rubbish
    )
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[bad]),
    )
    stored = state.pending_proposals[0].clauses[0]
    assert isinstance(stored, RecurringTributeClause)
    assert stored.turns_remaining == 5


def test_proposal_round_trip_preserves_clause_types():
    state = _state_with_two_players(
        alice_bag=ResourceBag(food=20),
        bob_bag=ResourceBag(wood=20),
    )
    action = ProposeTreatyAction(
        recipient="bob",
        clauses=[
            PeaceClause(duration_turns=5, turns_remaining=5),
            _swap(
                proposer_gives=ResourceBag(food=1),
                recipient_gives=ResourceBag(wood=1),
            ),
            _tribute("alice", ResourceBag(food=1), duration=2),
            FreeTextClause(text="all good"),
        ],
    )
    execute_propose_treaty(state, "alice", action)
    dumped = state.model_dump(mode="json")
    restored = GameState.model_validate(dumped)
    types = [c.clause_type for c in restored.pending_proposals[0].clauses]
    assert types == ["peace", "resource_swap", "recurring_tribute", "free_text"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_resource_clause_lifecycle_is_deterministic():
    def run() -> dict:
        state = _state_with_two_players(
            seed=71,
            alice_bag=ResourceBag(food=30, wood=10),
            bob_bag=ResourceBag(wood=20),
        )
        execute_propose_treaty(
            state,
            "alice",
            ProposeTreatyAction(
                recipient="bob",
                clauses=[
                    _swap(
                        proposer_gives=ResourceBag(food=5),
                        recipient_gives=ResourceBag(wood=3),
                    ),
                    _tribute("alice", ResourceBag(food=1), duration=2),
                ],
            ),
        )
        _accept_latest(state, "bob")
        resolve_turn(state, {"alice": [], "bob": []})
        resolve_turn(state, {"alice": [], "bob": []})
        return {
            "hash": state.hash_state(),
            "alice": state.stockpiles["alice"].model_dump(),
            "bob": state.stockpiles["bob"].model_dump(),
            "events": [
                (e.id, e.type.value, e.actor, e.counterparty)
                for e in state.diplomatic_events
            ],
        }

    assert run() == run()


# ---------------------------------------------------------------------------
# MCP surface
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
        await session.execute(
            delete(PromptLog).where(PromptLog.game_id.like("game_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("game_%"))
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
async def test_mcp_propose_treaty_accepts_swap_and_tribute_clauses(
    db_session, mcp
):
    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob"], "seed": 91}
    )
    alice_key = data["api_keys"]["alice"]

    out = await _call(
        mcp,
        "propose_treaty",
        {
            "api_key": alice_key,
            "recipient": "bob",
            "clauses": [
                {
                    "clause_type": "resource_swap",
                    "proposer_gives": {"food": 5},
                    "recipient_gives": {"wood": 3},
                },
                {
                    "clause_type": "recurring_tribute",
                    "payer": "alice",
                    "amount": {"food": 2},
                    "duration_turns": 4,
                },
            ],
        },
    )
    assert "action" in out
    assert len(out["action"]["clauses"]) == 2
    assert out["action"]["clauses"][0]["clause_type"] == "resource_swap"
    assert out["action"]["clauses"][1]["clause_type"] == "recurring_tribute"
    assert out["action"]["clauses"][1]["turns_remaining"] == 4


@pytest.mark.asyncio
async def test_mcp_propose_treaty_rejects_unknown_clause(db_session, mcp):
    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob"], "seed": 92}
    )
    alice_key = data["api_keys"]["alice"]

    out = await _call(
        mcp,
        "propose_treaty",
        {
            "api_key": alice_key,
            "recipient": "bob",
            "clauses": [{"clause_type": "open_borders"}],
        },
    )
    assert "error" in out
