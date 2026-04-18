"""Tests for Diplomacy Phase 2: private bilateral messaging.

Covers acceptance criteria from ``plans/diplomacy-plan.md`` Phase 2:

* deterministic message id counter on ``GameState`` and per-turn rate limiting;
* ``SEND_MESSAGE`` action: undiscovered/self/body-length/per-turn-limit rejection
  and successful delivery;
* delivery semantics: messages sent on turn N carry ``turn_sent=N`` and are
  observable to the recipient at turn N+1;
* ``redact_state`` strictly filters messages to sender and recipient only
  (third parties see neither content nor existence);
* MCP ``send_message`` + ``get_messages`` and REST ``/diplomacy/messages``
  parity; submission still routes through ``submit_actions``.
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
    MESSAGE_BODY_MAX_LENGTH,
    MESSAGES_PER_TURN_LIMIT,
    GameState,
    SendMessageAction,
)
from backend.src.game.rules import (
    execute_send_message,
    generate_map,
    place_starting_units,
    record_discovery,
    redact_state,
    resolve_turn,
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
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    return state


# ---------------------------------------------------------------------------
# GameState defaults
# ---------------------------------------------------------------------------


def test_game_state_has_message_fields_with_defaults():
    state = _fresh_state()
    assert state.next_message_id == 1
    assert state.messages == []


# ---------------------------------------------------------------------------
# execute_send_message validation and success paths
# ---------------------------------------------------------------------------


def test_send_message_rejects_self():
    state = _state_with_two_players()
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="alice", body="hi")
    )
    assert result.success is False
    assert "yourself" in result.message
    assert state.messages == []


def test_send_message_rejects_missing_player():
    state = _state_with_two_players()
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="ghost", body="hi")
    )
    assert result.success is False
    assert "not in this game" in result.message


def test_send_message_rejects_undiscovered_recipient():
    state = _state_with_two_players()
    state.discovered = {}  # clear discovery so bob is "undiscovered" to alice
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="hi")
    )
    assert result.success is False
    assert "undiscovered" in result.message
    assert state.messages == []


def test_send_message_rejects_empty_body():
    state = _state_with_two_players()
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="")
    )
    assert result.success is False
    assert "empty" in result.message


def test_send_message_rejects_over_length():
    state = _state_with_two_players()
    body = "x" * (MESSAGE_BODY_MAX_LENGTH + 1)
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body=body)
    )
    assert result.success is False
    assert str(MESSAGE_BODY_MAX_LENGTH) in result.message
    assert state.messages == []


def test_send_message_enforces_per_turn_limit():
    state = _state_with_two_players()
    for i in range(MESSAGES_PER_TURN_LIMIT):
        result = execute_send_message(
            state, "alice", SendMessageAction(recipient="bob", body=f"#{i}")
        )
        assert result.success is True
    # The 6th message in the same turn is rejected.
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="over")
    )
    assert result.success is False
    assert "limit" in result.message
    assert len(state.messages) == MESSAGES_PER_TURN_LIMIT


def test_per_turn_limit_resets_on_new_turn():
    state = _state_with_two_players()
    for i in range(MESSAGES_PER_TURN_LIMIT):
        execute_send_message(
            state, "alice", SendMessageAction(recipient="bob", body=f"#{i}")
        )
    # Advance the turn manually and send again — limit should have reset.
    state.turn += 1
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="next turn")
    )
    assert result.success is True
    assert len(state.messages) == MESSAGES_PER_TURN_LIMIT + 1


def test_send_message_assigns_deterministic_ids():
    state = _state_with_two_players()
    state.turn = 2
    r1 = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="hello")
    )
    r2 = execute_send_message(
        state, "bob", SendMessageAction(recipient="alice", body="hi")
    )
    assert r1.success and r2.success
    assert state.messages[0].id == 1
    assert state.messages[1].id == 2
    assert state.next_message_id == 3
    assert state.messages[0].turn_sent == 2
    assert state.messages[0].sender == "alice"
    assert state.messages[0].recipient == "bob"
    assert state.messages[0].body == "hello"


def test_send_message_at_exact_length_limit():
    state = _state_with_two_players()
    body = "x" * MESSAGE_BODY_MAX_LENGTH
    result = execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body=body)
    )
    assert result.success is True
    assert len(state.messages[0].body) == MESSAGE_BODY_MAX_LENGTH


# ---------------------------------------------------------------------------
# Delivery: turn-N message visible to recipient at turn N+1
# ---------------------------------------------------------------------------


def test_message_delivered_at_turn_resolution():
    state = _state_with_two_players()
    assert state.turn == 0

    resolve_turn(
        state,
        {
            "alice": [SendMessageAction(recipient="bob", body="hello bob")],
            "bob": [],
        },
    )
    # After resolve_turn, state.turn == 1 and the message carries turn_sent=0.
    assert state.turn == 1
    assert len(state.messages) == 1
    assert state.messages[0].turn_sent == 0

    # From bob's perspective at turn 1, he sees alice's message in his inbox.
    bob_view = redact_state(state, "bob")
    assert len(bob_view.messages) == 1
    assert bob_view.messages[0].sender == "alice"
    assert bob_view.messages[0].body == "hello bob"


# ---------------------------------------------------------------------------
# Redaction: private to sender and recipient only
# ---------------------------------------------------------------------------


def test_third_party_cannot_see_messages():
    state = _fresh_state(players=["alice", "bob", "carol"], seed=3)
    record_discovery(state, "alice", "bob")
    record_discovery(state, "bob", "alice")
    record_discovery(state, "carol", "alice")
    record_discovery(state, "carol", "bob")
    record_discovery(state, "alice", "carol")
    record_discovery(state, "bob", "carol")

    execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="secret")
    )

    alice_view = redact_state(state, "alice")
    bob_view = redact_state(state, "bob")
    carol_view = redact_state(state, "carol")

    assert len(alice_view.messages) == 1
    assert len(bob_view.messages) == 1
    assert carol_view.messages == []


def test_no_message_sent_event_in_public_feed():
    """Phase 2: sending a message must NOT add a public MESSAGE_SENT event."""
    state = _state_with_two_players()
    events_before = len(state.diplomatic_events)
    execute_send_message(
        state, "alice", SendMessageAction(recipient="bob", body="ping")
    )
    assert len(state.diplomatic_events) == events_before


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_with_same_seed_and_messages_produces_identical_ids():
    def run() -> list[tuple[int, str, str, str, int]]:
        state = _state_with_two_players(seed=77)
        actions = {
            "alice": [
                SendMessageAction(recipient="bob", body="hi"),
                SendMessageAction(recipient="bob", body="again"),
            ],
            "bob": [
                SendMessageAction(recipient="alice", body="yo"),
            ],
        }
        resolve_turn(state, actions)
        return [
            (m.id, m.sender, m.recipient, m.body, m.turn_sent)
            for m in state.messages
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
async def test_mcp_send_message_returns_action_payload(db_session, mcp):
    data = await _call(mcp, "create_game", {"players": ["alice", "bob"], "seed": 41})
    alice_key = data["api_keys"]["alice"]

    out = await _call(
        mcp,
        "send_message",
        {"api_key": alice_key, "recipient": "bob", "body": "hello bob"},
    )
    assert "action" in out
    assert out["action"]["type"] == "SEND_MESSAGE"
    assert out["action"]["recipient"] == "bob"
    assert out["action"]["body"] == "hello bob"


@pytest.mark.asyncio
async def test_mcp_get_messages_initially_empty(db_session, mcp):
    data = await _call(mcp, "create_game", {"players": ["alice", "bob"], "seed": 42})
    alice_key = data["api_keys"]["alice"]

    out = await _call(mcp, "get_messages", {"api_key": alice_key})
    assert out["messages"] == []


@pytest.mark.asyncio
async def test_mcp_get_messages_filters_by_counterparty_and_since_turn(
    db_session, mcp
):
    from backend.src.database.repository import GameRepository
    from backend.src.game.models import Message

    data = await _call(
        mcp,
        "create_game",
        {"players": ["alice", "bob", "carol"], "seed": 44},
    )
    alice_key = data["api_keys"]["alice"]
    game_id = data["game_id"]

    # Seed messages + discovery directly. The MCP `get_messages` filter logic
    # is independent of delivery; Phase 2 rules-level tests already cover the
    # end-to-end action -> resolve_turn -> state.messages path.
    async with async_session_factory() as session:
        repo = GameRepository(session)
        game = await repo.get_game(game_id)
        assert game is not None
        state = GameState.model_validate(game.state)
        record_discovery(state, "alice", "bob")
        record_discovery(state, "alice", "carol")
        state.messages = [
            Message(id=1, sender="alice", recipient="bob", body="hi bob", turn_sent=0),
            Message(id=2, sender="bob", recipient="alice", body="hi alice", turn_sent=0),
            Message(id=3, sender="carol", recipient="alice", body="hey", turn_sent=2),
        ]
        state.next_message_id = 4
        await repo.update_game_state(game_id, state)
        await session.commit()

    # Alice sees all three (all involve her).
    out = await _call(mcp, "get_messages", {"api_key": alice_key})
    assert len(out["messages"]) == 3

    # counterparty=bob restricts to the alice<->bob pair.
    out_filtered = await _call(
        mcp,
        "get_messages",
        {"api_key": alice_key, "counterparty": "bob"},
    )
    assert len(out_filtered["messages"]) == 2
    assert all(
        m["sender"] == "bob" or m["recipient"] == "bob"
        for m in out_filtered["messages"]
    )

    # since_turn=1 drops the two turn-0 messages, keeping carol's turn-2 note.
    out_since = await _call(
        mcp, "get_messages", {"api_key": alice_key, "since_turn": 1}
    )
    assert len(out_since["messages"]) == 1
    assert out_since["messages"][0]["turn_sent"] == 2


@pytest.mark.asyncio
async def test_mcp_submit_actions_validates_send_message_undiscovered(
    db_session, mcp
):
    # Create a 3-player game; alice has not discovered carol.
    data = await _call(
        mcp, "create_game", {"players": ["alice", "bob", "carol"], "seed": 51}
    )
    alice_key = data["api_keys"]["alice"]

    msg = await _call(
        mcp,
        "send_message",
        {"api_key": alice_key, "recipient": "carol", "body": "hi carol"},
    )
    submit = await _call(
        mcp,
        "submit_actions",
        {"api_key": alice_key, "actions": [msg["action"]]},
    )
    # Undiscovered recipient is rejected at submit time.
    assert "error" in submit
    assert "validation" in submit
    invalid = [v for v in submit["validation"] if not v["valid"]]
    assert invalid and "undiscovered" in invalid[0]["message"]
