'use client'

import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useGameStore, selectCurrentGameState } from '@/store/game-store'
import { MapCanvas } from '@/components/map-canvas'
import { TurnTimeline } from '@/components/turn-timeline'
import { PromptAccordion } from '@/components/prompt-accordion'
import { DiffLegend } from '@/components/diff-legend'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { ArrowLeft, Play, Pause, SkipForward, SkipBack } from 'lucide-react'
import Link from 'next/link'

export default function ReplayPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackSpeed, setPlaybackSpeed] = useState(1000) // ms between turns
  
  const gameState = useGameStore(selectCurrentGameState)
  const selectedTurn = useGameStore(state => state.selectedTurn)
  const diffMode = useGameStore(state => state.diffMode)
  const fogOfWarEnabled = useGameStore(state => state.fogOfWarEnabled)
  const selectedPlayer = useGameStore(state => state.selectedPlayer)
  const turns = useGameStore(state => state.turns)
  const prompts = useGameStore(state => state.prompts)
  const isLoading = useGameStore(state => state.isLoading)
  const error = useGameStore(state => state.error)
  
  const connectToGame = useGameStore(state => state.connectToGame)
  const seekToTurn = useGameStore(state => state.seekToTurn)
  const setSelectedPlayer = useGameStore(state => state.setSelectedPlayer)
  const toggleDiffMode = useGameStore(state => state.toggleDiffMode)
  const toggleFogOfWar = useGameStore(state => state.toggleFogOfWar)

  const availableTurns = Object.keys(turns).map(Number).sort((a, b) => a - b)
  const maxTurn = Math.max(...availableTurns, 0)
  const currentPrompts = prompts[selectedTurn] || []

  useEffect(() => {
    if (gameId) {
      connectToGame(gameId).catch(console.error)
    }
  }, [gameId, connectToGame])

  // Auto-play functionality
  useEffect(() => {
    if (!isPlaying) return

    const interval = setInterval(() => {
      if (selectedTurn < maxTurn) {
        seekToTurn(selectedTurn + 1)
      } else {
        setIsPlaying(false)
      }
    }, playbackSpeed)

    return () => clearInterval(interval)
  }, [isPlaying, selectedTurn, maxTurn, seekToTurn, playbackSpeed])

  const handlePlayPause = () => {
    setIsPlaying(!isPlaying)
  }

  const handleStepForward = () => {
    if (selectedTurn < maxTurn) {
      seekToTurn(selectedTurn + 1)
    }
  }

  const handleStepBack = () => {
    if (selectedTurn > 0) {
      seekToTurn(selectedTurn - 1)
    }
  }

  const handleTurnSeek = (turn: number) => {
    seekToTurn(turn)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4"></div>
          <p>Loading game replay...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center text-red-500">
          <p>Failed to load game: {error}</p>
          <Button asChild variant="outline" className="mt-4">
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
          <p className="mb-4">No game state available</p>
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
              Turn {selectedTurn} / {maxTurn}
            </div>
          </div>
        </div>
      </div>

      {/* Timeline Controls */}
      <div className="border-b bg-background/95 backdrop-blur">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            {/* Playback Controls */}
            <div className="flex items-center gap-2">
              <Button 
                variant="outline" 
                size="sm"
                onClick={handleStepBack}
                disabled={selectedTurn === 0}
              >
                <SkipBack className="h-4 w-4" />
              </Button>
              <Button 
                variant={isPlaying ? "default" : "outline"}
                size="sm"
                onClick={handlePlayPause}
                disabled={selectedTurn >= maxTurn}
              >
                {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </Button>
              <Button 
                variant="outline" 
                size="sm"
                onClick={handleStepForward}
                disabled={selectedTurn >= maxTurn}
              >
                <SkipForward className="h-4 w-4" />
              </Button>
              
              {/* Speed Control */}
              <div className="flex items-center gap-2 ml-4">
                <Label htmlFor="speed" className="text-sm">Speed:</Label>
                <select 
                  id="speed"
                  value={playbackSpeed}
                  onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
                  className="text-sm border rounded px-2 py-1"
                >
                  <option value={2000}>0.5x</option>
                  <option value={1000}>1x</option>
                  <option value={500}>2x</option>
                  <option value={250}>4x</option>
                </select>
              </div>
            </div>

            {/* View Options */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Switch
                  id="diff-mode"
                  checked={diffMode}
                  onCheckedChange={toggleDiffMode}
                />
                <Label htmlFor="diff-mode" className="text-sm">Diff Mode</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="fog-of-war"
                  checked={fogOfWarEnabled}
                  onCheckedChange={toggleFogOfWar}
                />
                <Label htmlFor="fog-of-war" className="text-sm">Fog of War</Label>
              </div>
            </div>
          </div>
          
          {/* Timeline Slider */}
          <div className="mt-3">
            <TurnTimeline
              currentTurn={selectedTurn}
              maxTurns={maxTurn}
              selectedTurn={selectedTurn}
              onSeek={handleTurnSeek}
              isPlaying={isPlaying}
              onPlayPause={handlePlayPause}
            />
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map Area */}
        <div className="flex-1 relative">
          <MapCanvas
            gameState={gameState}
            selectedPlayer={selectedPlayer || undefined}
            fogOfWarEnabled={fogOfWarEnabled}
            diffMode={diffMode}
          />
          
          {/* Diff Legend */}
          {diffMode && (
            <div className="absolute top-4 right-4">
              <DiffLegend />
            </div>
          )}
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
              <PromptAccordion
                prompts={currentPrompts}
                players={gameState.players}
                selectedTurn={selectedTurn}
              />
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
                
                {/* Player Stats */}
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
                    {currentPrompts.length > 0 && (
                      <>
                        <div className="flex justify-between">
                          <span>Prompts:</span>
                          <span>{currentPrompts.length}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Total Tokens:</span>
                          <span>{currentPrompts.reduce((sum, p) => sum + p.tokens_in + p.tokens_out, 0)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Avg Latency:</span>
                          <span>{Math.round(currentPrompts.reduce((sum, p) => sum + p.latency_ms, 0) / currentPrompts.length)}ms</span>
                        </div>
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