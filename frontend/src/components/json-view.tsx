"use client";

import { useMemo } from "react";
import { Minus, Plus } from "lucide-react";

import { Panel } from "@/components/ui/panel";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tag } from "@/components/ui/tag";

interface JsonViewProps {
  /** Object describing the previous turn's state. */
  before: unknown;
  /** Object describing the current turn's state. */
  after: unknown;
  title?: string;
  kicker?: string;
}

type DiffKind = "same" | "added" | "removed" | "changed";

interface DiffEntry {
  path: string;
  kind: DiffKind;
  before?: unknown;
  after?: unknown;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function diffValues(
  before: unknown,
  after: unknown,
  path: string,
  out: DiffEntry[],
): void {
  if (Object.is(before, after)) return;
  if (isPlainObject(before) && isPlainObject(after)) {
    const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const k of Array.from(keys).sort()) {
      const sub = path ? `${path}.${k}` : k;
      const a = before[k];
      const b = after[k];
      if (!(k in before)) {
        out.push({ path: sub, kind: "added", after: b });
      } else if (!(k in after)) {
        out.push({ path: sub, kind: "removed", before: a });
      } else {
        diffValues(a, b, sub, out);
      }
    }
    return;
  }
  if (JSON.stringify(before) === JSON.stringify(after)) return;
  if (before === undefined) {
    out.push({ path, kind: "added", after });
  } else if (after === undefined) {
    out.push({ path, kind: "removed", before });
  } else {
    out.push({ path, kind: "changed", before, after });
  }
}

function summarise(value: unknown): string {
  if (value === undefined) return "undefined";
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.length === 0 ? "[]" : `[${value.length}]`;
  }
  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    return keys.length === 0 ? "{}" : `{${keys.length}}`;
  }
  return JSON.stringify(value);
}

export function JsonView({ before, after, title = "JSON diff", kicker }: JsonViewProps) {
  const entries = useMemo(() => {
    const out: DiffEntry[] = [];
    diffValues(before, after, "", out);
    return out;
  }, [before, after]);

  const additions = entries.filter((e) => e.kind === "added").length;
  const removals = entries.filter((e) => e.kind === "removed").length;
  const changes = entries.filter((e) => e.kind === "changed").length;

  return (
    <Panel
      title={title}
      kicker={kicker ?? "vs previous turn"}
      action={
        <div className="flex items-center gap-1">
          <Tag tone="success" mono>
            +{additions}
          </Tag>
          <Tag tone="destructive" mono>
            −{removals}
          </Tag>
          <Tag tone="warning" mono>
            ±{changes}
          </Tag>
        </div>
      }
      className="flex h-full flex-col"
      padded={false}
    >
      <ScrollArea className="h-full">
        <div className="px-3 py-3">
          {entries.length === 0 ? (
            <p className="text-sm text-ink-muted">
              No state changes between these turns.
            </p>
          ) : (
            <ul className="space-y-1 font-mono text-xs">
              {entries.map((e, i) => (
                <li
                  key={`${e.path}-${i}`}
                  className={`flex items-start gap-2 rounded-md border px-2 py-1.5 ${
                    e.kind === "added"
                      ? "border-success/30 bg-success/10 text-success"
                      : e.kind === "removed"
                        ? "border-destructive/30 bg-destructive/10 text-destructive"
                        : "border-warning/30 bg-warning/10 text-warning"
                  }`}
                >
                  <span className="mt-0.5 shrink-0">
                    {e.kind === "added" ? (
                      <Plus className="h-3 w-3" />
                    ) : e.kind === "removed" ? (
                      <Minus className="h-3 w-3" />
                    ) : (
                      <span style={{ fontSize: 11, fontWeight: 600 }}>±</span>
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-ink truncate">{e.path}</div>
                    <div
                      className="font-mono text-ink-muted"
                      style={{ fontSize: 10.5 }}
                    >
                      {e.kind === "added" && <>+ {summarise(e.after)}</>}
                      {e.kind === "removed" && <>− {summarise(e.before)}</>}
                      {e.kind === "changed" && (
                        <>
                          {summarise(e.before)} → {summarise(e.after)}
                        </>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </ScrollArea>
    </Panel>
  );
}
