"use client";

import { ChevronLeft, ChevronRight, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { Tag } from "@/components/ui/tag";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";

export type ScrubberEventKind =
  | "move"
  | "attack"
  | "found"
  | "treaty"
  | "turn-resolved"
  | "spawn"
  | "tech";

export interface ScrubberEventTick {
  /** Turn number (1-indexed) the event sits on. */
  turn: number;
  kind: ScrubberEventKind;
}

interface ScrubberProps {
  /** Current selected turn (1..max). */
  turn: number;
  /** Inclusive maximum turn available. */
  max: number;
  /** Optional event ticks rendered above the slider. */
  events?: ScrubberEventTick[];
  /** Disable controls (e.g. while loading the turn list). */
  disabled?: boolean;
  /** When provided and `playing` is true, advances the turn at this cadence. */
  playIntervalMs?: number;
  onTurnChange: (turn: number) => void;
}

const TICK_TONE: Record<ScrubberEventKind, string> = {
  move: "var(--accent)",
  attack: "var(--destructive)",
  found: "var(--success)",
  treaty: "var(--warning)",
  spawn: "var(--success)",
  tech: "var(--accent)",
  "turn-resolved": "var(--ink-muted)",
};

export function Scrubber({
  turn,
  max,
  events = [],
  disabled = false,
  playIntervalMs = 1500,
  onTurnChange,
}: ScrubberProps) {
  const [playing, setPlaying] = useState(false);
  const atEnd = turn >= max;
  const isAdvancing = playing && !atEnd;

  useEffect(() => {
    if (!isAdvancing) return;
    const t = setTimeout(() => {
      onTurnChange(Math.min(max, turn + 1));
    }, playIntervalMs);
    return () => clearTimeout(t);
  }, [isAdvancing, turn, max, playIntervalMs, onTurnChange]);

  const safeMax = Math.max(1, max);
  const safeTurn = Math.min(Math.max(1, turn), safeMax);

  const ticks = useMemo(() => {
    return events.filter((e) => e.turn >= 1 && e.turn <= safeMax);
  }, [events, safeMax]);

  return (
    <Panel
      kicker="timeline"
      title={
        <span className="flex items-center gap-2">
          <span>Turn</span>
          <span
            className="font-mono tabular-nums text-ink"
            style={{ fontSize: 13 }}
          >
            {safeTurn}/{safeMax}
          </span>
        </span>
      }
      action={
        <Tag tone={safeTurn === safeMax ? "live" : "neutral"} mono>
          {safeTurn === safeMax ? "latest" : "scrubbing"}
        </Tag>
      }
    >
      <div className="space-y-2">
        {ticks.length > 0 && (
          <div
            className="relative h-2"
            aria-hidden="true"
          >
            {ticks.map((tick, idx) => {
              const left = ((tick.turn - 1) / Math.max(1, safeMax - 1)) * 100;
              return (
                <span
                  key={`${tick.turn}-${tick.kind}-${idx}`}
                  className="absolute top-0 inline-block h-2 w-[3px] rounded-sm"
                  style={{
                    left: `calc(${left}% - 1.5px)`,
                    background: TICK_TONE[tick.kind] ?? "var(--ink-muted)",
                  }}
                  title={`turn ${tick.turn} · ${tick.kind}`}
                />
              );
            })}
          </div>
        )}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            disabled={disabled || safeTurn <= 1}
            onClick={() => onTurnChange(1)}
            aria-label="Jump to first turn"
          >
            <SkipBack className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            disabled={disabled || safeTurn <= 1}
            onClick={() => onTurnChange(Math.max(1, safeTurn - 1))}
            aria-label="Previous turn"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            disabled={disabled || safeMax <= 1 || atEnd}
            onClick={() => setPlaying((v) => !v)}
            aria-label={isAdvancing ? "Pause" : "Play"}
          >
            {isAdvancing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            disabled={disabled || safeTurn >= safeMax}
            onClick={() => onTurnChange(Math.min(safeMax, safeTurn + 1))}
            aria-label="Next turn"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            disabled={disabled || safeTurn >= safeMax}
            onClick={() => onTurnChange(safeMax)}
            aria-label="Jump to latest turn"
          >
            <SkipForward className="h-4 w-4" />
          </Button>
          <div className="flex-1">
            <Slider
              value={[safeTurn]}
              min={1}
              max={safeMax}
              step={1}
              disabled={disabled}
              onValueChange={([v]) => onTurnChange(v)}
              aria-label="Turn timeline"
            />
          </div>
        </div>
      </div>
    </Panel>
  );
}
