// Server wrapper around the client <TopBar>. Resolves the signed-in
// email via `auth()` and binds the sign-out server action so server
// pages (e.g. /games) can render the bar without re-implementing the
// auth plumbing.

import type { ReactNode } from "react";
import { auth } from "@/auth";
import { signOutAction } from "@/lib/auth-actions";
import { TopBar, type TopBarGameContext } from "@/components/top-bar";

interface TopBarServerProps {
  game?: TopBarGameContext;
  children?: ReactNode;
}

export async function TopBarServer({ game, children }: TopBarServerProps) {
  const session = await auth();
  const email = session?.user?.email ?? null;
  return (
    <TopBar email={email} signOutAction={signOutAction} game={game}>
      {children}
    </TopBar>
  );
}
