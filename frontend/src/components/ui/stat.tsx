import * as React from "react";

import { cn } from "@/lib/utils";

interface StatProps {
  value: React.ReactNode;
  label: React.ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function Stat({ value, label, size = "md", className }: StatProps) {
  const valueSize = size === "lg" ? 32 : size === "sm" ? 20 : 26;
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span
        className="font-display font-medium leading-none text-ink"
        style={{ fontSize: valueSize, letterSpacing: "-0.02em" }}
      >
        {value}
      </span>
      <span
        className="font-mono uppercase text-ink-muted"
        style={{ fontSize: 10.5, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
    </div>
  );
}

interface StatPairProps {
  label: React.ReactNode;
  value: React.ReactNode;
  accent?: "default" | "warning" | "success";
  className?: string;
}

export function StatPair({ label, value, accent = "default", className }: StatPairProps) {
  const labelClass =
    accent === "warning"
      ? "text-warning"
      : accent === "success"
        ? "text-success"
        : "text-ink-muted";
  const valueClass =
    accent === "warning"
      ? "text-warning"
      : accent === "success"
        ? "text-success"
        : "text-ink";
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <span
        className={cn("font-mono uppercase", labelClass)}
        style={{ fontSize: 10.5, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span
        className={cn("font-mono tabular-nums", valueClass)}
        style={{ fontSize: 12.5 }}
      >
        {value}
      </span>
    </div>
  );
}
