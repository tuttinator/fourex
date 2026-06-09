"""Unit tests for active in-game chat dispatch in the agent runtime.

A minimal fake MCP client records tool calls so we can assert that SEND_MESSAGE
planner actions are routed to the ``send_message`` tool (and split out of the
game-action submission), only when chat is enabled.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.src.agents.agent_runtime import MCPAgent
from backend.src.agents.profiles import BALANCED


class _FakeClient:
    """Records call_tool invocations and returns canned per-tool responses."""

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "is_my_turn":
            return {"turn": 1, "waiting_for_you": True}
        if name == "get_game_state":
            return {"player": "p1", "state": {"units": {}, "cities": {}}}
        if name == "get_messages":
            return {"messages": [{"sender": "p2", "body": "ally?", "turn_sent": 0}]}
        if name == "validate_actions":
            actions = arguments.get("actions") or []
            return {"results": [{"valid": True} for _ in actions]}
        return {"ok": True}

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def args_for(self, name: str) -> dict[str, Any]:
        for n, a in self.calls:
            if n == name:
                return a
        return {}


def _planner_with_chat(profile, state, player_id, analysis, turn_number):
    return [
        {"type": "FOUND_CITY", "worker_id": 1},
        {"type": "SEND_MESSAGE", "recipient": "p2", "body": "Let's team up."},
    ]


@pytest.mark.asyncio
async def test_chat_enabled_dispatches_message_and_splits_actions():
    client = _FakeClient()
    agent = MCPAgent(
        client,
        api_key="k",
        profile=BALANCED,
        player_id="p1",
        planner=_planner_with_chat,
        chat_enabled=True,
    )
    trace = await agent.play_turn()

    # Inbound messages were read before planning.
    assert "get_messages" in client.names()
    # The SEND_MESSAGE was dispatched to the diplomacy tool with the right args.
    assert "send_message" in client.names()
    sent = client.args_for("send_message")
    assert sent["recipient"] == "p2"
    assert sent["body"] == "Let's team up."
    # Only the game action was submitted — the chat action was split out.
    submitted = client.args_for("submit_actions")["actions"]
    assert submitted == [{"type": "FOUND_CITY", "worker_id": 1}]
    assert trace.chat_actions == [
        {"type": "SEND_MESSAGE", "recipient": "p2", "body": "Let's team up."}
    ]


def _make_recording_planner(captured: list[dict[str, Any]]):
    """A planner that records the analysis/context dict it is handed each turn."""

    def _p(profile, state, player_id, analysis, turn_number):
        captured.append(analysis)
        return [{"type": "FOUND_CITY", "worker_id": 1}]

    return _p


@pytest.mark.asyncio
async def test_recent_turns_and_memory_fed_to_planner():
    """The planner receives the agent's own recent-move history (accumulated
    across turns) and the memory it read — the cross-turn continuity fix."""
    client = _FakeClient()
    captured: list[dict[str, Any]] = []
    agent = MCPAgent(
        client,
        api_key="k",
        profile=BALANCED,
        player_id="p1",
        planner=_make_recording_planner(captured),
        chat_enabled=False,
    )
    await agent.play_turn()
    await agent.play_turn()

    # First turn: no prior history yet.
    assert "_recent_turns" not in captured[0]
    # Second turn: the planner sees turn 1's actions and the memory read.
    assert captured[1]["_recent_turns"][-1]["actions"] == ["FOUND_CITY"]
    assert "_memory" in captured[1]


@pytest.mark.asyncio
async def test_chat_disabled_does_not_send_or_read_messages():
    client = _FakeClient()
    agent = MCPAgent(
        client,
        api_key="k",
        profile=BALANCED,
        player_id="p1",
        planner=_planner_with_chat,
        chat_enabled=False,
    )
    await agent.play_turn()

    # No inbound read, no send — the A/B baseline.
    assert "get_messages" not in client.names()
    assert "send_message" not in client.names()
    # A stray SEND_MESSAGE is still kept out of the game-action submission.
    submitted = client.args_for("submit_actions")["actions"]
    assert submitted == [{"type": "FOUND_CITY", "worker_id": 1}]
