'use client'

import { Slider } from '@/components/ui/slider'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import type { TurnTimelineProps } from '@/types/game'
import { Play, Pause, SkipForward, SkipBack, RotateCcw } from 'lucide-react'

export function TurnTimeline({
  currentTurn,
  maxTurns,
  selectedTurn,
  onSeek,
  isPlaying = false,
  onPlayPause
}: TurnTimelineProps) {
  const handleSliderChange = (values: number[]) => {
    onSeek(values[0])
  }

  const progress = maxTurns > 0 ? (selectedTurn / maxTurns) * 100 : 0

  return (
    <div className="space-y-3">
      {/* Timeline Slider */}
      <div className="relative">
        <Slider
          value={[selectedTurn]}
          onValueChange={handleSliderChange}
          max={maxTurns}
          min={0}
          step={1}
          className="w-full"
        />
        
        {/* Turn markers */}
        <div className="absolute top-6 w-full">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Turn 0</span>
            {maxTurns > 10 && (
              <>
                <span>Turn {Math.floor(maxTurns / 4)}</span>
                <span>Turn {Math.floor(maxTurns / 2)}</span>
                <span>Turn {Math.floor((maxTurns * 3) / 4)}</span>
              </>
            )}
            <span>Turn {maxTurns}</span>
          </div>
        </div>
      </div>

      {/* Timeline Info */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            Turn {selectedTurn}
          </Badge>
          <span className="text-sm text-muted-foreground">
            {progress.toFixed(1)}% complete
          </span>
        </div>
        
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSeek(0)}
            disabled={selectedTurn === 0}
          >
            <RotateCcw className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSeek(Math.max(0, selectedTurn - 1))}
            disabled={selectedTurn === 0}
          >
            <SkipBack className="h-3 w-3" />
          </Button>
          {onPlayPause && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onPlayPause}
              disabled={selectedTurn >= maxTurns}
            >
              {isPlaying ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSeek(Math.min(maxTurns, selectedTurn + 1))}
            disabled={selectedTurn >= maxTurns}
          >
            <SkipForward className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSeek(maxTurns)}
            disabled={selectedTurn >= maxTurns}
          >
            <span className="text-xs">End</span>
          </Button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-secondary rounded-full h-1">
        <div 
          className="bg-primary h-1 rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}