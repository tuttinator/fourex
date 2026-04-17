'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PLAYER_COLORS } from '@/types/game'
import { Eye, Globe } from 'lucide-react'
import type { PlayerId } from '@/types/game'

interface PerspectiveSelectorProps {
  players: PlayerId[]
  perspective: PlayerId | null
  onPerspectiveChange: (player: PlayerId | null) => void
}

export function PerspectiveSelector({
  players,
  perspective,
  onPerspectiveChange,
}: PerspectiveSelectorProps) {
  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Perspective</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {/* God mode option */}
          <Button
            variant={perspective === null ? 'default' : 'outline'}
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => onPerspectiveChange(null)}
          >
            <Globe className="h-3.5 w-3.5" />
            God mode
          </Button>

          {/* Player perspective options */}
          {players.map((player, index) => {
            const isSelected = perspective === player
            return (
              <Button
                key={player}
                variant={isSelected ? 'default' : 'outline'}
                size="sm"
                className="w-full justify-start gap-2"
                onClick={() => onPerspectiveChange(isSelected ? null : player)}
              >
                <div
                  className="w-3 h-3 rounded flex-shrink-0"
                  style={{ backgroundColor: PLAYER_COLORS[index] }}
                />
                <Eye className="h-3.5 w-3.5 flex-shrink-0" />
                <span className="truncate">{player}</span>
              </Button>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}
