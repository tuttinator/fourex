'use client'

import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { api, queryKeys, ApiError } from '@/lib/api'
import { EventLog } from '@/components/event-log'
import { PixiMap } from '@/components/pixi-map'
import { PlayerList } from '@/components/player-list'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { PlayerId } from '@/types/game'

const ACTIVE_POLL_INTERVAL = 3000
const DETAIL_POLL_INTERVAL = 5000

interface ObservationViewProps {
  gameId: string
}

export function ObservationView({ gameId }: ObservationViewProps) {
  const [selectedPlayer, setSelectedPlayer] = useState<PlayerId | null>(null)
  const [fogOfWarEnabled, setFogOfWarEnabled] = useState(false)

  const {
    data: gameDetail,
  } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: DETAIL_POLL_INTERVAL,
  })

  const isActive = gameDetail?.status === 'active'
  const isEnded = gameDetail?.status === 'ended'

  const {
    data: gameState,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.gameState(gameId),
    queryFn: () => api.getGameState(gameId),
    refetchInterval: isActive ? ACTIVE_POLL_INTERVAL : false,
    enabled: isActive || isEnded,
  })

  const handleFogToggle = useCallback((enabled: boolean) => {
    setFogOfWarEnabled(enabled)
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading game state...</p>
        </div>
      </div>
    )
  }

  if (error) {
    const is404 = error instanceof ApiError && error.status === 404
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-2">
            {is404 ? 'Game not found' : 'Failed to load game state'}
          </p>
          <p className="text-sm text-muted-foreground mb-4">
            {is404
              ? `No game exists with ID "${gameId}".`
              : error.message}
          </p>
          {!is404 && (
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Retry
            </Button>
          )}
        </div>
      </div>
    )
  }

  if (!gameState) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <p className="text-muted-foreground">No game state available</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Status bar */}
      <div className="border-b px-4 py-2 flex items-center justify-between bg-muted/30">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-medium">Turn {gameState.turn} / {gameState.max_turns}</span>
          {isActive && (
            <Badge variant="default" className="text-xs">
              <span className="relative flex h-2 w-2 mr-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
              </span>
              Live
            </Badge>
          )}
          {isEnded && (
            <Badge variant="outline" className="text-xs">Ended</Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground">
          {gameState.players.length} players &middot; {Object.keys(gameState.units).length} units &middot; {Object.keys(gameState.cities).length} cities
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map area */}
        <div className="flex-1 relative">
          <PixiMap
            gameState={gameState}
            selectedPlayer={selectedPlayer ?? undefined}
            fogOfWarEnabled={fogOfWarEnabled}
          />
        </div>

        {/* Sidebar */}
        <div className="w-80 border-l bg-background/95 backdrop-blur">
          <Tabs defaultValue="players" className="h-full flex flex-col">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="players">Players</TabsTrigger>
              <TabsTrigger value="events">Events</TabsTrigger>
              <TabsTrigger value="stats">Stats</TabsTrigger>
            </TabsList>

            <TabsContent value="players" className="flex-1 overflow-auto">
              <PlayerList
                players={gameState.players}
                gameState={gameState}
                selectedPlayer={selectedPlayer ?? undefined}
                onPlayerSelect={setSelectedPlayer}
                onFogToggle={handleFogToggle}
              />
            </TabsContent>

            <TabsContent value="events" className="flex-1 overflow-auto">
              <EventLog gameState={gameState} />
            </TabsContent>

            <TabsContent value="stats" className="flex-1 overflow-auto p-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Game Statistics</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Total Units:</span>
                      <span>{Object.keys(gameState.units).length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Total Cities:</span>
                      <span>{Object.keys(gameState.cities).length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Map Size:</span>
                      <span>{gameState.map_width}x{gameState.map_height}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Players:</span>
                      <span>{gameState.players.length}</span>
                    </div>
                    {gameState.players.map((player) => {
                      const units = Object.values(gameState.units).filter(u => u.owner === player)
                      const cities = Object.values(gameState.cities).filter(c => c.owner === player)
                      const resources = gameState.stockpiles[player]
                      return (
                        <div key={player} className="border-t pt-2 mt-2">
                          <div className="font-medium mb-1">{player}</div>
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
                        </div>
                      )
                    })}
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
