"""Tests for Diplomacy Phase 3: treaty lifecycle (peace + free-text clauses).

Covers acceptance criteria from ``plans/diplomacy-plan.md`` Phase 3:

* ``PROPOSE_TREATY`` validation: self/undiscovered/non-player/empty-clauses;
* proposal auto-expiry after ``TREATY_PROPOSAL_EXPIRY_TURNS`` turns;
* ``RESPOND_TO_TREATY`` accept flips WAR→PEACE via peace clauses and records
  an ``active_treaty``; decline removes the proposal silently from state;
* ``WITHDRAW_TREATY`` only allowed by the original proposer;
* ``CANCEL_TREATY`` emits ``TREATY_VIOLATED`` when an obligation is active
  and ``TREATY_CANCELLED`` when it is not;
* declaring war cancels existing treaties between the pair
  (routine cancellation, not a violation since war is antecedent);
* treacherous attack cancels treaties as ``TREATY_VIOLATED``;
* ``redact_state`` keeps ``pending_proposals`` private to proposer and
  recipient; ``active_treaties`` are public;
* replay determinism with a shared seed and identical action sequences;
* MCP and REST surfaces return the same lifecycle payloads.
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
    TREATY_PROPOSAL_EXPIRY_TURNS,
    CancelTreatyAction,
    DeclareWarAction,
    DiplomaticEventType,
    DiplomaticState,
    FreeTextClause,
    GameState,
    PeaceClause,
    ProposeTreatyAction,
    RespondToTreatyAction,
    WithdrawTreatyAction,
)
from backend.src.game.rules import (
    execute_cancel_treaty,
    execute_declare_war,
    execute_propose_treaty,
    execute_respond_to_treaty,
    execute_withdraw_treaty,
    generate_map,
    place_starting_units,
    record_discovery,
    redact_state,
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


def _state_with_two_players(seed: int = 13) -> GameState:
    state = _fresh_state(players=["alice", "bob"], seed=seed)
    rng = random.Random(seed)
    place_starting_units(state, "alice", rng)
    place_starting_units(state, "bob", rng)
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    return state


def _peace(duration: int = 5) -> PeaceClause:
    return PeaceClause(duration_turns=duration, turns_remaining=duration)


# ---------------------------------------------------------------------------
# GameState defaults
# ---------------------------------------------------------------------------


def test_state_has_treaty_fields_with_defaults():
    state = _fresh_state()
    assert state.next_proposal_id == 1
    assert state.next_treaty_id == 1
    assert state.pending_proposals == []
    assert state.active_treaties == []


# ---------------------------------------------------------------------------
# execute_propose_treaty validation and success paths
# ---------------------------------------------------------------------------


def test_propose_rejects_self():
    state = _state_with_two_players()
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="alice", clauses=[_peace()]),
    )
    assert result.success is False
    assert "yourself" in result.message


def test_propose_rejects_missing_player():
    state = _state_with_two_players()
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="ghost", clauses=[_peace()]),
    )
    assert result.success is False
    assert "not in this game" in result.message


def test_propose_rejects_undiscovered():
    state = _state_with_two_players()
    state.discovered = {}
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    assert result.success is False
    assert "undiscovered" in result.message


def test_propose_rejects_empty_clauses():
    state = _state_with_two_players()
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[]),
    )
    assert result.success is False
    assert "clause" in result.message.lower()


def test_propose_queues_proposal_and_emits_event():
    state = _state_with_two_players()
    state.turn = 4
    result = execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[_peace(6), FreeTextClause(text="and fair trade")],
        ),
    )
    assert result.success is True
    assert len(state.pending_proposals) == 1
    p = state.pending_proposals[0]
    assert p.id == 1
    assert p.proposer == "alice"
    assert p.recipient == "bob"
    assert p.turn_proposed == 4
    assert p.expires_on_turn == 4 + TREATY_PROPOSAL_EXPIRY_TURNS
    assert state.next_proposal_id == 2
    # A TREATY_PROPOSED event is recorded.
    assert any(
        e.type == DiplomaticEventType.TREATY_PROPOSED
        and e.payload.get("proposal_id") == "1"
        for e in state.diplomatic_events
    )


def test_propose_normalises_peace_turns_remaining_to_duration():
    state = _state_with_two_players()
    # Even if caller provides a fiddly turns_remaining, it's normalised to
    # duration_turns at proposal time so the recipient sees the offered span.
    action = ProposeTreatyAction(
        recipient="bob",
        clauses=[PeaceClause(duration_turns=10, turns_remaining=2)],
    )
    execute_propose_treaty(state, "alice", action)
    clause = state.pending_proposals[0].clauses[0]
    assert isinstance(clause, PeaceClause)
    assert clause.duration_turns == 10
    assert clause.turns_remaining == 10


# ---------------------------------------------------------------------------
# Respond: accept flips WAR→PEACE and records treaty
# ---------------------------------------------------------------------------


def test_accept_flips_war_to_peace_and_creates_treaty():
    state = _state_with_two_players()
    set_relation(state, "alice", "bob", DiplomaticState.WAR)
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace(5)]),
    )
    proposal_id = state.pending_proposals[0].id

    result = execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(proposal_id=proposal_id, accept=True),
    )
    assert result.success is True
    assert state.pending_proposals == []
    assert len(state.active_treaties) == 1
    treaty = state.active_treaties[0]
    assert set(treaty.parties) == {"alice", "bob"}
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.PEACE
    # PROPOSAL_ACCEPTED event captures the treaty id.
    assert any(
        e.type == DiplomaticEventType.PROPOSAL_ACCEPTED
        and e.payload.get("treaty_id") == str(treaty.id)
        for e in state.diplomatic_events
    )


def test_decline_removes_proposal_and_emits_event():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    proposal_id = state.pending_proposals[0].id

    result = execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(proposal_id=proposal_id, accept=False),
    )
    assert result.success is True
    assert state.pending_proposals == []
    assert state.active_treaties == []
    assert any(
        e.type == DiplomaticEventType.PROPOSAL_DECLINED
        for e in state.diplomatic_events
    )


def test_only_recipient_can_respond():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    proposal_id = state.pending_proposals[0].id
    # alice (the proposer) cannot respond to her own proposal.
    result = execute_respond_to_treaty(
        state,
        "alice",
        RespondToTreatyAction(proposal_id=proposal_id, accept=True),
    )
    assert result.success is False
    assert "only" in result.message.lower()
    assert len(state.pending_proposals) == 1


def test_respond_to_unknown_proposal():
    state = _state_with_two_players()
    result = execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(proposal_id=9999, accept=True),
    )
    assert result.success is False
    assert "not found" in result.message


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------


def test_withdraw_by_proposer_removes_proposal_and_emits_event():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    proposal_id = state.pending_proposals[0].id

    result = execute_withdraw_treaty(
        state, "alice", WithdrawTreatyAction(proposal_id=proposal_id)
    )
    assert result.success is True
    assert state.pending_proposals == []
    assert any(
        e.type == DiplomaticEventType.PROPOSAL_WITHDRAWN
        for e in state.diplomatic_events
    )


def test_withdraw_rejected_for_non_proposer():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    proposal_id = state.pending_proposals[0].id
    result = execute_withdraw_treaty(
        state, "bob", WithdrawTreatyAction(proposal_id=proposal_id)
    )
    assert result.success is False
    assert len(state.pending_proposals) == 1


# ---------------------------------------------------------------------------
# Cancel: violation vs cancellation
# ---------------------------------------------------------------------------


def test_cancel_with_active_peace_emits_violated():
    state = _state_with_two_players()
    set_relation(state, "alice", "bob", DiplomaticState.WAR)
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace(5)]),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    treaty_id = state.active_treaties[0].id

    result = execute_cancel_treaty(
        state, "alice", CancelTreatyAction(treaty_id=treaty_id)
    )
    assert result.success is True
    assert state.active_treaties == []
    assert any(
        e.type == DiplomaticEventType.TREATY_VIOLATED
        for e in state.diplomatic_events
    )


def test_cancel_free_text_only_emits_cancelled_not_violated():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[FreeTextClause(text="we are friends")],
        ),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    treaty_id = state.active_treaties[0].id

    result = execute_cancel_treaty(
        state, "alice", CancelTreatyAction(treaty_id=treaty_id)
    )
    assert result.success is True
    assert any(
        e.type == DiplomaticEventType.TREATY_CANCELLED
        for e in state.diplomatic_events
    )
    # No violation event.
    assert not any(
        e.type == DiplomaticEventType.TREATY_VIOLATED
        for e in state.diplomatic_events
    )


def test_cancel_by_non_party_rejected():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=3)
    for a, b in [("alice", "bob"), ("bob", "alice"), ("alice", "carol"), ("carol", "alice"), ("bob", "carol"), ("carol", "bob")]:
        record_discovery(state, a, b)

    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[FreeTextClause(text="friendship")],
        ),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    treaty_id = state.active_treaties[0].id

    result = execute_cancel_treaty(
        state, "carol", CancelTreatyAction(treaty_id=treaty_id)
    )
    assert result.success is False
    assert len(state.active_treaties) == 1


# ---------------------------------------------------------------------------
# Declare war cancels existing treaties
# ---------------------------------------------------------------------------


def test_declare_war_cancels_existing_treaty_as_cancellation_not_violation():
    state = _state_with_two_players()
    # Ratify a peace treaty first.
    set_relation(state, "alice", "bob", DiplomaticState.WAR)
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace(5)]),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.PEACE

    # Alice now declares war; the existing treaty is cancelled.
    execute_declare_war(state, "alice", DeclareWarAction(target_player="bob"))
    assert state.active_treaties == []
    assert state.get_diplomatic_state("alice", "bob") == DiplomaticState.WAR
    # It should be recorded as cancellation (war is the antecedent cause),
    # alongside the war_declared event.
    event_types = [e.type for e in state.diplomatic_events]
    assert DiplomaticEventType.TREATY_CANCELLED in event_types
    assert DiplomaticEventType.WAR_DECLARED in event_types


# ---------------------------------------------------------------------------
# resolve_diplomacy_phase: duration decrement + expiry
# ---------------------------------------------------------------------------


def test_peace_duration_decrements_each_turn_and_expires_at_zero():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace(2)]),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    assert len(state.active_treaties) == 1

    # Resolve two empty turns; the peace clause (duration=2) should expire.
    resolve_turn(state, {"alice": [], "bob": []})
    assert state.active_treaties[0].clauses[0].turns_remaining == 1
    resolve_turn(state, {"alice": [], "bob": []})
    assert state.active_treaties == []
    assert any(
        e.type == DiplomaticEventType.TREATY_EXPIRED
        for e in state.diplomatic_events
    )


def test_pure_free_text_treaty_never_auto_expires():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[FreeTextClause(text="do not harm my caravans")],
        ),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )
    for _ in range(5):
        resolve_turn(state, {"alice": [], "bob": []})
    assert len(state.active_treaties) == 1


def test_proposal_expires_after_deadline():
    state = _state_with_two_players()
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )
    expires_on = state.pending_proposals[0].expires_on_turn

    # `resolve_diplomacy_phase` runs with state.turn at the pre-increment
    # value; we need it to run at least once with state.turn >= expires_on.
    while state.turn <= expires_on:
        resolve_turn(state, {"alice": [], "bob": []})

    assert state.pending_proposals == []
    assert any(
        e.type == DiplomaticEventType.PROPOSAL_EXPIRED
        for e in state.diplomatic_events
    )


# ---------------------------------------------------------------------------
# Redaction: proposals private, treaties public
# ---------------------------------------------------------------------------


def test_proposals_private_to_proposer_and_recipient():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=3)
    for a, b in [("alice", "bob"), ("bob", "alice"), ("carol", "alice"), ("alice", "carol"), ("bob", "carol"), ("carol", "bob")]:
        record_discovery(state, a, b)
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(recipient="bob", clauses=[_peace()]),
    )

    alice_view = redact_state(state, "alice")
    bob_view = redact_state(state, "bob")
    carol_view = redact_state(state, "carol")

    assert len(alice_view.pending_proposals) == 1
    assert len(bob_view.pending_proposals) == 1
    assert carol_view.pending_proposals == []


def test_active_treaties_public_to_all_players():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=3)
    for a, b in [("alice", "bob"), ("bob", "alice"), ("carol", "alice"), ("alice", "carol"), ("bob", "carol"), ("carol", "bob")]:
        record_discovery(state, a, b)
    execute_propose_treaty(
        state,
        "alice",
        ProposeTreatyAction(
            recipient="bob",
            clauses=[FreeTextClause(text="non-aggression")],
        ),
    )
    execute_respond_to_treaty(
        state,
        "bob",
        RespondToTreatyAction(
            proposal_id=state.pending_proposals[0].id, accept=True
        ),
    )

    for viewer in ("alice", "bob", "carol"):
        v = redact_state(state, viewer)
        assert len(v.active_treaties) == 1


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_with_same_seed_produces_identical_ids():
    def run() -> list[tuple[int, str, str, int, int]]:
        state = _state_with_two_players(seed=91)
        resolve_turn(
            state,
            {
                "alice": [
                    ProposeTreatyAction(
                        recipient="bob", clauses=[_peace(4)]
                    )
                ],
                "bob": [],
            },
        )
        resolve_turn(
            state,
            {
                "alice": [],
                "bob": [
                    RespondToTreatyAction(
                        proposal_id=state.pending_proposals[0].id
                        if state.pending_proposals
                        else 1,
                        accept=True,
                    )
                ],
            },
        )
        return [
            (
                t.id,
                t.parties[0],
                t.parties[1],
                t.turn_ratified,
                len(t.clauses),
            )
            for t in state.active_treaties
        ]

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
async def test_mcp_propose_treaty_returns_action_payload(db_session, mcp):
    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob"], "seed": 61}
    )
    alice_key = data["api_keys"]["alice"]

    out = await _call(
        mcp,
        "propose_treaty",
        {
            "api_key": alice_key,
            "recipient": "bob",
            "clauses": [
                {"clause_type": "peace", "duration_turns": 5},
                {"clause_type": "free_text", "text": "trade freely"},
            ],
        },
    )
    assert "action" in out
    assert out["action"]["type"] == "PROPOSE_TREATY"
    assert out["action"]["recipient"] == "bob"
    assert len(out["action"]["clauses"]) == 2


@pytest.mark.asyncio
async def test_mcp_respond_withdraw_cancel_return_action_payloads(
    db_session, mcp
):
    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob"], "seed": 62}
    )
    alice_key = data["api_keys"]["alice"]
    bob_key = data["api_keys"]["bob"]

    resp = await _call(
        mcp,
        "respond_to_treaty",
        {"api_key": bob_key, "proposal_id": 1, "accept": True},
    )
    assert resp["action"]["type"] == "RESPOND_TO_TREATY"
    assert resp["action"]["proposal_id"] == 1
    assert resp["action"]["accept"] is True

    withdraw = await _call(
        mcp,
        "withdraw_treaty",
        {"api_key": alice_key, "proposal_id": 1},
    )
    assert withdraw["action"]["type"] == "WITHDRAW_TREATY"
    assert withdraw["action"]["proposal_id"] == 1

    cancel = await _call(
        mcp,
        "cancel_treaty",
        {"api_key": alice_key, "treaty_id": 7},
    )
    assert cancel["action"]["type"] == "CANCEL_TREATY"
    assert cancel["action"]["treaty_id"] == 7


@pytest.mark.asyncio
async def test_mcp_get_diplomacy_state_includes_proposals_and_treaties(
    db_session, mcp
):
    from backend.src.database.repository import GameRepository

    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob"], "seed": 64}
    )
    alice_key = data["api_keys"]["alice"]
    game_id = data["game_id"]

    async with async_session_factory() as session:
        repo = GameRepository(session)
        game = await repo.get_game(game_id)
        assert game is not None
        state = GameState.model_validate(game.state)
        record_discovery(state, "alice", "bob")
        record_discovery(state, "bob", "alice")
        execute_propose_treaty(
            state,
            "alice",
            ProposeTreatyAction(
                recipient="bob",
                clauses=[FreeTextClause(text="trade")],
            ),
        )
        await repo.update_game_state(game_id, state)
        await session.commit()

    out = await _call(mcp, "get_diplomacy_state", {"api_key": alice_key})
    assert "pending_proposals" in out
    assert len(out["pending_proposals"]) == 1
    assert out["pending_proposals"][0]["recipient"] == "bob"
    assert "active_treaties" in out
    assert out["active_treaties"] == []
