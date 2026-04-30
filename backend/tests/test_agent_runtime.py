"""
Phase 6 agent-runtime integration tests.

Covers the end-to-end contract for the MCP-only agent: an InProcessMCPClient
is wired to a real FastMCP server, two MCPAgents run the full observe -> ...
-> memorise loop, and we verify turns advance, memory is written, and the
orchestrator stops cleanly at the turn cap. These tests run without an LLM
by design (heuristic planner only) — that is the Phase 6 acceptance bar.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.agents import (
    AGGRESSIVE,
    BALANCED,
    ECONOMIC,
    InProcessMCPClient,
    MCPGameOrchestrator,
    create_game,
    run_agent_turn,
    run_orchestrated_game,
)
from backend.src.agents.planner import plan_actions
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    AgentMemory,
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.mcp_server.server import create_mcp_server


@pytest_asyncio.fixture
async def db_session():
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(
            delete(AgentMemory).where(AgentMemory.game_id.like("game_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("game_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("game_%"))
        )
        await session.execute(delete(GameTurn).where(GameTurn.game_id.like("game_%")))
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


@pytest.fixture
def client(mcp: Any) -> InProcessMCPClient:
    return InProcessMCPClient(mcp)


# ---------------------------------------------------------------------------
# Planner — deterministic, no MCP required
# ---------------------------------------------------------------------------


def test_planner_is_deterministic_for_same_inputs():
    state = {
        "units": {
            "1": {"id": 1, "owner": "alice", "type": "worker", "loc": {"x": 5, "y": 5}},
            "2": {"id": 2, "owner": "alice", "type": "scout", "loc": {"x": 6, "y": 5}},
        },
        "cities": {},
        "tiles": [
            {"loc": {"x": x, "y": y}, "terrain": "grass"}
            for x in range(4, 9)
            for y in range(4, 9)
        ],
        "stockpiles": {"alice": {"food": 50, "wood": 20}},
    }
    first = plan_actions(BALANCED, state, "alice", None, turn=1)
    second = plan_actions(BALANCED, state, "alice", None, turn=1)
    assert first == second


def test_planner_suppresses_attack_below_military_ratio():
    state = {
        "units": {
            "1": {"id": 1, "owner": "alice", "type": "soldier", "loc": {"x": 0, "y": 0}},
            "2": {"id": 2, "owner": "bob", "type": "soldier", "loc": {"x": 1, "y": 0}},
        },
        "cities": {},
        "tiles": [
            {"loc": {"x": x, "y": y}, "terrain": "grass"}
            for x in range(-2, 3)
            for y in range(-2, 3)
        ],
        "stockpiles": {"alice": {}},
    }
    analysis = {
        "evaluate_military_position": {"my_strength": 5, "enemy_strength": 10}
    }
    actions = plan_actions(AGGRESSIVE, state, "alice", analysis, turn=0)
    assert all(a["type"] != "ATTACK" for a in actions)


# ---------------------------------------------------------------------------
# MCPClient / MCPAgent — one-shot turn against real server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_process_client_routes_calls(db_session, client):
    game = await create_game(client, ["alice", "bob"], max_turns=20)
    assert game.game_id.startswith("game_")
    assert set(game.api_keys) == {"alice", "bob"}


@pytest.mark.asyncio
async def test_agent_single_turn_produces_trace(db_session, client):
    game = await create_game(client, ["alice", "bob"], max_turns=20)
    trace = await run_agent_turn(
        client, api_key=game.api_keys["alice"], profile=BALANCED
    )

    assert trace.profile_name == "balanced"
    assert trace.player_id == "alice"
    assert not trace.skipped
    assert trace.tool_calls  # at minimum is_my_turn + get_game_state
    assert "submit_actions" in {name for name, _ in trace.tool_calls}
    # Memory writes should have fired for each configured priority.
    assert set(trace.memory_writes) <= {"strategic_goals", "opponent_models", "turn_notes"}
    assert "strategic_goals" in trace.memory_writes
    # No errors from any tool call.
    assert trace.errors == []


@pytest.mark.asyncio
async def test_agent_skips_when_not_its_turn(db_session, client):
    game = await create_game(client, ["alice", "bob"], max_turns=20)
    # Alice submits first, turn still pending on Bob.
    await client.call_tool(
        "submit_actions",
        {"api_key": game.api_keys["alice"], "actions": []},
    )
    # Alice should now be "done" for this turn.
    trace = await run_agent_turn(
        client, api_key=game.api_keys["alice"], profile=BALANCED
    )
    assert trace.skipped is True


# ---------------------------------------------------------------------------
# Orchestrator — 10-turn self-play game (Phase 6 acceptance criterion)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_agents_play_ten_turns(db_session, client):
    game = await create_game(client, ["alice", "bob"], max_turns=50, seed=17)
    orch = MCPGameOrchestrator(
        client,
        game,
        profiles={"alice": AGGRESSIVE, "bob": ECONOMIC},
    )

    result = await orch.run(max_turn_cap=10)

    assert result.game_id == game.game_id
    assert result.status in {"active", "ended"}
    # Each turn invokes both players -> 20 traces at the cap.
    assert len(result.traces) >= 10
    # No traces should carry errors.
    error_summary = [(t.player_id, t.errors) for t in result.traces if t.errors]
    assert error_summary == [], f"Agents raised tool errors: {error_summary}"
    # Either we hit the cap or the game ended on its own — both are fine.
    assert result.hit_turn_cap or result.status == "ended"


@pytest.mark.asyncio
async def test_orchestrator_helper_wires_profiles(db_session, client):
    result = await run_orchestrated_game(
        client,
        ["alice", "bob"],
        personalities={"alice": "aggressive", "bob": "economic"},
        seed=3,
        max_turns=20,
        max_turn_cap=3,
    )
    profile_names = {t.profile_name for t in result.traces}
    assert profile_names == {"aggressive", "economic"}
    assert result.final_turn >= 1
