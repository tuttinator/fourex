"""LLM-backed planner.

A drop-in replacement for the heuristic :func:`plan_actions` that asks an
OpenAI-compatible LLM (a Modal-hosted vLLM ``/v1`` endpoint) to choose the
turn's actions. It implements the same ``PlannerFn`` shape, so it plugs
straight into ``MCPAgent(planner=...)`` / ``MCPGameOrchestrator(planners=...)``.

Design constraints that keep autonomous games always progressing:

- **Async, non-blocking.** Uses ``openai.AsyncOpenAI`` directly so the turn
  loop is never blocked on a synchronous network call.
- **Bounded.** Every call is wrapped in ``asyncio.wait_for(timeout_s)`` and a
  ``max_tokens`` cap, so a slow/cold model can't stall the loop or blow the
  token budget.
- **Robust fallback.** On *any* failure — timeout, transport error, unparseable
  output, empty plan — it returns the heuristic ``plan_actions`` result. The
  game therefore reaches ``ended`` even if a model misbehaves, which is what
  keeps the public game counts moving.

The runtime already calls ``validate_actions`` and drops illegal items, so the
planner does not need to produce perfectly legal actions — only well-formed
``{"type": ...}`` dicts.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from agents.src.llm_providers import extract_thinking_tokens

from .agent_runtime import PlannerFn
from .planner import plan_actions

logger = logging.getLogger(__name__)

# A sink the planner hands each turn's reasoning to. May be sync or async — an
# async sink is awaited (e.g. to persist the trace via an MCP tool). A
# slow/failing store never breaks the turn loop (errors are swallowed by the
# caller). Signature: (player_id, turn_number, reasoning, raw_completion,
# actions) -> None | Awaitable[None].
ReasoningSink = Callable[
    [str, int, str, str, list[dict[str, Any]]], None | Awaitable[None]
]

# Mistral reasoning models wrap their trace in [THINK]...[/THINK] rather than
# the <think>...</think> that extract_thinking_tokens handles.
_BRACKET_THINK_RE = re.compile(r"\[THINK\](.*?)\[/THINK\]", re.DOTALL)


def _message_reasoning(message: Any) -> str | None:
    """Pull the reasoning trace off an OpenAI-style message, field-name agnostic.

    vLLM exposes the separated thinking trace under different keys depending on
    version/parser: ``reasoning_content`` (OpenAI o1 style) or ``reasoning``
    (vLLM 0.20.1). The OpenAI SDK also stashes unknown fields in ``model_extra``.
    Check all of them so we never silently drop a trace the model produced.
    """
    if message is None:
        return None
    for attr in ("reasoning_content", "reasoning"):
        value = getattr(message, attr, None)
        if value:
            return value
    extra = getattr(message, "model_extra", None) or {}
    for key in ("reasoning_content", "reasoning"):
        if extra.get(key):
            return extra[key]
    return None


def _split_reasoning(content: str) -> tuple[str, str]:
    """Return ``(clean_content, reasoning)`` for inline-trace models.

    Handles both ``<think>...</think>`` (Qwen/Gemma-style) and
    ``[THINK]...[/THINK]`` (Mistral/Magistral-style). Used only when the server
    did not already separate the trace into ``reasoning_content``.
    """
    cleaned, thinking = extract_thinking_tokens(content)
    thinking = thinking or ""
    bracket = _BRACKET_THINK_RE.findall(cleaned)
    if bracket:
        thinking = (thinking + "\n" + "\n".join(bracket)).strip()
        cleaned = _BRACKET_THINK_RE.sub("", cleaned).strip()
    return cleaned, thinking.strip()


# The legal action shapes, embedded in the system prompt so the model knows
# exactly what to emit. Mirrors the play-parley skill's payload contract.
_ACTION_CONTRACT = """\
You control one player in a turn-based 4X strategy game. Choose this turn's
actions and reply with ONLY a JSON array of action objects — no prose, no
markdown fences. Each object has a "type" and the fields for that type:

- {"type": "MOVE", "unit_id": <int>, "to": {"x": <int>, "y": <int>}}
- {"type": "ATTACK", "attacker_id": <int>, "target_id": <int>, "target_type": "unit"}
- {"type": "FOUND_CITY", "worker_id": <int>}
- {"type": "TRAIN_UNIT", "city_id": <int>, "unit_type": "scout|worker|soldier|archer"}
- {"type": "BUILD_IMPROVEMENT", "worker_id": <int>, "improvement": "farm|mine|crystal_extractor|lumber_mill"}
- {"type": "BUILD_BUILDING", "city_id": <int>, "building_type": "granary|barracks|walls|monument|library|temple"}

Rules of thumb: move units one tile at a time toward objectives; you may submit
several actions (at most one per unit and one per city). If nothing is worth
doing, reply with []. Reply with the JSON array and nothing else."""


def _coord(entity: dict[str, Any]) -> dict[str, int] | None:
    loc = entity.get("loc") or {}
    if "x" in loc and "y" in loc:
        return {"x": int(loc["x"]), "y": int(loc["y"])}
    return None


def _summarise_state(
    state: dict[str, Any],
    player_id: str,
    analysis: dict[str, dict[str, Any]] | None,
    turn_number: int,
) -> dict[str, Any]:
    """Build a compact, token-light snapshot for the prompt."""
    # Owner-filter inline — mirrors plan_actions in planner.py (no shared helper).
    units = (state.get("units") or {}).values()
    cities = (state.get("cities") or {}).values()
    my_units = [
        {"id": u.get("id"), "type": u.get("type"), "loc": _coord(u)}
        for u in units
        if u.get("owner") == player_id
    ]
    my_cities = [
        {"id": c.get("id"), "loc": _coord(c)}
        for c in cities
        if c.get("owner") == player_id
    ]
    enemies = [
        {"type": u.get("type"), "owner": u.get("owner"), "loc": _coord(u)}
        for u in units
        if u.get("owner") != player_id
    ]
    stockpile = (state.get("stockpiles") or {}).get(player_id, {})
    summary: dict[str, Any] = {
        "turn": turn_number,
        "max_turns": state.get("max_turns"),
        "map": {"w": state.get("map_width"), "h": state.get("map_height")},
        "my_units": my_units,
        "my_cities": my_cities,
        "visible_enemy_units": enemies,
        "stockpile": stockpile,
    }
    # Fold in any analysis tool output the agent already gathered (kept small).
    if analysis:
        summary["analysis"] = {
            tool: out for tool, out in analysis.items() if isinstance(out, dict)
        }
    return summary


def _extract_action_list(text: str) -> list[dict[str, Any]]:
    """Pull the first balanced top-level JSON array of objects out of ``text``.

    Robust to ``<think>`` blocks and stray prose around the array. Returns
    only dict items that carry a ``type`` key; raises ``ValueError`` when no
    usable array is found so the caller can fall back.
    """
    cleaned, _thinking = extract_thinking_tokens(text)
    start = cleaned.find("[")
    if start == -1:
        raise ValueError("no JSON array found in model output")
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                parsed = json.loads(candidate)  # may raise — caller handles
                if not isinstance(parsed, list):
                    raise ValueError("parsed JSON is not a list")
                return [
                    item for item in parsed if isinstance(item, dict) and "type" in item
                ]
    raise ValueError("unbalanced JSON array in model output")


def make_llm_planner(
    *,
    base_url: str,
    model: str,
    api_key: str = "not-needed",
    timeout_s: float = 45.0,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    enable_thinking: bool = True,
    on_reasoning: ReasoningSink | None = None,
) -> PlannerFn:
    """Build an async ``PlannerFn`` backed by an OpenAI-compatible endpoint.

    ``base_url`` should point at a vLLM ``/v1`` URL; ``model`` is the served
    model id. The returned coroutine planner is awaited by ``MCPAgent``.

    Every seat reasons: ``enable_thinking`` is passed to the chat template (for
    models that honour it, e.g. Qwen) and defaults on. The reasoning trace is
    captured and handed to ``on_reasoning`` so callers can persist it — we keep
    the thinking, we don't discard it. The trace comes from the server's
    ``reasoning_content`` field when the model was launched with a
    ``--reasoning-parser``; otherwise it is extracted inline, and as a last
    resort the raw completion itself is stored so nothing is ever lost.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)

    async def llm_plan(
        profile: Any,
        state: dict[str, Any],
        player_id: str,
        analysis: dict[str, dict[str, Any]] | None,
        turn_number: int,
    ) -> list[dict[str, Any]]:
        def _fallback() -> list[dict[str, Any]]:
            return plan_actions(profile, state, player_id, analysis, turn_number)

        try:
            summary = _summarise_state(state, player_id, analysis, turn_number)
            system_prompt = (
                getattr(profile, "system_prompt", "") + "\n\n" + _ACTION_CONTRACT
            ).strip()
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"You are player '{player_id}'. Current situation:\n"
                        + json.dumps(summary, separators=(",", ":"))
                        + "\n\nReturn the JSON array of actions for this turn."
                    ),
                },
            ]

            async def _create(extra_body: dict[str, Any] | None):
                # Plain dicts are valid at runtime; the SDK's overloads are
                # typed against TypedDict message params, which pyrefly can't
                # match against a built list of dicts.
                return await client.chat.completions.create(  # pyrefly: ignore[no-matching-overload]
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body=extra_body,
                )

            # enable_thinking is honoured by templates that gate thinking (e.g.
            # Qwen3.x). Mistral-tokenizer models (Magistral) reject ANY
            # chat_template kwargs with a 400 — they reason by default via their
            # own template — so retry once without it. Every seat reasons.
            think_body = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
            try:
                resp = await asyncio.wait_for(_create(think_body), timeout=timeout_s)
            except Exception as exc:  # noqa: BLE001
                if "chat_template" not in str(exc).lower():
                    raise
                resp = await asyncio.wait_for(_create(None), timeout=timeout_s)
            message = resp.choices[0].message if resp.choices else None
            raw = (getattr(message, "content", None) or "") if message else ""
            # Prefer the server-separated trace (set when vLLM ran with
            # --reasoning-parser); else split it out of the content inline.
            reasoning = _message_reasoning(message)
            if reasoning:
                content = raw
            else:
                content, reasoning = _split_reasoning(raw)

            # Parse, but keep the reasoning no matter what — a parse failure
            # still falls back to the heuristic below, and we must not lose the
            # thinking in that case.
            parsed: list[dict[str, Any]] = []
            parse_error: Exception | None = None
            try:
                parsed = _extract_action_list(content)
            except Exception as parse_exc:  # noqa: BLE001 — store, then fall back
                parse_error = parse_exc

            if on_reasoning is not None:
                # Never lose the thinking: fall back to the raw completion when
                # no discrete trace was isolated. The sink may be async (e.g. it
                # persists via an MCP tool), so await an awaitable result.
                try:
                    maybe = on_reasoning(
                        player_id, turn_number, reasoning or raw, raw, parsed
                    )
                    if inspect.isawaitable(maybe):
                        await maybe
                except Exception:  # noqa: BLE001 — persistence must not break play
                    logger.warning("on_reasoning sink failed", exc_info=True)

            if parse_error is not None:
                raise parse_error  # -> heuristic fallback in the outer except

            actions = parsed
            if not actions:
                # Empty plan is valid (a deliberate pass), but if the heuristic
                # would have done something useful, prefer it on turn-0-ish
                # states. Treat empty as "pass" only when the model clearly
                # returned []; otherwise the parser would have raised.
                logger.info(
                    "llm_planner: empty plan for %s turn %s", player_id, turn_number
                )
            return actions
        except Exception as exc:  # noqa: BLE001 — any failure → heuristic
            logger.warning(
                "llm_planner fallback for %s turn %s: %s",
                player_id,
                turn_number,
                exc,
            )
            return _fallback()

    return llm_plan
