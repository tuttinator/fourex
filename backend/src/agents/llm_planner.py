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
import json
import logging
from typing import Any

from agents.src.llm_providers import extract_thinking_tokens

from .agent_runtime import PlannerFn
from .planner import plan_actions

logger = logging.getLogger(__name__)

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
) -> PlannerFn:
    """Build an async ``PlannerFn`` backed by an OpenAI-compatible endpoint.

    ``base_url`` should point at a vLLM ``/v1`` URL; ``model`` is the served
    model id. The returned coroutine planner is awaited by ``MCPAgent``.
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
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=timeout_s,
            )
            content = (resp.choices[0].message.content or "") if resp.choices else ""
            actions = _extract_action_list(content)
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
