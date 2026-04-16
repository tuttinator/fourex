'use client'

import { useState, useMemo } from 'react'
import { PixiMap } from '@/components/pixi-map'
import { createDemoGameState } from '@/lib/demo-fixture'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { PLAYER_COLORS } from '@/types/game'

export default function DemoPage() {
  const [mapSize, setMapSize] = useState<20 | 50 | 100>(20)
  const gameState = useMemo(() => createDemoGameState(mapSize, mapSize), [mapSize])

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-semibold">Map Renderer Demo</h1>
              <Badge variant="secondary">Pixi.js</Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground mr-2">Map size:</span>
              {([20, 50, 100] as const).map((size) => (
                <Button
                  key={size}
                  variant={mapSize === size ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setMapSize(size)}
                >
                  {size}x{size}
                </Button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map */}
        <div className="flex-1 relative">
          <PixiMap gameState={gameState} />
        </div>

        {/* Legend sidebar */}
        <div className="w-64 border-l bg-background/95 p-4 overflow-y-auto">
          <h2 className="text-sm font-semibold mb-3">Controls</h2>
          <div className="space-y-1 text-xs text-muted-foreground mb-4">
            <div>Scroll to zoom</div>
            <div>Click + drag to pan</div>
            <div>Hover for tile info</div>
          </div>

          <h2 className="text-sm font-semibold mb-2">Players</h2>
          <div className="space-y-1 mb-4">
            {gameState.players.map((p, i) => (
              <div key={p} className="flex items-center gap-2 text-xs">
                <div
                  className="w-3 h-3 rounded"
                  style={{ backgroundColor: PLAYER_COLORS[i] }}
                />
                <span>{p}</span>
              </div>
            ))}
          </div>

          <h2 className="text-sm font-semibold mb-2">Terrain</h2>
          <div className="space-y-1 mb-4">
            {(['plains', 'forest', 'mountain', 'water'] as const).map((t) => (
              <div key={t} className="flex items-center gap-2 text-xs">
                <div
                  className="w-3 h-3 rounded"
                  style={{
                    backgroundColor:
                      t === 'plains' ? '#8fbc8f'
                        : t === 'forest' ? '#228b22'
                          : t === 'mountain' ? '#696969'
                            : '#4682b4',
                  }}
                />
                <span className="capitalize">{t}</span>
              </div>
            ))}
          </div>

          <h2 className="text-sm font-semibold mb-2">Units</h2>
          <div className="space-y-1 mb-4">
            {(['scout', 'worker', 'soldier', 'archer'] as const).map((u) => (
              <div key={u} className="flex items-center gap-2 text-xs">
                <div
                  className="w-3 h-3 rounded"
                  style={{
                    backgroundColor:
                      u === 'scout' ? '#22c55e'
                        : u === 'worker' ? '#3b82f6'
                          : u === 'soldier' ? '#ef4444'
                            : '#a855f7',
                  }}
                />
                <span className="capitalize">{u}</span>
              </div>
            ))}
          </div>

          <h2 className="text-sm font-semibold mb-2">Game Info</h2>
          <div className="space-y-1 text-xs text-muted-foreground">
            <div>Turn: {gameState.turn}/{gameState.max_turns}</div>
            <div>Map: {gameState.map_width}x{gameState.map_height}</div>
            <div>Units: {Object.keys(gameState.units).length}</div>
            <div>Cities: {Object.keys(gameState.cities).length}</div>
            <div>Tiles: {gameState.tiles.length}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
