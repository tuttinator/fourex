import * as React from "react";

import { cn } from "@/lib/utils";

export function Kbd({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded bg-surface text-ink-muted",
        className,
      )}
      style={{
        minWidth: 18,
        height: 18,
        padding: "0 5px",
        boxShadow: "inset 0 0 0 1px var(--border), 0 1px 0 var(--border)",
        fontFamily: "var(--font-mono)",
        fontSize: 10.5,
      }}
      {...props}
    >
      {children}
    </span>
  );
}
