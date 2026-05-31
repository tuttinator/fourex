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
    def __init__(self, content):
        self.message = types.SimpleNamespace(content=content)


class _FakeCompletions:
    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises

    async def create(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        return types.SimpleNamespace(choices=[_FakeMessage(self._content)])


class _FakeAsyncOpenAI:
    """Drop-in for openai.AsyncOpenAI returning a scripted completion."""

    content = None
    raises = None

    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(self.content, self.raises)
        )


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a fake ``openai`` module so make_llm_planner imports it."""
    fake_mod = types.ModuleType("openai")

    def _factory(content=None, raises=None):
        cls = type(
            "ScriptedAsyncOpenAI",
            (_FakeAsyncOpenAI,),
            {"content": content, "raises": raises},
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
