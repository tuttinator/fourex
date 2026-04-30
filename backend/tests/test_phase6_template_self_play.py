"""Phase 6 — per-template self-play smoke tests.

Drives the deterministic planner through a short self-play game on each
parametric template (``random``, ``continent``, ``islands``, ``river``,
``lakes``, ``archipelago``) plus a fixture saved map. The contract is
the same for every template: the engine never produces an inconsistent
state, no tool call returns an error, and at least one turn resolves.

These are smoke tests, not balance tests. The bar is "the planner can
play a few turns on each map shape without hitting an invalid action or
deadlocking" — enough to catch regressions where a template starves
profiles of viable resource tiles or mis-shapes the spawn pool.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.agents import (
    InProcessMCPClient,
    SelfPlayResult,
    format_failure_report,
    run_self_play,
)
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    AgentMemory,
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    SavedMap,
    TurnAction,
    TurnSnapshot,
)
from backend.src.database.repository import GameRepository
from backend.src.game.rules import MAP_TEMPLATES
from backend.src.mcp_server.server import create_mcp_server

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        for model in (
            AgentMemory,
            TurnAction,
            TurnSnapshot,
            GameTurn,
            PlayerApiKey,
            GameSnapshot,
        ):
            await session.execute(delete(model).where(model.game_id.like("game_%")))
        await session.execute(delete(Game).where(Game.id.like("game_%")))
        # Saved-map fixtures created by the saved-map smoke test.
        await session.execute(delete(SavedMap).where(SavedMap.name.like("phase6-%")))
        await session.commit()


@pytest.fixture
def mcp() -> Any:
    return create_mcp_server()


@pytest.fixture
def client(mcp: Any) -> InProcessMCPClient:
    return InProcessMCPClient(mcp)


# ---------------------------------------------------------------------------
# Per-template smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", MAP_TEMPLATES)
@pytest.mark.asyncio
async def test_self_play_runs_to_completion_on_each_template(
    db_session, client, template: str
) -> None:
    """One bounded self-play game per parametric template.

    The map is sized large enough to guarantee spawn-zone spacing on
    every template (archipelago needs water budget; islands needs one
    island per player). Two players keep the per-test runtime reasonable
    while still exercising spawn-zone selection.
    """
    result: SelfPlayResult = await run_self_play(
        client,
        ["alice", "bob"],
        profiles={"alice": "balanced", "bob": "balanced"},
        seed=2026,
        max_turns=30,
        max_turn_cap=4,
        map_width=14,
        map_height=14,
        map_template=template,
    )

    assert result.ok, format_failure_report(result)
    assert result.consistency_errors == []
    assert result.final_turn >= 1
    # Every turn that ran must have submitted at least one action log
    # entry; if the planner deadlocked we'd see an empty log.
    assert len(result.action_log) >= 2


# ---------------------------------------------------------------------------
# Saved-map fixture smoke test
# ---------------------------------------------------------------------------


def _fixture_saved_map_payload() -> dict[str, Any]:
    """A minimal but valid saved-map payload.

    12x12 grass field with hills strips for variety, two spawn zones
    placed far enough apart that the engine's min-distance assertion
    passes for a 2-player game.
    """
    width, height = 12, 12
    tiles: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            # Strip of hills along y=5..6 to give the planner ore tiles.
            terrain = "hills" if 5 <= y <= 6 else "grass"
            tiles.append({"x": x, "y": y, "terrain": terrain})
    return {
        "name": "phase6-fixture",
        "description": "Phase 6 self-play fixture",
        "width": width,
        "height": height,
        "tiles": tiles,
        "spawn_zones": [
            {"x": 2, "y": 2},
            {"x": 9, "y": 9},
        ],
    }


@pytest.mark.asyncio
async def test_self_play_runs_on_saved_map_fixture(db_session, client) -> None:
    """Exercise the ``saved:<id>`` resolver path with a real game."""
    payload = _fixture_saved_map_payload()
    async with async_session_factory() as session:
        repo = GameRepository(session)
        saved = await repo.create_saved_map(
            name=payload["name"],
            description=payload["description"],
            width=payload["width"],
            height=payload["height"],
            tiles=payload["tiles"],
            spawn_zones=payload["spawn_zones"],
            created_by=None,
        )
        await session.commit()
        saved_map_id = saved.id

    result = await run_self_play(
        client,
        ["alice", "bob"],
        profiles={"alice": "balanced", "bob": "balanced"},
        seed=4242,
        max_turns=30,
        max_turn_cap=4,
        # Width/height are overridden by the saved map; values here are
        # ignored by the resolver but kept for the orchestrator's API.
        map_width=payload["width"],
        map_height=payload["height"],
        map_template=f"saved:{saved_map_id}",
    )

    assert result.ok, format_failure_report(result)
    assert result.consistency_errors == []
    assert result.final_turn >= 1
    assert len(result.action_log) >= 2
