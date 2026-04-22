'use client'

import { Button } from '@/components/ui/button'
import { PLAYER_COLORS } from '@/types/game'
import { Globe } from 'lucide-react'
import type { PlayerId } from '@/types/game'

interface PerspectiveSwitcherProps {
  players: PlayerId[]
  perspective: PlayerId | null
  onPerspectiveChange: (player: PlayerId | null) => void
  /** Hide the God-mode pill when the viewer isn't entitled to the
   * no-fog view (future: restrict to game creator). */
  allowGodMode?: boolean
  className?: string
}

/**
 * Inline perspective pill group for the observe/replay header bars.
 *
 * A horizontal row of radio-style buttons — one per player plus an
 * optional God-mode entry. Replaces the old sidebar ``PerspectiveSelector``
 * as the primary discovery surface: the switcher is visible without
 * opening a tab, which is what spectators actually want while watching
 * a game tick over.
 */
export function PerspectiveSwitcher({
  players,
  perspective,
  onPerspectiveChange,
  allowGodMode = true,
  className,
}: PerspectiveSwitcherProps) {
  return (
    <div
      className={
        'flex items-center gap-2 flex-wrap' + (className ? ` ${className}` : '')
      }
      role="radiogroup"
      aria-label="Perspective"
    >
      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        View
      </span>
      <div className="flex items-center gap-1 rounded-md border bg-background p-0.5">
        {allowGodMode && (
          <Button
            variant={perspective === null ? 'default' : 'ghost'}
            size="sm"
            role="radio"
            aria-checked={perspective === null}
            className="h-7 gap-1.5 px-2.5 text-xs"
            onClick={() => onPerspectiveChange(null)}
          >
            <Globe className="h-3.5 w-3.5" />
            God mode
          </Button>
        )}
        {players.map((player, index) => {
          const isSelected = perspective === player
          return (
            <Button
              key={player}
              variant={isSelected ? 'default' : 'ghost'}
              size="sm"
              role="radio"
              aria-checked={isSelected}
              className="h-7 gap-1.5 px-2.5 text-xs"
              onClick={() => onPerspectiveChange(player)}
            >
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: PLAYER_COLORS[index] }}
                aria-hidden
              />
              <span className="truncate max-w-[8rem]">{player}</span>
            </Button>
          )
        })}
      </div>
    </div>
  )
}
