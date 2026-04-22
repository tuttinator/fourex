"""Phase 6 spectated-agents: per-agent telemetry + context compaction.

Covers the Phase 6 acceptance criteria in ``plans/spectated-agents.md``:

- Token counting uses tiktoken for OpenAI-compatible providers and a
  ``len(text) / 4`` heuristic elsewhere.
- Per-provider context windows are configurable via env vars with
  documented defaults.
- A JSONL telemetry file is written per game with one row per agent
  per turn.
- Rows carry provider, model, prompt_tokens, completion_tokens,
  thinking_tokens, scratchpad_reads, scratchpad_writes, wall_ms,
  action_count.
- Compaction fires when the running estimate crosses 70% of the
  configured window.
- The oldest-half entries are summarised via the supplied async
  summariser and replaced in the history by the summary entry; the
  summary is also appended to the scratchpad under a
  ``[compacted_turns]`` block with the turn range.
- The scratchpad is never truncated by compaction — prior notes
  survive.
- An agent continues producing valid turns after a compaction event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.agents import (
    BALANCED,
    CompactionEvent,
    ContextWindowConfig,
    InProcessMCPClient,
    MCPGameOrchestrator,
    TelemetryConfig,
    TelemetryRecord,
    TelemetryWriter,
    TurnHistory,
    create_game,
    make_token_counter,
    run_agent_turn,
)
from backend.src.agents.telemetry import (
    DEFAULT_CONTEXT_WINDOWS,
    HeuristicCounter,
    SCRATCHPAD_HEADER,
    SCRATCHPAD_MAX_CHARS,
    TiktokenCounter,
    count_messages_tokens,
    format_compaction_append,
)
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
        await session.commit()


@pytest.fixture
def client() -> InProcessMCPClient:
    return InProcessMCPClient(create_mcp_server())


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def test_heuristic_counter_rounds_up():
    counter = HeuristicCounter()
    assert counter.count("") == 0
    # 5 chars -> ceil(5/4) == 2 tokens
    assert counter.count("hello") == 2
    # 12 chars -> 3 tokens exactly
    assert counter.count("hello world!") == 3


def test_make_token_counter_picks_tiktoken_for_openai():
    counter = make_token_counter("openai")
    assert isinstance(counter, TiktokenCounter)


def test_make_token_counter_falls_back_for_non_openai():
    counter = make_token_counter("llm_studio")
    assert isinstance(counter, HeuristicCounter)


def test_count_messages_tokens_sums_content_strings():
    counter = HeuristicCounter()
    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "efgh"},
        {"role": "assistant", "content": [{"type": "text", "text": "ijkl"}]},
    ]
    # 4 chars each -> 1 token each -> 3 tokens total
    assert count_messages_tokens(messages, counter) == 3


# ---------------------------------------------------------------------------
# Context window config
# ---------------------------------------------------------------------------


def test_context_window_config_defaults_match_documented():
    cfg = ContextWindowConfig()
    assert cfg.window_for("openai") == DEFAULT_CONTEXT_WINDOWS["openai"]
    assert cfg.window_for("llm_studio") == DEFAULT_CONTEXT_WINDOWS["llm_studio"]


def test_context_window_config_env_override():
    cfg = ContextWindowConfig.from_env(
        {
            "OPENAI_CONTEXT_WINDOW": "200000",
            "LLM_STUDIO_CONTEXT_WINDOW": "16000",
            "AGENT_COMPACTION_THRESHOLD_RATIO": "0.5",
        }
    )
    assert cfg.window_for("openai") == 200_000
    assert cfg.window_for("llm_studio") == 16_000
    assert cfg.threshold_ratio == 0.5
    # Threshold = window * ratio.
    assert cfg.threshold_tokens("openai") == 100_000


# ---------------------------------------------------------------------------
# Telemetry record + writer
# ---------------------------------------------------------------------------


def test_telemetry_writer_appends_jsonl(tmp_path: Path):
    writer = TelemetryWriter(game_id="game_demo", base_dir=tmp_path)
    writer.write(
        TelemetryRecord(
            game_id="game_demo",
            player_id="alice",
            turn=1,
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=20,
            thinking_tokens=5,
            scratchpad_reads=3,
            scratchpad_writes=2,
            wall_ms=450,
            action_count=4,
        )
    )
    writer.write(
        TelemetryRecord(
            game_id="game_demo",
            player_id="bob",
            turn=1,
            provider="llm_studio",
            model="qwen3",
            prompt_tokens=80,
        )
    )
    writer.close()

    path = tmp_path / "game_game_demo.jsonl"
    assert path.exists()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["player_id"] == "alice"
    assert rows[0]["action_count"] == 4
    assert rows[0]["scratchpad_reads"] == 3
    assert rows[0]["scratchpad_writes"] == 2
    assert rows[1]["provider"] == "llm_studio"


# ---------------------------------------------------------------------------
# TurnHistory compaction
# ---------------------------------------------------------------------------


def _aggressive_config() -> ContextWindowConfig:
    """Tiny window so compaction fires on modest text."""
    return ContextWindowConfig(
        windows={"llm_studio": 100, "openai": 100, "openai_compatible": 100},
        threshold_ratio=0.7,
    )


@pytest.mark.asyncio
async def test_turn_history_compacts_oldest_half_via_summariser():
    history = TurnHistory(provider="llm_studio", config=_aggressive_config())
    for turn in range(1, 9):
        history.append(turn, "Units: 2; Cities: 1 | Actions: MOVE, FOUND_CITY")
    assert history.should_compact() is True

    captured: dict[str, Any] = {}

    async def summariser(joined: str, first: int, last: int) -> str:
        captured["joined"] = joined
        captured["range"] = (first, last)
        return f"early game ({first}-{last}): explored + founded capital"

    event = await history.compact(summariser)
    assert isinstance(event, CompactionEvent)
    assert event.first_turn == 1
    assert event.last_turn <= 8
    assert event.replaced_entries >= 2
    assert "explored" in event.summary
    # The oldest entries were replaced by one summary entry.
    entries = history.entries
    assert entries[0].text.startswith("[compacted ")
    assert all(e.turn for e in entries[1:])


@pytest.mark.asyncio
async def test_turn_history_no_compaction_below_threshold():
    history = TurnHistory(provider="llm_studio")
    for turn in range(1, 4):
        history.append(turn, "tiny")
    assert history.should_compact() is False

    async def summariser(joined: str, first: int, last: int) -> str:
        return "should not run"

    result = await history.compact(summariser)
    assert result is None
    # History still has all 3 entries intact.
    assert [e.turn for e in history.entries] == [1, 2, 3]


def test_format_compaction_append_preserves_existing_notes():
    event = CompactionEvent(
        first_turn=1, last_turn=5, summary="founded capital and explored", replaced_entries=5
    )
    existing = "player notes from an earlier turn"
    out = format_compaction_append(existing, event)
    assert existing in out
    assert SCRATCHPAD_HEADER in out
    assert "turns 1-5" in out
    assert "founded capital" in out


def test_format_compaction_append_never_truncates_summary():
    """If scratchpad would overflow, older notes drop — the compaction
    block always survives."""
    event = CompactionEvent(
        first_turn=1, last_turn=5, summary="S" * 200, replaced_entries=5
    )
    # Make the existing body larger than the limit so the new scratchpad
    # overflows and we have to drop the head.
    existing = "A" * (SCRATCHPAD_MAX_CHARS - 50)
    out = format_compaction_append(existing, event)
    assert len(out) <= SCRATCHPAD_MAX_CHARS
    # The compaction block ends the string; the last 200 'S' chars are present.
    assert out.endswith("S" * 200)


# ---------------------------------------------------------------------------
# End-to-end: MCPAgent emits telemetry and writes a JSONL row per turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_turn_emits_telemetry_row(
    db_session, client, tmp_path: Path
):
    game = await create_game(client, ["alice", "bob"], max_turns=20, seed=7)
    writer = TelemetryWriter(game_id=game.game_id, base_dir=tmp_path)
    telemetry = TelemetryConfig(
        writer=writer,
        provider="llm_studio",
        model="qwen3-test",
        game_id=game.game_id,
    )
    trace = await run_agent_turn(
        client,
        api_key=game.api_keys["alice"],
        profile=BALANCED,
        telemetry=telemetry,
    )
    writer.close()

    assert trace.telemetry is not None
    assert trace.telemetry.provider == "llm_studio"
    assert trace.telemetry.model == "qwen3-test"
    assert trace.telemetry.action_count == len(trace.submitted_actions)
    # At least the three structured-memory writes happened this turn.
    assert trace.telemetry.scratchpad_writes >= 1
    # Wall-time is non-negative; we don't pin a lower bound to keep CI calm.
    assert trace.telemetry.wall_ms >= 0

    # File exists with one JSONL row matching the trace.
    rows = [
        json.loads(line) for line in writer.path.read_text().splitlines() if line.strip()
    ]
    assert len(rows) == 1
    row = rows[0]
    expected_fields = {
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "thinking_tokens",
        "scratchpad_reads",
        "scratchpad_writes",
        "wall_ms",
        "action_count",
    }
    assert expected_fields <= set(row.keys())


# ---------------------------------------------------------------------------
# End-to-end: compaction fires in a real game and agent keeps playing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_fires_and_summary_lands_in_scratchpad(
    db_session, client, tmp_path: Path
):
    game = await create_game(client, ["alice", "bob"], max_turns=30, seed=11)

    summarised_ranges: list[tuple[int, int]] = []

    async def summariser(joined: str, first: int, last: int) -> str:
        summarised_ranges.append((first, last))
        return f"compacted-summary-for-turns-{first}-to-{last}"

    # Aggressive window so compaction triggers after only a few turns.
    aggressive = ContextWindowConfig(
        windows={
            p: 40 for p in ("llm_studio", "openai", "openai_compatible", "heuristic")
        },
        threshold_ratio=0.7,
    )
    alice_writer = TelemetryWriter(game_id=game.game_id, base_dir=tmp_path / "alice")
    bob_writer = TelemetryWriter(game_id=game.game_id, base_dir=tmp_path / "bob")
    orch = MCPGameOrchestrator(
        client,
        game,
        profiles={p: BALANCED for p in game.players},
        telemetry={
            "alice": TelemetryConfig(
                writer=alice_writer,
                provider="heuristic",
                model="tiny",
                context=aggressive,
                summariser=summariser,
                game_id=game.game_id,
            ),
            "bob": TelemetryConfig(
                writer=bob_writer,
                provider="heuristic",
                model="tiny",
                context=aggressive,
                summariser=summariser,
                game_id=game.game_id,
            ),
        },
    )
    # Cap short; compaction should fire inside this window given the
    # tiny 40-token threshold.
    result = await orch.run(max_turn_cap=12)
    alice_writer.close()
    bob_writer.close()

    # At least one compaction fired.
    assert summarised_ranges, "expected at least one compaction"

    # The scratchpad is per-turn; compaction may have happened on an
    # earlier turn. Walk every turn written so far to find at least one
    # ``[compacted_turns]`` block — that's the Phase 6 contract.
    combined = ""
    for turn in range(0, result.final_turn + 1):
        entry = await client.call_tool(
            "read_scratchpad",
            {"api_key": game.api_keys["alice"], "turn_number": turn},
        )
        if isinstance(entry, dict) and entry.get("text"):
            combined += f"\n{entry['text']}"
    assert SCRATCHPAD_HEADER in combined, (
        "expected a [compacted_turns] block somewhere in Alice's scratchpad"
    )

    # Agent kept producing turns after the compaction (status == ended
    # or we simply reached the cap without any errors).
    assert result.status in {"active", "ended"}

    # Telemetry file has multiple rows with a ``compacted=true`` marker.
    rows = [
        json.loads(line)
        for line in alice_writer.path.read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) > 1
    assert any(r.get("compacted") for r in rows)
    # Turns after the first compaction still produced non-error rows.
    first_compaction = next(i for i, r in enumerate(rows) if r.get("compacted"))
    later = rows[first_compaction + 1 :]
    assert later, "expected the agent to keep playing after compaction"
    for r in later:
        assert r["provider"] == "heuristic"
        assert r["action_count"] >= 0
