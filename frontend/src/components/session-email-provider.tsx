"use client";

// Threads the signed-in email from a server layout down to the
// client-component pages under /games/[id]/* so they can render
// <TopBar email={...}> without re-running auth() on every render.

import { createContext, useContext, type ReactNode } from "react";

const SessionEmailContext = createContext<string | null>(null);

interface SessionEmailProviderProps {
  email: string | null;
  children: ReactNode;
}

export function SessionEmailProvider({
  email,
  children,
}: SessionEmailProviderProps) {
  return (
    <SessionEmailContext.Provider value={email}>
      {children}
    </SessionEmailContext.Provider>
  );
}

export function useSessionEmail(): string | null {
  return useContext(SessionEmailContext);
}
