'use client'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useGameStore } from '@/store/game-store'
import { 
  Play, 
  Pause, 
  SkipForward, 
  Eye, 
  EyeOff,
  Diff,
  ZoomIn,
  ZoomOut,
  RotateCcw
} from 'lucide-react'

export function GameToolbar() {
  const gameState = useGameStore(state => state.turns[state.selectedTurn])
  const fogOfWarEnabled = useGameStore(state => state.fogOfWarEnabled)
  const diffMode = useGameStore(state => state.diffMode)
  const autoZoom = useGameStore(state => state.autoZoom)
  const toggleFogOfWar = useGameStore(state => state.toggleFogOfWar)
  const toggleDiffMode = useGameStore(state => state.toggleDiffMode)
  const connectionStatus = useGameStore(state => state.connectionStatus)

  if (!gameState) return null

  return (
    <div className="border-b bg-background/95 backdrop-blur">
      <div className="container mx-auto px-4 py-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm">
              <Play className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <Pause className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <SkipForward className="h-4 w-4" />
            </Button>
            <div className="h-4 w-px bg-border mx-2" />
            <Button 
              variant={fogOfWarEnabled ? "default" : "outline"} 
              size="sm"
              onClick={toggleFogOfWar}
            >
              {fogOfWarEnabled ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              Fog of War
            </Button>
            <Button 
              variant={diffMode ? "default" : "outline"} 
              size="sm"
              onClick={toggleDiffMode}
            >
              <Diff className="h-4 w-4" />
              Diff Mode
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant={connectionStatus === 'open' ? 'default' : 'secondary'}>
              {connectionStatus}
            </Badge>
            <Button variant="outline" size="sm">
              <ZoomIn className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <ZoomOut className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <RotateCcw className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}