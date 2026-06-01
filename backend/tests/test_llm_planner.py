"""Unit tests for the LLM planner — parsing robustness and heuristic fallback.

No network: the OpenAI client is replaced with a fake so the tests are
deterministic and offline.
"""

from __future__ import annotations

import sys
import types

import pytest

from backend.src.agents.llm_planner import _extract_action_list, make_llm_planner
from backend.src.agents.profiles import BALANCED


def test_extract_plain_array():
    out = _extract_action_list('[{"type":"FOUND_CITY","worker_id":5}]')
    assert out == [{"type": "FOUND_CITY", "worker_id": 5}]


def test_extract_strips_think_and_prose():
    text = (
        "<think>I should expand.</think>\n"
        "Here is my plan:\n"
        '[{"type":"MOVE","unit_id":1,"to":{"x":2,"y":3}}]\n'
        "Hope that works!"
    )
    assert _extract_action_list(text) == [
        {"type": "MOVE", "unit_id": 1, "to": {"x": 2, "y": 3}}
    ]


def test_extract_drops_items_without_type():
    out = _extract_action_list('[{"type":"MOVE","unit_id":1},{"nope":2}]')
    assert out == [{"type": "MOVE", "unit_id": 1}]


def test_extract_empty_array_is_valid_pass():
    assert _extract_action_list("[]") == []


def test_extract_raises_without_array():
    with pytest.raises(ValueError):
        _extract_action_list("I refuse to answer in JSON.")


def test_extract_raises_on_malformed_json():
    with pytest.raises(Exception):
        _extract_action_list('[{"type":"MOVE", oops}]')


# --- Fake OpenAI client wiring ---------------------------------------------


class _FakeMessage:
    def __init__(self, content, reasoning_content=None):
        msg = types.SimpleNamespace(content=content)
        if reasoning_content is not None:
            msg.reasoning_content = reasoning_content
        self.message = msg


class _FakeCompletions:
    def __init__(self, content=None, raises=None, reasoning_content=None, calls=None):
        self._content = content
        self._raises = raises
        self._reasoning_content = reasoning_content
        self._calls = calls

    async def create(self, **kwargs):
        if self._calls is not None:
            self._calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return types.SimpleNamespace(
            choices=[_FakeMessage(self._content, self._reasoning_content)]
        )


class _FakeAsyncOpenAI:
    """Drop-in for openai.AsyncOpenAI returning a scripted completion."""

    content = None
    raises = None
    reasoning_content = None
    calls: list | None = None

    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(
                self.content, self.raises, self.reasoning_content, type(self).calls
            )
        )


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a fake ``openai`` module so make_llm_planner imports it."""
    fake_mod = types.ModuleType("openai")

    def _factory(content=None, raises=None, reasoning_content=None):
        cls = type(
            "ScriptedAsyncOpenAI",
            (_FakeAsyncOpenAI,),
            {
                "content": content,
                "raises": raises,
                "reasoning_content": reasoning_content,
                "calls": [],
            },
        )
        fake_mod.AsyncOpenAI = cls
        monkeypatch.setitem(sys.modules, "openai", fake_mod)
        return cls

    return _factory


_MIN_STATE = {
    "max_turns": 50,
    "map_width": 20,
    "map_height": 20,
    "units": {"1": {"id": 1, "owner": "p1", "type": "worker", "loc": {"x": 1, "y": 1}}},
    "cities": {},
    "stockpiles": {"p1": {"food": 10, "wood": 10, "ore": 0, "crystal": 0}},
    "tiles": [{"id": 0, "loc": {"x": 1, "y": 1}, "terrain": "grass", "resource": None}],
    "players": ["p1", "p2"],
}


@pytest.mark.asyncio
async def test_planner_returns_parsed_actions(fake_openai):
    fake_openai(content='[{"type":"FOUND_CITY","worker_id":1}]')
    planner = make_llm_planner(base_url="http://x/v1", model="m")
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert out == [{"type": "FOUND_CITY", "worker_id": 1}]


@pytest.mark.asyncio
async def test_planner_falls_back_on_error(fake_openai):
    fake_openai(raises=RuntimeError("model is down"))
    planner = make_llm_planner(base_url="http://x/v1", model="m")
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    # Heuristic fallback returns a list (possibly empty) without raising.
    assert isinstance(out, list)


@pytest.mark.asyncio
async def test_planner_falls_back_on_unparseable(fake_openai):
    fake_openai(content="no json here, sorry")
    planner = make_llm_planner(base_url="http://x/v1", model="m")
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert isinstance(out, list)


# --- Reasoning capture / storage -------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_content_field_is_stored(fake_openai):
    """When the server separates the trace, it is handed to on_reasoning."""
    fake_openai(
        content='[{"type":"FOUND_CITY","worker_id":1}]',
        reasoning_content="Founding here maximises early growth.",
    )
    captured = []
    planner = make_llm_planner(
        base_url="http://x/v1",
        model="m",
        on_reasoning=lambda pid, turn, reasoning, raw, actions: captured.append(
            (pid, turn, reasoning, actions)
        ),
    )
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 7)
    assert out == [{"type": "FOUND_CITY", "worker_id": 1}]
    assert len(captured) == 1
    pid, turn, reasoning, actions = captured[0]
    assert pid == "p1"
    assert turn == 7
    assert reasoning == "Founding here maximises early growth."
    assert actions == [{"type": "FOUND_CITY", "worker_id": 1}]


@pytest.mark.asyncio
async def test_inline_bracket_think_is_extracted(fake_openai):
    """Mistral-style [THINK]...[/THINK] is split out of the content."""
    fake_openai(
        content='[THINK]Scout first.[/THINK][{"type":"MOVE","unit_id":1,"to":{"x":2,"y":1}}]'
    )
    captured = []
    planner = make_llm_planner(
        base_url="http://x/v1",
        model="m",
        on_reasoning=lambda *a: captured.append(a),
    )
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert out == [{"type": "MOVE", "unit_id": 1, "to": {"x": 2, "y": 1}}]
    assert "Scout first." in captured[0][2]


@pytest.mark.asyncio
async def test_reasoning_kept_even_when_unparseable(fake_openai):
    """A parse failure still stores the trace before falling back."""
    fake_openai(content="<think>I'm overthinking this.</think> no array at all")
    captured = []
    planner = make_llm_planner(
        base_url="http://x/v1",
        model="m",
        on_reasoning=lambda *a: captured.append(a),
    )
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert isinstance(out, list)  # heuristic fallback
    assert len(captured) == 1
    assert "overthinking" in captured[0][2]  # reasoning
    assert captured[0][4] == []  # no actions parsed


@pytest.mark.asyncio
async def test_async_reasoning_sink_is_awaited(fake_openai):
    """An async on_reasoning sink (e.g. an MCP write) is awaited, not dropped."""
    fake_openai(
        content='[{"type":"FOUND_CITY","worker_id":1}]',
        reasoning_content="Settle now.",
    )
    captured = []

    async def _sink(pid, turn, reasoning, raw, actions):
        captured.append(reasoning)

    planner = make_llm_planner(base_url="http://x/v1", model="m", on_reasoning=_sink)
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert out == [{"type": "FOUND_CITY", "worker_id": 1}]
    assert captured == ["Settle now."]


@pytest.mark.asyncio
async def test_enable_thinking_passed_to_template(fake_openai):
    """enable_thinking is forwarded via chat_template_kwargs."""
    cls = fake_openai(content="[]")
    planner = make_llm_planner(base_url="http://x/v1", model="m", enable_thinking=True)
    await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert cls.calls, "create() was not called"
    extra_body = cls.calls[-1].get("extra_body", {})
    assert extra_body.get("chat_template_kwargs") == {"enable_thinking": True}
