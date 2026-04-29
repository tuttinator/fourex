// In-app top bar — wordmark, optional game context, slotted right
// actions, signed-in email + sign-out. Server component so `auth()` can
// run inline; pages that render this should also be present in
// SessionBarShell's HIDDEN_PATHS so the global session strip stays out
// of their way.

import Link from "next/link";
import type { ReactNode } from "react";
import { auth, signOut } from "@/auth";
import { Wordmark } from "@/components/brand/wordmark";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

interface GameContext {
  name: string;
  state?: "live" | "replay" | "waiting" | "ended";
  turn?: number;
  max?: number;
}

interface TopBarProps {
  game?: GameContext;
  /** Right-aligned action slot, rendered before the session controls. */
  children?: ReactNode;
}

const STATE_LABEL: Record<NonNullable<GameContext["state"]>, string> = {
  live: "live",
  replay: "replay",
  waiting: "waiting",
  ended: "ended",
};

export async function TopBar({ game, children }: TopBarProps) {
  const session = await auth();
  const email = session?.user?.email ?? null;

  return (
    <header className="sticky top-0 z-10 flex min-h-14 flex-nowrap items-center gap-4 whitespace-nowrap border-b border-border bg-surface px-5 py-3">
      <Link href="/" className="inline-flex shrink-0">
        <Wordmark variant="flag" size={18} />
      </Link>

      {game && (
        <>
          <span className="h-[22px] w-px shrink-0 bg-border" aria-hidden />
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="truncate font-mono text-[13px] text-ink">
              {game.name}
            </span>
            {game.state && (
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono ${
                  game.state === "live"
                    ? "bg-accent-soft text-accent"
                    : "bg-surface-alt text-ink-soft"
                }`}
                style={{ fontSize: 11, letterSpacing: "0.02em" }}
              >
                {game.state === "live" && (
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
                {STATE_LABEL[game.state]}
              </span>
            )}
            {typeof game.turn === "number" && typeof game.max === "number" && (
              <span
                className="font-mono text-ink-muted"
                style={{ fontSize: 12 }}
              >
                turn {game.turn} / {game.max}
              </span>
            )}
          </div>
        </>
      )}

      <span className="flex-1" />

      {children && <div className="flex items-center gap-2">{children}</div>}

      <ThemeToggle />

      <span className="h-[22px] w-px shrink-0 bg-border" aria-hidden />

      {email ? (
        <>
          <span
            className="max-w-[180px] overflow-hidden text-ellipsis font-ui text-[12.5px] text-ink-muted"
            title={email}
          >
            {email}
          </span>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/signin" });
            }}
          >
            <Button type="submit" size="sm" variant="ghost">
              Sign out
            </Button>
          </form>
        </>
      ) : (
        <Button asChild size="sm" variant="outline">
          <Link href="/signin">Sign in</Link>
        </Button>
      )}
    </header>
  );
}
