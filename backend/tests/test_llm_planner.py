"""Unit tests for the LLM planner — parsing robustness and heuristic fallback.

No network: the OpenAI client is replaced with a fake so the tests are
deterministic and offline.
"""

from __future__ import annotations

import sys
import types

import pytest

from backend.src.agents.llm_planner import (
    _extract_action_list,
    _message_reasoning,
    make_llm_planner,
)
from backend.src.agents.profiles import BALANCED


def test_message_reasoning_field_names():
    # vLLM 0.20.1 uses `reasoning`; OpenAI o1 style uses `reasoning_content`.
    assert _message_reasoning(types.SimpleNamespace(reasoning="trace A")) == "trace A"
    assert (
        _message_reasoning(types.SimpleNamespace(reasoning_content="trace B"))
        == "trace B"
    )
    # model_extra fallback (SDK stashes unknown fields there).
    msg = types.SimpleNamespace(model_extra={"reasoning": "trace C"})
    assert _message_reasoning(msg) == "trace C"
    # Nothing present -> None.
    assert _message_reasoning(types.SimpleNamespace(content="[]")) is None
    assert _message_reasoning(None) is None


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


def test_extract_last_array_after_reasoning_prose():
    # Reasoning prose (with a stray bracket pair) precedes the final answer.
    text = (
        "I should secure the tile at [5,3] first, then settle my capital.\n"
        '[{"type":"FOUND_CITY","worker_id":1}]'
    )
    assert _extract_action_list(text) == [{"type": "FOUND_CITY", "worker_id": 1}]


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
    def __init__(
        self,
        content=None,
        raises=None,
        reasoning_content=None,
        calls=None,
        template_400=False,
        responses=None,
    ):
        self._content = content
        self._raises = raises
        self._reasoning_content = reasoning_content
        self._calls = calls
        self._template_400 = template_400
        # Optional per-call script: a list of {content, reasoning_content} dicts
        # consumed in order (the last entry repeats). Lets a test drive the
        # forced-answer continuation (call 1 reasons with no array, call 2 emits
        # the action). Takes precedence over the single `content`.
        self._responses = responses
        self._call_index = 0

    async def create(self, **kwargs):
        if self._calls is not None:
            self._calls.append(kwargs)
        # Simulate a Mistral-tokenizer server: reject any chat_template kwargs.
        if self._template_400 and (kwargs.get("extra_body") or {}).get(
            "chat_template_kwargs"
        ):
            raise RuntimeError(
                "Error code: 400 - chat_template is not supported for Mistral tokenizers."
            )
        if self._raises is not None:
            raise self._raises
        if self._responses is not None:
            idx = min(self._call_index, len(self._responses) - 1)
            self._call_index += 1
            r = self._responses[idx]
            return types.SimpleNamespace(
                choices=[
                    _FakeMessage(r.get("content"), r.get("reasoning_content"))
                ]
            )
        return types.SimpleNamespace(
            choices=[_FakeMessage(self._content, self._reasoning_content)]
        )


class _FakeAsyncOpenAI:
    """Drop-in for openai.AsyncOpenAI returning a scripted completion."""

    content = None
    raises = None
    reasoning_content = None
    calls: list | None = None
    template_400 = False
    responses: list | None = None

    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(
                self.content,
                self.raises,
                self.reasoning_content,
                type(self).calls,
                type(self).template_400,
                type(self).responses,
            )
        )


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a fake ``openai`` module so make_llm_planner imports it."""
    fake_mod = types.ModuleType("openai")

    def _factory(
        content=None,
        raises=None,
        reasoning_content=None,
        template_400=False,
        responses=None,
    ):
        cls = type(
            "ScriptedAsyncOpenAI",
            (_FakeAsyncOpenAI,),
            {
                "content": content,
                "raises": raises,
                "reasoning_content": reasoning_content,
                "calls": [],
                "template_400": template_400,
                "responses": responses,
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
async def test_mistral_template_400_retries_without_kwargs(fake_openai):
    """A Mistral-tokenizer 400 on chat_template kwargs retries without them."""
    cls = fake_openai(
        content='[{"type":"FOUND_CITY","worker_id":1}]', template_400=True
    )
    planner = make_llm_planner(base_url="http://x/v1", model="m")
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    # Did NOT fall back to the heuristic — the retry succeeded.
    assert out == [{"type": "FOUND_CITY", "worker_id": 1}]
    # Two create() calls: one with chat_template kwargs (rejected), one without.
    assert len(cls.calls) == 2
    assert (cls.calls[0].get("extra_body") or {}).get("chat_template_kwargs")
    assert not (cls.calls[1].get("extra_body") or {})


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
async def test_continuation_recovers_actions_when_overreasoning(fake_openai):
    """Model burns the budget reasoning (no array); the forced-answer follow-up
    call recovers the action, and the ORIGINAL reasoning is what gets stored."""
    cls = fake_openai(
        responses=[
            # Call 1: verbose reasoning, never emits the JSON array.
            {
                "content": "Let me think hard about this. " * 20,
                "reasoning_content": "Founding the capital maximises early growth.",
            },
            # Call 2 (forced-answer continuation): only the array.
            {"content": '[{"type":"FOUND_CITY","worker_id":1}]'},
        ]
    )
    captured = []
    planner = make_llm_planner(
        base_url="http://x/v1",
        model="m",
        on_reasoning=lambda pid, turn, reasoning, raw, actions: captured.append(
            (reasoning, actions)
        ),
    )
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 3)
    # Recovered the action rather than falling back to the heuristic.
    assert out == [{"type": "FOUND_CITY", "worker_id": 1}]
    # Two calls: the reasoning pass, then the forced-answer continuation.
    assert len(cls.calls) == 2
    # Continuation turned thinking OFF.
    assert cls.calls[1]["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    # The stored reasoning is the verbose first-call trace, with final actions.
    assert captured[0][0] == "Founding the capital maximises early growth."
    assert captured[0][1] == [{"type": "FOUND_CITY", "worker_id": 1}]


@pytest.mark.asyncio
async def test_continuation_failure_falls_back_to_heuristic(fake_openai):
    """If the continuation also yields no array, we still fall back cleanly."""
    cls = fake_openai(
        responses=[
            {"content": "thinking with no array", "reasoning_content": "hmm"},
            {"content": "still no array, sorry"},
        ]
    )
    planner = make_llm_planner(base_url="http://x/v1", model="m")
    out = await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert isinstance(out, list)  # heuristic fallback, no raise
    assert len(cls.calls) == 2  # tried the continuation before giving up


@pytest.mark.asyncio
async def test_enable_thinking_passed_to_template(fake_openai):
    """enable_thinking is forwarded via chat_template_kwargs."""
    cls = fake_openai(content="[]")
    planner = make_llm_planner(base_url="http://x/v1", model="m", enable_thinking=True)
    await planner(BALANCED, _MIN_STATE, "p1", None, 1)
    assert cls.calls, "create() was not called"
    extra_body = cls.calls[-1].get("extra_body", {})
    assert extra_body.get("chat_template_kwargs") == {"enable_thinking": True}
