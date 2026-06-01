"""CLI for the autonomous live match runner.

Examples
--------
Play 5 games (2 players each) against the live server, two models defined
inline via env-provided vLLM endpoints::

    VLLM_API_KEY=... \\
    PARLEY_VLLM_QWEN36_A3B_URL=https://...modal.run/v1 \\
    PARLEY_VLLM_GEMMA4_31B_URL=https://...modal.run/v1 \\
    PARLEY_VLLM_MAGISTRAL_SMALL_URL=https://...modal.run/v1 \\
    uv run python -m backend.src.agents.run_live_matches --max-games 5

Endpoints are read from ``--endpoint label=base_url[:model]`` flags (repeatable)
or, if none are given, from ``PARLEY_VLLM_<LABEL>_URL`` environment variables.
The served model name defaults to the label (matching ``--served-model-name``
in the Modal deploy).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .match_runner import MatchConfig, ModelEndpoint, run_forever

# Labels mirror MODEL_REGISTRY in agents/deploy/modal_vllm.py (and the
# --served-model-name each vLLM endpoint serves under).
_KNOWN_LABELS = ("qwen36-a3b", "gemma4-31b", "magistral-small")


def _endpoints_from_args(
    specs: list[str], *, timeout_s: float, max_tokens: int
) -> list[ModelEndpoint]:
    eps: list[ModelEndpoint] = []
    for spec in specs:
        label, _, rest = spec.partition("=")
        if not rest:
            raise SystemExit(f"--endpoint must be label=base_url[:model]: {spec!r}")
        # Split an optional trailing :model that isn't part of the scheme.
        base_url, _, model = rest.rpartition(",")
        if not base_url:  # no comma → whole thing is the URL
            base_url, model = rest, label
        eps.append(
            ModelEndpoint(
                label=label,
                base_url=base_url,
                model=model or label,
                api_key=os.getenv("VLLM_API_KEY", "not-needed"),
                timeout_s=timeout_s,
                max_tokens=max_tokens,
            )
        )
    return eps


def _endpoints_from_env(*, timeout_s: float, max_tokens: int) -> list[ModelEndpoint]:
    eps: list[ModelEndpoint] = []
    for label in _KNOWN_LABELS:
        env_key = f"PARLEY_VLLM_{label.replace('-', '_').upper()}_URL"
        url = os.getenv(env_key)
        if url:
            eps.append(
                ModelEndpoint(
                    label=label,
                    base_url=url,
                    model=label,
                    api_key=os.getenv("VLLM_API_KEY", "not-needed"),
                    timeout_s=timeout_s,
                    max_tokens=max_tokens,
                )
            )
    return eps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run autonomous LLM-vs-LLM games.")
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Model endpoint as label=base_url[,model]. Repeatable.",
    )
    parser.add_argument("--mcp-url", default=None, help="Override the live MCP URL.")
    parser.add_argument("--players-per-game", type=int, default=2)
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--turn-cap", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-games", type=int, default=10)
    parser.add_argument("--per-game-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Per-LLM-call timeout (s). Raise above the cold-start time "
        "(~180-240s for a scale-to-zero vLLM endpoint) so the first turn "
        "isn't forced into the heuristic fallback.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Per-call generation cap. Reasoning traces eat into this.",
    )
    parser.add_argument("--kill-switch", default=None, help="Stop if this file exists.")
    parser.add_argument("--results", default="logs/match_results.jsonl")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    endpoints = (
        _endpoints_from_args(
            args.endpoint, timeout_s=args.timeout, max_tokens=args.max_tokens
        )
        if args.endpoint
        else _endpoints_from_env(timeout_s=args.timeout, max_tokens=args.max_tokens)
    )
    if not endpoints:
        raise SystemExit(
            "No endpoints. Pass --endpoint label=url or set "
            "PARLEY_VLLM_<LABEL>_URL env vars."
        )

    cfg = MatchConfig(
        endpoints=endpoints,
        mcp_url=args.mcp_url or MatchConfig.mcp_url,
        players_per_game=args.players_per_game,
        max_turns=args.max_turns,
        max_turn_cap=args.turn_cap,
        concurrency=args.concurrency,
        max_games=args.max_games,
        per_game_timeout_s=args.per_game_timeout,
        kill_switch_path=args.kill_switch,
        results_path=args.results,
    )
    outcomes = asyncio.run(run_forever(cfg))
    ended = sum(1 for o in outcomes if o.status == "ended")
    print(f"Done: {len(outcomes)} games, {ended} reached 'ended'.")


if __name__ == "__main__":
    main()
