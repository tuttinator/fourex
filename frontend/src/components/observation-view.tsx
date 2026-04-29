"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Identity } from "@/components/brand/identity";
import { EventLog } from "@/components/event-log";
import { MiniMap } from "@/components/mini-map";
import { PerspectiveSwitcher } from "@/components/perspective-switcher";
import { PixiMap } from "@/components/pixi-map";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tag } from "@/components/ui/tag";
import { ApiError, api, queryKeys } from "@/lib/api";
import { PLAYER_COLORS, type Coord, type PlayerId, type ViewportRect } from "@/types/game";

const ACTIVE_POLL_INTERVAL = 3000;
const DETAIL_POLL_INTERVAL = 5000;

interface ObservationViewProps {
  gameId: string;
}

export function ObservationView({ gameId }: ObservationViewProps) {
  const [perspective, setPerspective] = useState<PlayerId | null>(null);
  const [viewportRect, setViewportRect] = useState<ViewportRect | null>(null);
  const [panToTile, setPanToTile] = useState<Coord | null>(null);

  const { data: gameDetail } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: DETAIL_POLL_INTERVAL,
  });

  const isActive = gameDetail?.status === "active";
  const isEnded = gameDetail?.status === "ended";

  const {
    data: gameState,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.gameState(gameId, perspective),
    queryFn: () =>
      perspective
        ? api.getGameStateAsPlayer(gameId, perspective)
        : api.getGameState(gameId),
    refetchInterval: isActive ? ACTIVE_POLL_INTERVAL : false,
    enabled: isActive || isEnded,
  });

  const isFogOfWar = perspective !== null;

  if (isLoading) {
    return <CenterMsg icon={<Loader2 className="h-8 w-8 animate-spin" />}>Loading game state…</CenterMsg>;
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
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (!gameState) {
    return <CenterMsg>No game state available</CenterMsg>;
  }

  const allPlayers = gameDetail?.players ?? gameState.players;
  const totalUnits = Object.keys(gameState.units).length;
  const totalCities = Object.keys(gameState.cities).length;

  return (
    <div className="flex h-full flex-col bg-bg text-ink font-ui">
      {/* Status / context bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-bg-subtle px-5 py-2.5">
        <div className="flex items-center gap-2.5">
          <span
            className="font-mono text-ink"
            style={{ fontSize: 12, letterSpacing: "0.02em" }}
          >
            turn {gameState.turn} / {gameState.max_turns}
          </span>
          {isActive && <Tag tone="live" mono>live</Tag>}
          {isEnded && <Tag tone="neutral" mono>ended</Tag>}
        </div>
        <PerspectiveSwitcher
          players={allPlayers}
          perspective={perspective}
          onPerspectiveChange={setPerspective}
        />
        <span
          className="font-mono text-ink-muted"
          style={{ fontSize: 11 }}
        >
          {allPlayers.length} players · {totalUnits} units · {totalCities} cities
        </span>
      </div>

      {/* Two-column main: map | sidebar */}
      <div className="flex flex-1 overflow-hidden p-3 gap-3">
        <Panel className="flex-1 min-w-0" padded={false}>
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

        <aside className="w-[340px] shrink-0">
          <Tabs defaultValue="players" className="flex h-full flex-col gap-3">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="players">Players</TabsTrigger>
              <TabsTrigger value="events">Events</TabsTrigger>
              <TabsTrigger value="stats">Stats</TabsTrigger>
            </TabsList>

            <TabsContent value="players" className="flex-1 overflow-auto">
              <Panel padded={false} title="Roster">
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
              <Panel title="Game statistics">
                <dl className="m-0 flex flex-col gap-2 text-[13px]">
                  <Row k="Total units" v={totalUnits} />
                  <Row k="Total cities" v={totalCities} />
                  <Row k="Map size" v={`${gameState.map_width}×${gameState.map_height}`} />
                  <Row k="Players" v={allPlayers.length} />
                  {isFogOfWar && (
                    <Row
                      k="Visible tiles"
                      v={`${gameState.tiles.length} / ${gameState.map_width * gameState.map_height}`}
                      accent="warning"
                    />
                  )}
                </dl>
                <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
                  {allPlayers.map((player, index) => {
                    const units = Object.values(gameState.units).filter(
                      (u) => u.owner === player,
                    );
                    const cities = Object.values(gameState.cities).filter(
                      (c) => c.owner === player,
                    );
                    const resources = gameState.stockpiles[player];
                    const color = PLAYER_COLORS[index % 8] ?? "#888";
                    return (
                      <div key={player} className="flex flex-col gap-1">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="inline-block rounded-sm"
                            style={{
                              width: 10,
                              height: 10,
                              background: color,
                              boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.3)",
                            }}
                          />
                          <span className="font-medium text-ink">{player}</span>
                        </div>
                        <div
                          className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-ink-soft"
                          style={{ fontSize: 11 }}
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
                      </div>
                    );
                  })}
                </div>
              </Panel>
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}

// ──────────────── tiny shared bits ────────────────

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
      <span
        className={accent === "warning" ? "text-warning" : "text-ink-muted"}
      >
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

