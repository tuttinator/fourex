'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { api, queryKeys, ApiError } from '@/lib/api'
import { PixiMap } from '@/components/pixi-map'
import { PerspectiveSelector } from '@/components/perspective-selector'
import { PromptAccordion } from '@/components/prompt-accordion'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  ArrowLeft,
  AlertCircle,
  Loader2,
  RefreshCw,
  SkipBack,
  SkipForward,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import type { PlayerId } from '@/types/game'

export default function ReplayPage() {
  const { id: gameId } = useParams<{ id: string }>()

  const [selectedTurn, setSelectedTurn] = useState<number>(1)
  const [perspective, setPerspective] = useState<PlayerId | null>(null)
  const [perspectiveInitialised, setPerspectiveInitialised] = useState(false)

  // Fetch game detail for player list and status
  const { data: gameDetail } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
  })

  // Default to first player's perspective once we know the player list,
  // so replay works even when god-mode snapshots are sparse.
  if (gameDetail?.players?.length && !perspectiveInitialised) {
    setPerspective(gameDetail.players[0])
    setPerspectiveInitialised(true)
  }

  // Fetch turn list to know available turns
  const {
    data: turnList,
    isLoading: turnsLoading,
    error: turnsError,
    refetch: refetchTurns,
  } = useQuery({
    queryKey: queryKeys.turnList(gameId),
    queryFn: () => api.listTurns(gameId, { limit: 200 }),
  })

  const totalTurns = turnList?.total ?? 0
  const hasTurns = totalTurns > 0

  // Clamp selectedTurn to valid range when turn list loads
  const effectiveTurn = hasTurns
    ? Math.min(selectedTurn, totalTurns)
    : selectedTurn

  // Fetch state snapshot for the selected turn
  const {
    data: turnState,
    isLoading: stateLoading,
    error: stateError,
  } = useQuery({
    queryKey: queryKeys.turnState(gameId, effectiveTurn, perspective),
    queryFn: () =>
      perspective
        ? api.getTurnState(gameId, effectiveTurn, perspective)
        : api.getTurnState(gameId, effectiveTurn),
    enabled: hasTurns,
  })

  // Fetch turn detail (actions + results) for the selected turn
  const { data: turnDetail } = useQuery({
    queryKey: queryKeys.turnDetail(gameId, effectiveTurn),
    queryFn: () => api.getTurnDetail(gameId, effectiveTurn),
    enabled: hasTurns,
  })

  // Fetch prompt logs for the selected turn
  const { data: turnPrompts } = useQuery({
    queryKey: queryKeys.turnPrompts(gameId, effectiveTurn),
    queryFn: () => api.getTurnPrompts(gameId, effectiveTurn),
    enabled: hasTurns,
  })

  const allPlayers = gameDetail?.players ?? turnState?.players ?? []
  const isFogOfWar = perspective !== null

  // Loading state
  if (turnsLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading replay data...</p>
        </div>
      </div>
    )
  }

  // Error state
  if (turnsError) {
    const is404 = turnsError instanceof ApiError && turnsError.status === 404
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-2">
            {is404 ? 'Game not found' : 'Failed to load replay data'}
          </p>
          <p className="text-sm text-muted-foreground mb-4">
            {is404 ? `No game exists with ID "${gameId}".` : turnsError.message}
          </p>
          <div className="flex gap-2 justify-center">
            {!is404 && (
              <Button variant="outline" onClick={() => refetchTurns()}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </Button>
            )}
            <Button asChild variant="outline">
              <Link href="/games">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Games
              </Link>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // No turns available
  if (!hasTurns) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-2">No turns to replay</p>
          <p className="text-sm text-muted-foreground mb-4">
            This game has not completed any turns yet.
          </p>
          <Button asChild variant="outline">
            <Link href={`/games/${gameId}`}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Game
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button asChild variant="ghost" size="sm">
                <Link href={`/games/${gameId}`}>
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Back
                </Link>
              </Button>
              <h1 className="text-xl font-semibold">Replay: {gameId}</h1>
              <Badge variant="secondary">Historical</Badge>
              {gameDetail?.status === 'ended' && gameDetail.winner && (
                <Badge variant="outline">Winner: {gameDetail.winner}</Badge>
              )}
            </div>
            <div className="flex items-center gap-3 text-sm">
              <span className="text-muted-foreground">
                Turn {effectiveTurn} / {totalTurns}
              </span>
              {isFogOfWar && (
                <Badge variant="secondary" className="text-xs">
                  {perspective}&apos;s view
                </Badge>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Turn Timeline */}
      <div className="border-b px-4 py-3 bg-muted/30">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={effectiveTurn <= 1}
              onClick={() => setSelectedTurn(1)}
            >
              <SkipBack className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={effectiveTurn <= 1}
              onClick={() => setSelectedTurn(Math.max(1, effectiveTurn - 1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex-1">
            <Slider
              value={[effectiveTurn]}
              min={1}
              max={totalTurns}
              step={1}
              onValueChange={([value]) => setSelectedTurn(value)}
            />
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={effectiveTurn >= totalTurns}
              onClick={() => setSelectedTurn(Math.min(totalTurns, effectiveTurn + 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={effectiveTurn >= totalTurns}
              onClick={() => setSelectedTurn(totalTurns)}
            >
              <SkipForward className="h-4 w-4" />
            </Button>
          </div>
          <span className="text-sm font-mono w-20 text-right tabular-nums">
            {effectiveTurn} / {totalTurns}
          </span>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map Area */}
        <div className="flex-1 relative">
          {stateLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
                <p className="text-muted-foreground">Loading turn state...</p>
              </div>
            </div>
          ) : stateError ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <AlertCircle className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
                <p className="text-sm text-muted-foreground mb-1">
                  No snapshot available for turn {effectiveTurn}
                </p>
                <p className="text-xs text-muted-foreground">
                  {isFogOfWar
                    ? `No fog-of-war snapshot found for ${perspective}.`
                    : 'Full snapshots are saved every 10 turns, plus initial and final states.'}
                </p>
              </div>
            </div>
          ) : turnState ? (
            <PixiMap
              gameState={turnState}
              selectedPlayer={perspective ?? undefined}
              fogOfWarEnabled={isFogOfWar}
            />
          ) : null}
        </div>

        {/* Right Sidebar */}
        <div className="w-96 border-l bg-background/95 backdrop-blur">
          <Tabs defaultValue="actions" className="h-full flex flex-col">
            <TabsList className="grid w-full grid-cols-4 m-2">
              <TabsTrigger value="actions">Actions</TabsTrigger>
              <TabsTrigger value="prompts">Prompts</TabsTrigger>
              <TabsTrigger value="players">Players</TabsTrigger>
              <TabsTrigger value="analysis">Analysis</TabsTrigger>
            </TabsList>

            {/* Action Results Tab */}
            <TabsContent value="actions" className="flex-1 overflow-hidden">
              <ScrollArea className="h-full">
                <div className="p-4 space-y-3">
                  {turnDetail ? (
                    allPlayers.map((player) => {
                      const results = turnDetail.action_results[player]
                      const actions = turnDetail.player_actions[player]
                      if (!results && !actions) return null

                      return (
                        <Card key={player}>
                          <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center justify-between">
                              <span>{player}</span>
                              {results && (
                                <Badge variant="outline" className="text-xs">
                                  {results.length} action{results.length !== 1 ? 's' : ''}
                                </Badge>
                              )}
                            </CardTitle>
                          </CardHeader>
                          <CardContent>
                            {results && results.length > 0 ? (
                              <div className="space-y-2">
                                {results.map((result, i) => (
                                  <div
                                    key={i}
                                    className="flex items-start gap-2 text-xs"
                                  >
                                    {result.success ? (
                                      <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 text-green-500 shrink-0" />
                                    ) : (
                                      <XCircle className="h-3.5 w-3.5 mt-0.5 text-red-500 shrink-0" />
                                    )}
                                    <div className="min-w-0">
                                      <span className="font-medium">
                                        {result.action && typeof result.action === 'object' && 'type' in result.action
                                          ? String((result.action as Record<string, unknown>).type)
                                          : 'Action'}
                                      </span>
                                      <span className="text-muted-foreground ml-1">
                                        — {result.message}
                                      </span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                No actions this turn
                              </p>
                            )}
                          </CardContent>
                        </Card>
                      )
                    })
                  ) : (
                    <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                      No action data available for this turn
                    </div>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Prompts Tab */}
            <TabsContent value="prompts" className="flex-1 overflow-hidden">
              {turnPrompts && turnPrompts.prompts.length > 0 ? (
                <PromptAccordion
                  prompts={turnPrompts.prompts}
                  players={allPlayers}
                  selectedTurn={effectiveTurn}
                />
              ) : (
                <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                  No prompt data available for this turn
                </div>
              )}
            </TabsContent>

            {/* Players / Perspective Tab */}
            <TabsContent value="players" className="flex-1 overflow-auto">
              <PerspectiveSelector
                players={allPlayers}
                perspective={perspective}
                onPerspectiveChange={setPerspective}
              />

              {turnState && (
                <div className="p-4 space-y-3">
                  {allPlayers.map((player) => {
                    const units = Object.values(turnState.units).filter(
                      (u) => u.owner === player,
                    )
                    const cities = Object.values(turnState.cities).filter(
                      (c) => c.owner === player,
                    )
                    const resources = turnState.stockpiles[player]
                    return (
                      <Card key={player}>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">{player}</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="grid grid-cols-2 gap-1 text-xs">
                            <span>Units: {units.length}</span>
                            <span>Cities: {cities.length}</span>
                            {resources && (
                              <>
                                <span>Food: {resources.food}</span>
                                <span>Wood: {resources.wood}</span>
                                <span>Ore: {resources.ore}</span>
                                <span>Crystal: {resources.crystal}</span>
                              </>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    )
                  })}
                </div>
              )}
            </TabsContent>

            {/* Analysis Tab */}
            <TabsContent value="analysis" className="flex-1 overflow-hidden p-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Turn Analysis</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Turn:</span>
                      <span>{effectiveTurn}</span>
                    </div>
                    {turnState && (
                      <>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Total Units:</span>
                          <span>{Object.keys(turnState.units).length}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Total Cities:</span>
                          <span>{Object.keys(turnState.cities).length}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Map Size:</span>
                          <span>
                            {turnState.map_width}x{turnState.map_height}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Players:</span>
                          <span>{turnState.players.length}</span>
                        </div>
                        {isFogOfWar && (
                          <div className="flex justify-between text-yellow-600 dark:text-yellow-400">
                            <span>Visible Tiles:</span>
                            <span>
                              {turnState.tiles.length} /{' '}
                              {turnState.map_width * turnState.map_height}
                            </span>
                          </div>
                        )}
                      </>
                    )}
                    {turnDetail && (
                      <>
                        <div className="border-t pt-2 mt-2" />
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">State Hash:</span>
                          <span className="font-mono text-xs truncate max-w-[120px]">
                            {turnDetail.state_hash}
                          </span>
                        </div>
                        {turnDetail.completed_at && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Completed:</span>
                            <span className="text-xs">
                              {new Date(turnDetail.completed_at).toLocaleString()}
                            </span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}
