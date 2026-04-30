import * as React from "react";

import { cn } from "@/lib/utils";

interface PanelProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  title?: React.ReactNode;
  kicker?: React.ReactNode;
  action?: React.ReactNode;
  padded?: boolean;
  bordered?: boolean;
}

export function Panel({
  title,
  kicker,
  action,
  padded = true,
  bordered = true,
  className,
  children,
  ...props
}: PanelProps) {
  const hasHeader = title !== undefined || kicker !== undefined || action !== undefined;
  return (
    <section
      className={cn(
        "flex flex-col overflow-hidden rounded-[10px] bg-surface",
        bordered && "border border-border",
        className,
      )}
      style={{ boxShadow: "0 1px 0 rgba(0,0,0,0.02)" }}
      {...props}
    >
      {hasHeader && (
        <header className="flex items-center justify-between gap-3 border-b border-border bg-bg-subtle px-3.5 py-2.5">
          <div className="flex flex-col gap-0.5">
            {kicker !== undefined && (
              <span
                className="font-mono uppercase text-accent"
                style={{ fontSize: 10.5, letterSpacing: "0.10em" }}
              >
                {kicker}
              </span>
            )}
            {title !== undefined && (
              <h3
                className="m-0 font-ui font-semibold uppercase text-ink-muted"
                style={{ fontSize: 11.5, letterSpacing: "0.06em" }}
              >
                {title}
              </h3>
            )}
          </div>
          {action !== undefined && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={cn(padded ? "p-3.5 flex-1 min-h-0" : "flex-1 min-h-0")}>
        {children}
      </div>
    </section>
  );
}
