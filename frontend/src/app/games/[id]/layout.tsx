import type { ReactNode } from "react";
import { auth } from "@/auth";
import { SessionEmailProvider } from "@/components/session-email-provider";

// Server layout that resolves the signed-in email once and seeds the
// client-side context. Pages under /games/[id]/* are client components
// (state, query hooks, etc.) and read the email via useSessionEmail()
// to populate <TopBar email={...}>.
export default async function GameDetailLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await auth();
  const email = session?.user?.email ?? null;
  return (
    <SessionEmailProvider email={email}>{children}</SessionEmailProvider>
  );
}
