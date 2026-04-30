"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// Routes that render their own <TopBar /> (or a custom marketing nav) and
// don't want the global session strip stacked on top.
const HIDDEN_EXACT: readonly string[] = ["/", "/signin"];
const HIDDEN_PREFIX: readonly string[] = ["/games", "/signin/"];

interface SessionBarShellProps {
  children: ReactNode;
}

export function SessionBarShell({ children }: SessionBarShellProps) {
  const pathname = usePathname();
  if (!pathname) return <>{children}</>;
  if (HIDDEN_EXACT.includes(pathname)) return null;
  if (HIDDEN_PREFIX.some((p) => pathname.startsWith(p))) return null;
  return <>{children}</>;
}
