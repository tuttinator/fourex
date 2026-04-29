"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { Identity } from "@/components/brand/identity";
import { EventLog } from "@/components/event-log";
import { JsonView } from "@/components/json-view";
import { MiniMap } from "@/components/mini-map";
import { PerspectiveSwitcher } from "@/components/perspective-switcher";
import { PixiMap } from "@/components/pixi-map";
import { PromptAccordion } from "@/components/prompt-accordion";
import { Scrubber, type ScrubberEventTick } from "@/components/scrubber";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tag } from "@/components/ui/tag";
import { ApiError, api, queryKeys } from "@/lib/api";
import {
  PLAYER_COLORS,
  type Coord,
  type GameState,
  type PlayerId,
  type ViewportRect,
} from "@/types/game";

const ACTIVE_POLL_INTERVAL = 3000;
const DETAIL_POLL_INTERVAL = 5000;

export type ObservationMode = "live" | "replay";

interface ObservationSurfaceProps {
  gameId: string;
  /** `live` keeps polling while the scrubber is at the latest turn;
   * `replay` never polls. */
  mode: ObservationMode;
}

export function ObservationSurface({ gameId, mode }: ObservationSurfaceProps) {
  const [perspective, setPerspective] = useState<PlayerId | null>(null);
  const [viewportRect, setViewportRect] = useState<ViewportRect | null>(null);
  const [panToTile, setPanToTile] = useState<Coord | null>(null);
  const [scrubTurn, setScrubTurn] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState("players");

  const { data: gameDetail } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: mode === "live" ? DETAIL_POLL_INTERVAL : false,
  });

  const isActive = gameDetail?.status === "active";
  const isEnded = gameDetail?.status === "ended";

  const { data: turnList } = useQuery({
    queryKey: queryKeys.turnList(gameId),
    queryFn: () => api.listTurns(gameId, { limit: 500 }),
    refetchInterval: mode === "live" && isActive ? ACTIVE_POLL_INTERVAL : false,
    enabled: isActive || isEnded,
  });

  const totalTurns = turnList?.total ?? 0;
  const hasTurns = totalTurns > 0;
  const latestTurn = Math.max(1, totalTurns);
  const effectiveTurn = scrubTurn ?? latestTurn;
  const isAtLatest = effectiveTurn >= latestTurn;
  const livePolling = mode === "live" && isActive && isAtLatest;

  const {
    data: liveState,
    isLoading: liveLoading,
    error: liveError,
    refetch: refetchLive,
  } = useQuery({
    queryKey: queryKeys.gameState(gameId, perspective),
    queryFn: () =>
      perspective
        ? api.getGameStateAsPlayer(gameId, perspective)
        : api.getGameState(gameId),
    refetchInterval: livePolling ? ACTIVE_POLL_INTERVAL : false,
    enabled: livePolling,
  });

  const {
    data: snapshotState,
    isLoading: snapshotLoading,
    error: snapshotError,
  } = useQuery({
    queryKey: queryKeys.turnState(gameId, effectiveTurn, perspective),
    queryFn: () =>
      perspective
        ? api.getTurnState(gameId, effectiveTurn, perspective)
        : api.getTurnState(gameId, effectiveTurn),
    enabled: hasTurns && !livePolling,
  });

  const { data: prevState } = useQuery({
    queryKey: queryKeys.turnState(gameId, Math.max(1, effectiveTurn - 1), perspective),
    queryFn: () =>
      perspective
        ? api.getTurnState(gameId, Math.max(1, effectiveTurn - 1), perspective)
        : api.getTurnState(gameId, Math.max(1, effectiveTurn - 1)),
    enabled: hasTurns && effectiveTurn > 1,
  });

  const { data: turnDetail } = useQuery({
    queryKey: queryKeys.turnDetail(gameId, effectiveTurn),
    queryFn: () => api.getTurnDetail(gameId, effectiveTurn),
    enabled: hasTurns,
  });

  const { data: turnPrompts } = useQuery({
    queryKey: queryKeys.turnPrompts(gameId, effectiveTurn),
    queryFn: () => api.getTurnPrompts(gameId, effectiveTurn),
    enabled: hasTurns,
  });

  const gameState: GameState | undefined = livePolling
    ? liveState
    : snapshotState;
  const isLoading = livePolling ? liveLoading : snapshotLoading;
  const error = livePolling ? liveError : snapshotError;

  const events: ScrubberEventTick[] = useMemo(() => {
    if (!turnList) return [];
    return turnList.turns.map((t) => ({
      turn: t.turn_number,
      kind: "turn-resolved" as const,
    }));
  }, [turnList]);

  if (isLoading) {
    return (
      <CenterMsg icon={<Loader2 className="h-8 w-8 animate-spin" />}>
        Loading game state…
      </CenterMsg>
    );
  }

  if (error) {
    const is404 = error instanceof ApiError && error.status === 404;
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <div className="text-center">
          <AlertCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <p className="mb-2 text-destructive">
            {is404 ? "Game not found" : "Failed to load game state"}
          </p>
          <p className="mb-4 text-sm text-ink-muted">
            {is404 ? `No game exists with ID "${gameId}".` : error.message}
          </p>
          {!is404 && (
            <Button variant="outline" onClick={() => refetchLive()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (!gameState) {
    return <CenterMsg>No game state available.</CenterMsg>;
  }

  const allPlayers = gameDetail?.players ?? gameState.players;
  const totalUnits = Object.keys(gameState.units).length;
  const totalCities = Object.keys(gameState.cities).length;
  const isFogOfWar = perspective !== null;

  return (
    <div className="flex h-full flex-col bg-bg text-ink font-ui">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-bg-subtle px-5 py-2.5">
        <div className="flex items-center gap-2.5">
          <span
            className="font-mono text-ink"
            style={{ fontSize: 12, letterSpacing: "0.02em" }}
          >
            turn {gameState.turn} / {gameState.max_turns}
          </span>
          {mode === "live" && isActive && livePolling && <Tag tone="live" mono>live</Tag>}
          {mode === "live" && isActive && !livePolling && (
            <Tag tone="warning" mono>scrubbing</Tag>
          )}
          {mode === "replay" && <Tag tone="neutral" mono>replay</Tag>}
          {isEnded && mode !== "replay" && <Tag tone="neutral" mono>ended</Tag>}
        </div>
        <PerspectiveSwitcher
          players={allPlayers}
          perspective={perspective}
          onPerspectiveChange={setPerspective}
        />
        <span className="font-mono text-ink-muted" style={{ fontSize: 11 }}>
          {allPlayers.length} players · {totalUnits} units · {totalCities} cities
        </span>
      </div>

      <div className="flex flex-1 overflow-hidden gap-3 p-3">
        <div className="flex flex-1 min-w-0 flex-col gap-3">
          <Panel className="flex-1 min-h-0" padded={false}>
            <div className="relative h-full">
              <PixiMap
                gameState={gameState}
                selectedPlayer={perspective ?? undefined}
                fogOfWarEnabled={isFogOfWar}
                frameVariant="parchment"
                onViewportRectChange={setViewportRect}
                panToTile={panToTile}
              />
              <div className="pointer-events-auto absolute bottom-3 right-3">
                <MiniMap
                  gameState={gameState}
                  viewport={viewportRect}
                  onPanRequest={(coord) => setPanToTile({ ...coord })}
                  width={180}
                />
              </div>
            </div>
          </Panel>
          {hasTurns && (
            <Scrubber
              turn={effectiveTurn}
              max={latestTurn}
              events={events}
              onTurnChange={(t) =>
                setScrubTurn(t === latestTurn ? null : t)
              }
            />
          )}
        </div>

        <aside className="w-[360px] shrink-0">
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="flex h-full flex-col gap-3"
          >
            <TabsList className="grid w-full grid-cols-5">
              <TabsTrigger value="prompt">Prompt</TabsTrigger>
              <TabsTrigger value="json">JSON</TabsTrigger>
              <TabsTrigger value="players">Players</TabsTrigger>
              <TabsTrigger value="events">Events</TabsTrigger>
              <TabsTrigger value="stats">Stats</TabsTrigger>
            </TabsList>

            <TabsContent value="prompt" className="flex-1 overflow-hidden">
              {perspective === null ? (
                <Panel
                  title="Prompt"
                  kicker="agent reasoning"
                  className="h-full"
                >
                  <p className="text-sm text-ink-muted">
                    Select a player perspective to view their prompt for this
                    turn.
                  </p>
                </Panel>
              ) : (
                <PromptAccordion
                  prompts={turnPrompts?.prompts ?? []}
                  players={[perspective]}
                  selectedTurn={effectiveTurn}
                />
              )}
            </TabsContent>

            <TabsContent value="json" className="flex-1 overflow-hidden">
              <JsonView
                before={prevState ?? null}
                after={gameState}
                kicker={`t${Math.max(1, effectiveTurn - 1)} → t${effectiveTurn}`}
              />
            </TabsContent>

            <TabsContent value="players" className="flex-1 overflow-auto">
              <Panel padded={false} title="Roster" kicker="players">
                <ul className="m-0 list-none p-0">
                  {allPlayers.map((player, index) => {
                    const units = Object.values(gameState.units).filter(
                      (u) => u.owner === player,
                    );
                    const cities = Object.values(gameState.cities).filter(
                      (c) => c.owner === player,
                    );
                    const resources = gameState.stockpiles[player];
                    const color = PLAYER_COLORS[index % 8] ?? "#888";
                    const viewing = perspective === player;
                    return (
                      <li
                        key={player}
                        className="flex flex-col gap-2 px-3.5 py-3 [&:not(:last-child)]:border-b [&:not(:last-child)]:border-border"
                      >
                        <div className="flex items-center justify-between">
                          <Identity
                            kind="human"
                            name={player}
                            id={player}
                            color={color}
                            size={24}
                            showLabel
                            label={`seat ${index + 1}`}
                          />
                          {viewing && <Tag tone="accent" mono>viewing</Tag>}
                        </div>
                        <div
                          className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-ink-soft"
                          style={{ fontSize: 11.5 }}
                        >
                          <span>units · {units.length}</span>
                          <span>cities · {cities.length}</span>
                          {resources && (
                            <>
                              <span>food · {resources.food}</span>
                              <span>wood · {resources.wood}</span>
                              <span>ore · {resources.ore}</span>
                              <span>crystal · {resources.crystal}</span>
                            </>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Panel>
            </TabsContent>

            <TabsContent value="events" className="flex-1 overflow-auto">
              <EventLog gameState={gameState} />
            </TabsContent>

            <TabsContent value="stats" className="flex-1 overflow-auto">
              <Panel title="Statistics" kicker="this turn">
                <dl className="m-0 flex flex-col gap-2 text-[13px]">
                  <Row k="Total units" v={totalUnits} />
                  <Row k="Total cities" v={totalCities} />
                  <Row
                    k="Map size"
                    v={`${gameState.map_width}×${gameState.map_height}`}
                  />
                  <Row k="Players" v={allPlayers.length} />
                  {turnDetail?.state_hash && (
                    <Row
                      k="State hash"
                      v={
                        <span
                          className="truncate font-mono"
                          title={turnDetail.state_hash}
                        >
                          {turnDetail.state_hash.slice(0, 12)}…
                        </span>
                      }
                    />
                  )}
                  {isFogOfWar && (
                    <Row
                      k="Visible tiles"
                      v={`${gameState.tiles.length} / ${gameState.map_width * gameState.map_height}`}
                      accent="warning"
                    />
                  )}
                </dl>
              </Panel>
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}

function CenterMsg({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-[400px] items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-center">
        {icon}
        <p className="text-ink-muted">{children}</p>
      </div>
    </div>
  );
}

function Row({
  k,
  v,
  accent,
}: {
  k: string;
  v: React.ReactNode;
  accent?: "warning";
}) {
  return (
    <div className="flex items-center justify-between">
      <span className={accent === "warning" ? "text-warning" : "text-ink-muted"}>
        {k}
      </span>
      <span
        className={`font-mono ${accent === "warning" ? "text-warning" : "text-ink"}`}
        style={{ fontSize: 12.5 }}
      >
        {v}
      </span>
    </div>
  );
}
