"""Phase 6 spectated-agents: per-agent telemetry and context compaction.

Three responsibilities live here:

1. **Token counting.** Providers advertising an OpenAI-compatible surface
   go through ``tiktoken`` when it's available; every other provider
   falls back to a ``len(text) / 4`` heuristic. The accuracy only needs
   to be good enough to trigger compaction at a 70%-of-window threshold,
   so a conservative heuristic is acceptable.

2. **Per-game JSONL telemetry.** ``TelemetryWriter`` writes one row per
   agent per turn to a file under ``logs/``. Rows carry provider, model,
   prompt / completion / thinking token counts, scratchpad read+write
   counts, wall-clock, and the resulting action count. Rows are
   append-only so an operator can ``tail -F`` a game log mid-run.

3. **Turn-history compaction.** ``TurnHistory`` tracks a rolling list of
   turn summaries the agent keeps in-memory. When the running token
   estimate crosses ``threshold_ratio`` of the configured provider
   window, a pluggable async summariser is invoked to compact the oldest
   half into a single block. The summary replaces those entries in the
   history AND is handed back so the caller can append it to the agent's
   scratchpad via MCP — the scratchpad itself is never truncated here.

The module is intentionally transport-agnostic: nothing here talks to
the database, the MCP server, or a provider SDK directly. The agent
runtime (or a test) supplies callbacks and this module handles the
bookkeeping.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Providers whose model surface is OpenAI-compatible enough that
# ``tiktoken`` gives a useful token count. Anything outside this set gets
# the ``len(text) / 4`` heuristic.
_TIKTOKEN_PROVIDERS: frozenset[str] = frozenset({"openai", "openai_compatible"})

# Per-provider defaults for the context window, in tokens. Callers can
# override via env vars (see ``ContextWindowConfig.from_env``) or by
# instantiating ``ContextWindowConfig`` directly.
DEFAULT_CONTEXT_WINDOWS: dict[str, int] = {
    "openai": 128_000,
    "openai_compatible": 32_000,
    "llm_studio": 32_000,
    "modal_ollama": 32_000,
    "replicate": 32_000,
    "huggingface": 8_000,
}

# Compaction fires at 70% of the configured window by default.
DEFAULT_COMPACTION_THRESHOLD_RATIO = 0.70


# --------------------------------------------------------------------------
# Token counting
# --------------------------------------------------------------------------


class TokenCounter(Protocol):
    """Anything with a ``count(str) -> int``. Used to keep tests honest."""

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class HeuristicCounter:
    """``len(text) / 4`` rounded up. Used when tiktoken is unavailable."""

    chars_per_token: int = 4

    def count(self, text: str) -> int:
        if not text:
            return 0
        # Round up so we never under-count against the threshold.
        return (len(text) + self.chars_per_token - 1) // self.chars_per_token


class TiktokenCounter:
    """``tiktoken``-backed counter for OpenAI-compatible providers."""

    def __init__(self, encoding_name: str = "cl100k_base"):
        import tiktoken  # noqa: I001 — lazy import to keep non-OpenAI paths free of it

        self._encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding.encode(text))


def make_token_counter(provider: str) -> TokenCounter:
    """Pick the right counter for ``provider``; always returns something.

    Falls back to the heuristic if ``tiktoken`` can't be imported, so
    environments without the optional dep still boot.
    """
    if provider in _TIKTOKEN_PROVIDERS:
        try:
            return TiktokenCounter()
        except Exception:
            # tiktoken optional — fall through to heuristic
            pass
    return HeuristicCounter()


def count_messages_tokens(messages: list[dict[str, Any]], counter: TokenCounter) -> int:
    """Count the concatenated text content of a chat-messages list."""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += counter.count(content)
        elif isinstance(content, list):
            # OpenAI supports multi-part content; sum the text parts.
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += counter.count(part["text"])
    return total


# --------------------------------------------------------------------------
# Telemetry records + writer
# --------------------------------------------------------------------------


@dataclass
class TelemetryRecord:
    """One row in a per-game JSONL telemetry log."""

    game_id: str
    player_id: str
    turn: int
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    scratchpad_reads: int = 0
    scratchpad_writes: int = 0
    wall_ms: int = 0
    action_count: int = 0
    compacted: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class TelemetryWriter:
    """Append-only JSONL writer. One file per game.

    Files live under ``base_dir / f"game_{game_id}.jsonl"``. The writer
    opens the file lazily on first ``write`` so creating a writer for a
    short-lived test doesn't leave empty files behind.
    """

    def __init__(self, game_id: str, base_dir: Path | str = "logs"):
        self._game_id = game_id
        self._base = Path(base_dir)
        self._path = self._base / f"game_{game_id}.jsonl"
        self._fh = None

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: TelemetryRecord) -> None:
        if self._fh is None:
            self._base.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")
        self._fh.write(record.to_json())
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> TelemetryWriter:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


# --------------------------------------------------------------------------
# Context-window + compaction config
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextWindowConfig:
    """Per-provider context windows + compaction threshold ratio.

    The defaults match ``DEFAULT_CONTEXT_WINDOWS`` but any single
    provider can be overridden via env vars:

    - ``OPENAI_CONTEXT_WINDOW``
    - ``LLM_STUDIO_CONTEXT_WINDOW``
    - ``MODAL_OLLAMA_CONTEXT_WINDOW``
    - ``AGENT_COMPACTION_THRESHOLD_RATIO``
    """

    windows: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_CONTEXT_WINDOWS)
    )
    threshold_ratio: float = DEFAULT_COMPACTION_THRESHOLD_RATIO

    def window_for(self, provider: str) -> int:
        return self.windows.get(provider, DEFAULT_CONTEXT_WINDOWS.get(provider, 32_000))

    def threshold_tokens(self, provider: str) -> int:
        return int(self.window_for(provider) * self.threshold_ratio)

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ContextWindowConfig:
        env = environ if environ is not None else os.environ
        windows = dict(DEFAULT_CONTEXT_WINDOWS)
        overrides = {
            "openai": "OPENAI_CONTEXT_WINDOW",
            "llm_studio": "LLM_STUDIO_CONTEXT_WINDOW",
            "modal_ollama": "MODAL_OLLAMA_CONTEXT_WINDOW",
            "openai_compatible": "OPENAI_COMPATIBLE_CONTEXT_WINDOW",
        }
        for provider, var in overrides.items():
            raw = env.get(var)
            if raw:
                try:
                    windows[provider] = int(raw)
                except ValueError:
                    continue
        ratio_raw = env.get("AGENT_COMPACTION_THRESHOLD_RATIO")
        ratio = DEFAULT_COMPACTION_THRESHOLD_RATIO
        if ratio_raw:
            try:
                ratio = float(ratio_raw)
            except ValueError:
                pass
        return cls(windows=windows, threshold_ratio=ratio)


# --------------------------------------------------------------------------
# Turn history + compaction
# --------------------------------------------------------------------------


@dataclass
class TurnEntry:
    """One turn's worth of in-memory history text."""

    turn: int
    text: str


@dataclass
class CompactionEvent:
    """Outcome of a single compaction pass.

    ``summary`` is the model's own compacted-turns block — exactly what
    gets both replacing the in-memory entries and appended to the
    agent's scratchpad.
    """

    first_turn: int
    last_turn: int
    summary: str
    replaced_entries: int


Summariser = Callable[[str, int, int], Awaitable[str]]
"""Async callable: ``(joined_text, first_turn, last_turn) -> summary``."""


class TurnHistory:
    """In-memory list of turn summaries with threshold-gated compaction.

    The history tracks a running token estimate cheaply — ``append`` adds
    the entry's count, ``replace_oldest_half`` replaces it with the
    summary's count. The estimate is recomputed from scratch on
    ``total_tokens`` just in case callers have muted the counter state.
    """

    # Oldest-half cutoff: keep at least this many recent entries
    # verbatim to avoid compacting right up to the current turn.
    MIN_RETAINED_ENTRIES = 2

    def __init__(
        self,
        provider: str,
        config: ContextWindowConfig | None = None,
        counter: TokenCounter | None = None,
    ):
        self._provider = provider
        self._config = config or ContextWindowConfig()
        self._counter = counter or make_token_counter(provider)
        self._entries: list[TurnEntry] = []

    @property
    def entries(self) -> list[TurnEntry]:
        return list(self._entries)

    @property
    def provider(self) -> str:
        return self._provider

    def append(self, turn: int, text: str) -> None:
        self._entries.append(TurnEntry(turn=turn, text=text))

    def render(self) -> str:
        return "\n\n".join(f"[turn {e.turn}] {e.text}" for e in self._entries)

    def total_tokens(self) -> int:
        return self._counter.count(self.render())

    def threshold_tokens(self) -> int:
        return self._config.threshold_tokens(self._provider)

    def should_compact(self) -> bool:
        if len(self._entries) < self.MIN_RETAINED_ENTRIES + 2:
            # Nothing meaningful to compact — need at least one pair to
            # summarise plus the retained tail.
            return False
        return self.total_tokens() >= self.threshold_tokens()

    def _oldest_half_cutoff(self) -> int:
        """Index of the first entry that should be *kept* verbatim.

        Compacts the oldest ``floor(n/2)`` entries and keeps the rest.
        Guarantees at least ``MIN_RETAINED_ENTRIES`` survive.
        """
        n = len(self._entries)
        half = n // 2
        keep = max(n - half, self.MIN_RETAINED_ENTRIES)
        return n - keep if n - keep > 0 else 0

    def oldest_half(self) -> list[TurnEntry]:
        cutoff = self._oldest_half_cutoff()
        return list(self._entries[:cutoff])

    async def compact(self, summariser: Summariser) -> CompactionEvent | None:
        """Summarise the oldest half and replace those entries in place.

        Returns ``None`` if no compaction happened (not enough entries
        or threshold not crossed).
        """
        if not self.should_compact():
            return None

        oldest = self.oldest_half()
        if not oldest:
            return None

        first_turn = oldest[0].turn
        last_turn = oldest[-1].turn
        joined = "\n\n".join(f"[turn {e.turn}] {e.text}" for e in oldest)

        summary = await summariser(joined, first_turn, last_turn)
        summary_text = summary.strip() or "(no summary produced)"

        replaced = len(oldest)
        cutoff = self._oldest_half_cutoff()
        summary_entry = TurnEntry(
            turn=first_turn,
            text=f"[compacted {first_turn}-{last_turn}] {summary_text}",
        )
        self._entries = [summary_entry, *self._entries[cutoff:]]

        return CompactionEvent(
            first_turn=first_turn,
            last_turn=last_turn,
            summary=summary_text,
            replaced_entries=replaced,
        )


# --------------------------------------------------------------------------
# Scratchpad append helper
# --------------------------------------------------------------------------


SCRATCHPAD_HEADER = "[compacted_turns]"
# Hard upper bound on the scratchpad body. Mirrors the MCP server's
# ``SCRATCHPAD_MAX_CHARS`` so write_scratchpad never rejects a sweep.
SCRATCHPAD_MAX_CHARS = 4000


def format_compaction_append(existing_text: str | None, event: CompactionEvent) -> str:
    """Append a compaction block to an existing scratchpad, never truncating
    prior content. Returns the new scratchpad text, trimmed at the head
    if and only if the total would exceed ``SCRATCHPAD_MAX_CHARS``.

    The header section is always surfaced — if the existing body plus
    header+summary would overflow, *older* content inside the scratchpad
    is dropped rather than this compaction block, because the compaction
    block is the whole point of the write.
    """
    block = (
        f"{SCRATCHPAD_HEADER} turns {event.first_turn}-{event.last_turn}\n"
        f"{event.summary}"
    )
    if not existing_text:
        text = block
    else:
        text = f"{existing_text.rstrip()}\n\n{block}"

    if len(text) <= SCRATCHPAD_MAX_CHARS:
        return text

    # Overflow: keep the tail (which ends with the new compaction block)
    # so the compaction block survives. Drop older material from the
    # head. This is NOT truncating the compaction output — only older
    # free-form notes written on prior turns.
    return text[-SCRATCHPAD_MAX_CHARS:]


__all__ = [
    "DEFAULT_COMPACTION_THRESHOLD_RATIO",
    "DEFAULT_CONTEXT_WINDOWS",
    "SCRATCHPAD_HEADER",
    "SCRATCHPAD_MAX_CHARS",
    "CompactionEvent",
    "ContextWindowConfig",
    "HeuristicCounter",
    "Summariser",
    "TelemetryRecord",
    "TelemetryWriter",
    "TiktokenCounter",
    "TokenCounter",
    "TurnEntry",
    "TurnHistory",
    "count_messages_tokens",
    "format_compaction_append",
    "make_token_counter",
]
