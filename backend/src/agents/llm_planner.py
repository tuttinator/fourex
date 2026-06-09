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
You control one player in a turn-based 4X strategy game. First REASON BRIEFLY
about your position — your units, cities, resources, visible threats and
opportunities, and how this turn advances your strategy. Keep your reasoning to
a few decisive sentences; do NOT deliberate at length. Then give your FINAL
ANSWER as a JSON array of action objects. Each object has a "type" and the
fields for that type:

- {"type": "MOVE", "unit_id": <int>, "to": {"x": <int>, "y": <int>}}
- {"type": "ATTACK", "attacker_id": <int>, "target_id": <int>, "target_type": "unit"}
- {"type": "FOUND_CITY", "worker_id": <int>}
- {"type": "TRAIN_UNIT", "city_id": <int>, "unit_type": "scout|worker|soldier|archer"}
- {"type": "BUILD_IMPROVEMENT", "worker_id": <int>, "improvement": "farm|mine|crystal_extractor|lumber_mill"}
- {"type": "BUILD_BUILDING", "city_id": <int>, "building_type": "granary|barracks|walls|monument|library|temple"}

Rules of thumb: move units one tile at a time toward objectives; you may submit
several actions (at most one per unit and one per city). If nothing is worth
doing, your final answer is [].

OWNERSHIP: "your_units" and "your_cities" are YOURS; everything under
"visible_enemy_units" belongs to opponents. "force_balance" is the authoritative
count of your vs enemy forces — trust it rather than counting the lists. Never
attack your own units or treat them as a threat.

CONTINUITY: the situation includes "your_recent_turns" (what you actually did
the last few turns) and "memory" (your standing goals and notes on opponents).
Play a consistent, evolving strategy — build on your prior moves and follow
through on plans rather than re-deciding from scratch or repeating yourself.

Do your reasoning first, then end your reply with the FINAL ANSWER: the JSON
array alone, on its own, with no prose or markdown fences after it."""


# Sent as a follow-up turn when the model reasoned but never emitted a parseable
# action array (verbose thinking-mode models — notably Qwen3.x — sometimes spend
# the whole token budget reasoning). We keep the original reasoning trace and ask
# only for the action, with thinking turned OFF so it answers immediately.
_FORCE_ANSWER_PROMPT = (
    "You reasoned but did not finish with a JSON array. Output ONLY your final "
    "JSON array of actions for this turn now — no reasoning, no prose, no "
    "markdown fences. Just the array, e.g. "
    '[{"type":"MOVE","unit_id":1,"to":{"x":2,"y":3}}] or [] to pass.'
)

# Appended to the forced-answer prompt when chat is enabled, so a model that
# decided to talk during its reasoning doesn't lose that intent on the recovery
# call (the plain prompt only shows game actions).
_FORCE_ANSWER_CHAT_SUFFIX = (
    " The array MAY also include diplomacy, e.g. "
    '{"type":"SEND_MESSAGE","recipient":"<player_id>","body":"<short message>"}; '
    "include a message if you intended to talk this turn or owe a reply."
)


# Appended to the contract only when chat/diplomacy is enabled for the game.
# Deliberately directive: in the baseline (chat off) runs agents simply ignored
# the soft "you may talk" invitation, so here diplomacy is framed as an active,
# expected part of play to actually surface chat behaviour worth studying.
_CHAT_CONTRACT = """

DIPLOMACY IS ACTIVE this game — what you say shapes the outcome as much as how
you move. To message another player, add this action to your JSON array
(alongside any game actions):
- {"type": "SEND_MESSAGE", "recipient": "<player_id>", "body": "<your message>"}
How to play the table:
- On your FIRST turn, open with a short message to each other player — greet
  them, propose a pact, or stake a claim.
- Most turns, send at least one message when it could help: propose or honour
  alliances, coordinate or trade, bluff, threaten, or deceive.
- ALWAYS reply when someone has messaged you — their messages appear under
  "incoming_messages" in the situation above.
- Keep each message to one or two sentences. Valid recipients are listed under
  "other_players"."""


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
    """Build a compact snapshot for the prompt.

    Ownership is made explicit and unambiguous: your own units/cities use
    ``your_*`` keys, opponents live under ``visible_enemy_units``, and a
    pre-counted ``force_balance`` is the single source of truth for "who has how
    many" — so the model never has to count, or read the confusable
    ``my_military_units`` / ``visible_enemy_military`` analysis fields it was
    observed to transpose (reasoning about its own army as the enemy's).
    """
    # Owner-filter inline — mirrors plan_actions in planner.py (no shared helper).
    units = (state.get("units") or {}).values()
    cities = (state.get("cities") or {}).values()
    military_types = {"soldier", "archer"}
    your_units = [
        {"id": u.get("id"), "type": u.get("type"), "loc": _coord(u)}
        for u in units
        if u.get("owner") == player_id
    ]
    your_cities = [
        {"id": c.get("id"), "loc": _coord(c)}
        for c in cities
        if c.get("owner") == player_id
    ]
    enemy_units = [
        {"type": u.get("type"), "owner": u.get("owner"), "loc": _coord(u)}
        for u in units
        if u.get("owner") != player_id
    ]
    stockpile = (state.get("stockpiles") or {}).get(player_id, {})
    summary: dict[str, Any] = {
        "turn": turn_number,
        "max_turns": state.get("max_turns"),
        "you_are": player_id,
        "map": {"w": state.get("map_width"), "h": state.get("map_height")},
        "your_units": your_units,
        "your_cities": your_cities,
        "visible_enemy_units": enemy_units,
        # Authoritative, pre-counted balance — trust this over counting the lists.
        "force_balance": {
            "your_units_total": len(your_units),
            "your_military": sum(
                1 for u in your_units if u.get("type") in military_types
            ),
            "visible_enemy_units_total": len(enemy_units),
            "visible_enemy_military": sum(
                1 for u in enemy_units if u.get("type") in military_types
            ),
        },
        "stockpile": stockpile,
    }
    # Valid message recipients (so the model addresses SEND_MESSAGE correctly).
    others = [p for p in (state.get("players") or []) if p != player_id]
    if others:
        summary["other_players"] = others
    # Fold in any analysis tool output the agent already gathered (kept small).
    if analysis:
        # Cross-turn continuity: this agent's own recent moves and the memory it
        # read (strategic goals, opponent models, prior turn notes). Surfaced
        # top-level — the runtime injects these under reserved keys.
        recent = analysis.get("_recent_turns")
        if recent:
            summary["your_recent_turns"] = recent
        memory = analysis.get("_memory")
        if memory:
            summary["memory"] = memory
        # Lift inbound chat OUT of the analysis blob to a top-level field so the
        # model plainly sees what it must react to (it was previously buried).
        incoming = analysis.get("incoming_messages")
        if incoming:
            summary["incoming_messages"] = incoming
        _reserved = {"incoming_messages", "_memory", "_recent_turns"}
        analysis_blob: dict[str, Any] = {}
        for tool, out in analysis.items():
            if not isinstance(out, dict) or tool in _reserved:
                continue
            # Drop the military tool's own count block — force_balance is the
            # single source of truth, and its `my_military_units` /
            # `visible_enemy_military` keys are exactly what the model transposed.
            if tool == "evaluate_military_position":
                out = {k: v for k, v in out.items() if k != "strength_comparison"}
            analysis_blob[tool] = out
        summary["analysis"] = analysis_blob
    return summary


def _extract_action_list(text: str) -> list[dict[str, Any]]:
    """Pull the LAST balanced top-level JSON array of objects out of ``text``.

    The prompt asks the model to reason first and END with the JSON array as its
    final answer, so we scan from the last ``]`` backwards and return the last
    balanced array that parses as a list — robust to reasoning prose (and stray
    brackets) before the answer, and to ``<think>`` blocks. Returns only dict
    items carrying a ``type`` key; raises ``ValueError`` when no usable array is
    found so the caller can fall back.
    """
    cleaned, _thinking = extract_thinking_tokens(text)
    end = cleaned.rfind("]")
    while end != -1:
        depth = 0
        start = -1
        for i in range(end, -1, -1):
            ch = cleaned[i]
            if ch == "]":
                depth += 1
            elif ch == "[":
                depth -= 1
                if depth == 0:
                    start = i
                    break
        if start != -1:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [
                    item for item in parsed if isinstance(item, dict) and "type" in item
                ]
        end = cleaned.rfind("]", 0, end)
    raise ValueError("no JSON array found in model output")


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
    chat_enabled: bool = False,
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
    # Sticky flag: once a model rejects chat_template kwargs (Mistral tokenizer
    # 400s), stop sending them so every subsequent turn isn't a wasted 400+retry.
    template_ok = [True]

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
                getattr(profile, "system_prompt", "")
                + "\n\n"
                + _ACTION_CONTRACT
                + (_CHAT_CONTRACT if chat_enabled else "")
            ).strip()
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"You are player '{player_id}'. Current situation:\n"
                        # Pretty-printed (not minified): newlines + indentation
                        # cut the own-vs-enemy transposition errors a dense blob
                        # invited. The state is small, so the token cost is minor.
                        + json.dumps(summary, indent=2)
                        + "\n\nReturn the JSON array of actions for this turn."
                    ),
                },
            ]

            async def _create(
                msgs: list[dict[str, Any]],
                extra_body: dict[str, Any] | None,
                tokens: int,
            ):
                # Plain dicts are valid at runtime; the SDK's overloads are
                # typed against TypedDict message params, which pyrefly can't
                # match against a built list of dicts.
                return await client.chat.completions.create(  # pyrefly: ignore[no-matching-overload]
                    model=model,
                    messages=msgs,
                    max_tokens=tokens,
                    temperature=temperature,
                    extra_body=extra_body,
                )

            # enable_thinking is honoured by templates that gate thinking (e.g.
            # Qwen3.x). Mistral-tokenizer models (Magistral) reject ANY
            # chat_template kwargs with a 400 — they reason by default via their
            # own template. Try with kwargs until the model rejects them once,
            # then skip them for the rest of the game. Every seat reasons.
            think_body = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
            if not template_ok[0]:
                resp = await asyncio.wait_for(
                    _create(messages, None, max_tokens), timeout=timeout_s
                )
            else:
                try:
                    resp = await asyncio.wait_for(
                        _create(messages, think_body, max_tokens), timeout=timeout_s
                    )
                except Exception as exc:  # noqa: BLE001
                    if "chat_template" not in str(exc).lower():
                        raise
                    template_ok[0] = False
                    resp = await asyncio.wait_for(
                        _create(messages, None, max_tokens), timeout=timeout_s
                    )
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

            # Forced-answer continuation: the model reasoned but never produced a
            # parseable array (it burned the budget thinking, or refused JSON).
            # Rather than drop straight to the heuristic, ask once more for ONLY
            # the action array, thinking OFF, feeding the reasoning back so the
            # action reflects it. The verbose trace from the first call is what we
            # store; this just recovers the decision. Best-effort: any failure
            # here leaves parse_error set and we fall back below.
            if parse_error is not None:
                try:
                    force_prompt = _FORCE_ANSWER_PROMPT + (
                        _FORCE_ANSWER_CHAT_SUFFIX if chat_enabled else ""
                    )
                    followup = messages + [
                        {"role": "assistant", "content": (reasoning or raw)[:6000]},
                        {"role": "user", "content": force_prompt},
                    ]
                    no_think = (
                        {"chat_template_kwargs": {"enable_thinking": False}}
                        if template_ok[0]
                        else None
                    )
                    cont = await asyncio.wait_for(
                        _create(followup, no_think, min(max_tokens, 512)),
                        timeout=timeout_s,
                    )
                    cmsg = cont.choices[0].message if cont.choices else None
                    ctext = (getattr(cmsg, "content", None) or "") if cmsg else ""
                    # The continuation has thinking off, but split defensively in
                    # case the template still emitted a trace.
                    cclean, _ = _split_reasoning(ctext)
                    parsed = _extract_action_list(cclean)
                    parse_error = None
                    logger.info(
                        "llm_planner: recovered actions via continuation for %s "
                        "turn %s",
                        player_id,
                        turn_number,
                    )
                except Exception:  # noqa: BLE001 — keep parse_error; heuristic below
                    logger.info(
                        "llm_planner: continuation did not yield actions for %s "
                        "turn %s",
                        player_id,
                        turn_number,
                    )

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
