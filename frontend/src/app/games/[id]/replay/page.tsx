'use client'

import { useParams } from 'next/navigation'
import { useEffect } from 'react'
import { useGameStore, selectCurrentGameState } from '@/store/game-store'
import { MapCanvas } from '@/components/map-canvas'
import { PromptAccordion } from '@/components/prompt-accordion'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ArrowLeft, AlertCircle, Loader2 } from 'lucide-react'
import Link from 'next/link'

export default function ReplayPage() {
  const { id: gameId } = useParams<{ id: string }>()

  const gameState = useGameStore(selectCurrentGameState)
  const selectedTurn = useGameStore(state => state.selectedTurn)
  const fogOfWarEnabled = useGameStore(state => state.fogOfWarEnabled)
  const selectedPlayer = useGameStore(state => state.selectedPlayer)
  const prompts = useGameStore(state => state.prompts)
  const isLoading = useGameStore(state => state.isLoading)
  const error = useGameStore(state => state.error)

  const loadGameState = useGameStore(state => state.loadGameState)
  const reset = useGameStore(state => state.reset)
  const setSelectedPlayer = useGameStore(state => state.setSelectedPlayer)

  const currentPrompts = prompts[selectedTurn] || []

  useEffect(() => {
    if (gameId) {
      loadGameState(gameId).catch(console.error)
    }
    return () => {
      reset()
    }
  }, [gameId, loadGameState, reset])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p>Loading game replay...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-4">Failed to load game: {error}</p>
          <Button asChild variant="outline">
            <Link href="/games">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Games
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  if (!gameState) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">No game state available</p>
          <Button asChild variant="outline">
            <Link href="/games">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Games
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
                <Link href="/games">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Back
                </Link>
              </Button>
              <h1 className="text-xl font-semibold">Replay: {gameId}</h1>
              <Badge variant="secondary">Historical</Badge>
            </div>
            <div className="text-sm text-muted-foreground">
              Turn {selectedTurn}
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map Area */}
        <div className="flex-1 relative">
          <MapCanvas
            gameState={gameState}
            selectedPlayer={selectedPlayer ?? undefined}
            fogOfWarEnabled={fogOfWarEnabled}
          />
        </div>

        {/* Right Sidebar */}
        <div className="w-96 border-l bg-background/95 backdrop-blur">
          <Tabs defaultValue="prompts" className="h-full flex flex-col">
            <TabsList className="grid w-full grid-cols-3 m-2">
              <TabsTrigger value="prompts">Prompts</TabsTrigger>
              <TabsTrigger value="players">Players</TabsTrigger>
              <TabsTrigger value="analysis">Analysis</TabsTrigger>
            </TabsList>

            <TabsContent value="prompts" className="flex-1 overflow-hidden">
              {currentPrompts.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                  No prompt data available for this turn
                </div>
              ) : (
                <PromptAccordion
                  prompts={currentPrompts}
                  players={gameState.players}
                  selectedTurn={selectedTurn}
                />
              )}
            </TabsContent>

            <TabsContent value="players" className="flex-1 overflow-hidden p-4">
              <div className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Player Selection</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {gameState.players.map((player) => (
                      <Button
                        key={player}
                        variant={selectedPlayer === player ? "default" : "outline"}
                        size="sm"
                        className="w-full justify-start"
                        onClick={() => setSelectedPlayer(selectedPlayer === player ? null : player)}
                      >
                        {player}
                      </Button>
                    ))}
                  </CardContent>
                </Card>

                {selectedPlayer && (
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">{selectedPlayer} Stats</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span>Units:</span>
                          <span>{Object.values(gameState.units).filter(u => u.owner === selectedPlayer).length}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Cities:</span>
                          <span>{Object.values(gameState.cities).filter(c => c.owner === selectedPlayer).length}</span>
                        </div>
                        {gameState.stockpiles[selectedPlayer] && (
                          <>
                            <div className="flex justify-between">
                              <span>Food:</span>
                              <span>{gameState.stockpiles[selectedPlayer].food}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Wood:</span>
                              <span>{gameState.stockpiles[selectedPlayer].wood}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Ore:</span>
                              <span>{gameState.stockpiles[selectedPlayer].ore}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Crystal:</span>
                              <span>{gameState.stockpiles[selectedPlayer].crystal}</span>
                            </div>
                          </>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            </TabsContent>

            <TabsContent value="analysis" className="flex-1 overflow-hidden p-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Turn Analysis</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span>Turn:</span>
                      <span>{selectedTurn}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Total Units:</span>
                      <span>{Object.keys(gameState.units).length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Total Cities:</span>
                      <span>{Object.keys(gameState.cities).length}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Players:</span>
                      <span>{gameState.players.length}</span>
                    </div>
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
