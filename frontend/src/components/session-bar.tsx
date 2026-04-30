import Link from "next/link";
import { auth, signOut } from "@/auth";
import { Wordmark } from "@/components/brand/wordmark";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { fetchServerIdentity } from "@/lib/server-identity";

interface SessionBarProps {
  /** When true, render a compact session strip with the wordmark on the left.
   *  When false, render only the right-aligned session controls. The landing
   *  page suppresses this entirely and renders its own nav. */
  showWordmark?: boolean;
}

export async function SessionBar({ showWordmark = true }: SessionBarProps = {}) {
  const session = await auth();
  const identity = session?.user?.email ? await fetchServerIdentity() : null;

  return (
    <div className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2 text-sm">
      <div className="flex items-center gap-3">
        {showWordmark && (
          <Link href="/" className="inline-flex">
            <Wordmark variant="flag" size={16} />
          </Link>
        )}
        {identity?.isAdmin && (
          <Link
            href="/maps"
            className="text-ink-muted hover:text-ink font-mono text-xs"
            data-testid="nav-maps"
          >
            Maps
          </Link>
        )}
      </div>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        {session?.user?.email ? (
          <>
            <span className="text-ink-muted font-mono text-xs">
              {session.user.email}
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
      </div>
    </div>
  );
}
