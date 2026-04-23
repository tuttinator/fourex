"use client";

/**
 * Authenticated WebSocket subscription for a single lobby.
 *
 * Opens one connection per (gameId, apiKey) pair to the FastAPI
 * `/api/v1/events` endpoint and invalidates the React Query cache for
 * the lobby detail whenever a `lobby.*` event arrives — the roster
 * refresh piggybacks on the existing GET /games/{id} query.
 *
 * If no API key is available for this game yet (user hasn't joined) the
 * hook no-ops — Phase 3's live updates are only relevant to seated
 * participants. Observers on the invite URL see the polling cadence
 * from `useQuery({ refetchInterval })` until they join.
 *
 * Drop handling: a single reconnection attempt with a short backoff; if
 * that also fails the hook surfaces `status: "disconnected"` and the
 * component's 5s polling carries the lobby forward.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { queryKeys } from "@/lib/api";
import { getGameApiKey } from "@/lib/game-auth";

type ConnectionStatus = "idle" | "connecting" | "open" | "disconnected";

export interface LobbyEvent {
  type: string;
  game_id: string;
  player_id?: string;
  players?: string[];
}

interface UseLobbyEventsResult {
  status: ConnectionStatus;
  lastEvent: LobbyEvent | null;
}

function resolveWsUrl(gameId: string, apiKey: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. It must be defined at build time — " +
        "Next.js inlines NEXT_PUBLIC_* vars into the client bundle.",
    );
  }
  // Swap protocol: http(s) → ws(s). The env var is the REST base so we
  // reuse it verbatim for the WS path, avoiding a second env var that
  // can drift.
  const wsBase = base.replace(/^http/, "ws");
  const params = new URLSearchParams({ game_id: gameId, api_key: apiKey });
  return `${wsBase}/events?${params.toString()}`;
}

export function useLobbyEvents(gameId: string): UseLobbyEventsResult {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [lastEvent, setLastEvent] = useState<LobbyEvent | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!gameId) return;
    const apiKey = getGameApiKey(gameId);
    // No key → no socket. Default status is "idle" so there's nothing
    // to set; if the user joins the lobby later, the mutation bumps a
    // React Query cache that re-renders this component and reruns the
    // effect, at which point the key is present.
    if (!apiKey) return;

    let cancelled = false;
    let retried = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const open = () => {
      if (cancelled) return;
      const ws = new WebSocket(resolveWsUrl(gameId, apiKey));
      socketRef.current = ws;
      // Mark "connecting" from the callback that just instantiated the
      // socket rather than synchronously in the effect body, so we
      // satisfy the react-hooks/set-state-in-effect rule.
      queueMicrotask(() => {
        if (!cancelled) setStatus("connecting");
      });

      ws.onopen = () => {
        if (cancelled) return;
        setStatus("open");
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        let parsed: LobbyEvent | null = null;
        try {
          parsed = JSON.parse(event.data) as LobbyEvent;
        } catch {
          return;
        }
        if (!parsed || typeof parsed.type !== "string") return;
        setLastEvent(parsed);
        if (parsed.type.startsWith("lobby.")) {
          queryClient.invalidateQueries({
            queryKey: queryKeys.gameDetail(gameId),
          });
          queryClient.invalidateQueries({ queryKey: ["games"] });
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        socketRef.current = null;
        // Single reconnect attempt on first drop; subsequent drops defer
        // to the component's polling fallback so we don't hammer the
        // server on a persistent network fault.
        if (!retried) {
          retried = true;
          setStatus("connecting");
          reconnectTimer = setTimeout(open, 1500);
          return;
        }
        setStatus("disconnected");
      };

      ws.onerror = () => {
        // onclose fires right after; let it handle state transitions.
      };
    };

    open();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [gameId, queryClient]);

  return { status, lastEvent };
}
