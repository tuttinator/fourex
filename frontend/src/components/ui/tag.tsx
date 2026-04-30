import * as React from "react";

import { cn } from "@/lib/utils";

export type TagTone =
  | "neutral"
  | "accent"
  | "success"
  | "warning"
  | "live"
  | "destructive";

interface TagProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: TagTone;
  mono?: boolean;
}

const TONES: Record<TagTone, { bg: string; fg: string; bd: string }> = {
  neutral: {
    bg: "var(--surface-alt)",
    fg: "var(--ink-soft)",
    bd: "var(--border)",
  },
  accent: {
    bg: "var(--accent-soft)",
    fg: "var(--accent)",
    bd: "var(--accent-soft)",
  },
  success: {
    bg: "oklch(from var(--success) l c h / 0.12)",
    fg: "var(--success)",
    bd: "oklch(from var(--success) l c h / 0.20)",
  },
  warning: {
    bg: "oklch(from var(--warning) l c h / 0.14)",
    fg: "oklch(from var(--warning) calc(l - 0.10) c h)",
    bd: "oklch(from var(--warning) l c h / 0.30)",
  },
  live: {
    bg: "var(--accent-soft)",
    fg: "var(--accent)",
    bd: "transparent",
  },
  destructive: {
    bg: "oklch(from var(--destructive) l c h / 0.14)",
    fg: "var(--destructive)",
    bd: "oklch(from var(--destructive) l c h / 0.30)",
  },
};

export function Tag({
  tone = "neutral",
  mono = false,
  className,
  style,
  children,
  ...props
}: TagProps) {
  const t = TONES[tone];
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5", className)}
      style={{
        background: t.bg,
        color: t.fg,
        boxShadow: `inset 0 0 0 1px ${t.bd}`,
        fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)",
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: mono ? "0.02em" : "0.005em",
        lineHeight: 1.5,
        ...style,
      }}
      {...props}
    >
      {tone === "live" && (
        <span
          className="inline-block animate-parley-pulse"
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "var(--accent)",
          }}
        />
      )}
      {children}
    </span>
  );
}
