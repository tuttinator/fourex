'use client'

/**
 * Phase 4 gameplay tracer — the first end-to-end action loop for a
 * seated human player.
 *
 * Flow:
 *   1. Click a friendly unit → fetch /valid-moves → highlight reachable
 *      tiles on the map.
 *   2. Click a highlighted tile → queue a MOVE action in the sidebar.
 *   3. Remove individual items from the queue if you change your mind.
 *   4. Click End Turn → POST the whole queue atomically to /actions.
 *   5. Wait for `turn.resolved` on the WebSocket → invalidate the
 *      game-state query, clear the queue, drop the waiting banner.
 *
 * The valid-moves list is re-fetched from the server rather than
 * computed client-side so the rendered highlight is exactly the set
 * the server will accept on submission — no drift risk if map-gen or
 * unit stats change server-side.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2, RefreshCw, Trash2, Send } from 'lucide-react'
import { api, ApiError, queryKeys } from '@/lib/api'
import { PixiMap } from '@/components/pixi-map'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'
import { useLobbyEvents } from '@/hooks/use-lobby-events'
import type {
  Coord,
  GameState,
  PlayerId,
  QueuedAction,
  Tile,
  Unit,
  ValidMovesResponse,
} from '@/types/game'

const ACTIVE_POLL_INTERVAL = 5000

interface GameplayViewProps {
  gameId: string
  currentPlayer: PlayerId
}

export function GameplayView({ gameId, currentPlayer }: GameplayViewProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null)
  const [queue, setQueue] = useState<QueuedAction[]>([])
  const [waiting, setWaiting] = useState(false)

  const { lastEvent } = useLobbyEvents(gameId)

  const stateQueryKey = queryKeys.gameState(gameId, currentPlayer)

  const {
    data: gameState,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: stateQueryKey,
    queryFn: () => api.getGameState(gameId),
    // Polling fallback: if the WS drops we still surface turn-resolution.
    refetchInterval: ACTIVE_POLL_INTERVAL,
  })

  const { data: validMoves } = useQuery<ValidMovesResponse | null>({
    queryKey: ['game', gameId, 'validMoves', selectedUnitId],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getValidMoves(gameId, selectedUnitId),
    enabled: selectedUnitId != null,
  })

  // Tiles already targeted by queued moves for this unit — subtract from
  // the highlight set so we don't suggest a tile the player already
  // booked. Server-side re-validation on submission will flag illegal
  // double-moves anyway, but local filtering keeps the UI honest.
  const queuedTargetKeys = useMemo(() => {
    const out = new Set<string>()
    for (const q of queue) {
      if (q.action.type === 'MOVE' && q.action.unit_id === selectedUnitId) {
        out.add(`${q.action.to.x},${q.action.to.y}`)
      }
    }
    return out
  }, [queue, selectedUnitId])

  const highlightedTiles: Coord[] = useMemo(() => {
    if (!validMoves) return []
    return validMoves.moves
      .filter((m) => !queuedTargetKeys.has(`${m.x},${m.y}`))
      .map((m) => ({ x: m.x, y: m.y }))
  }, [validMoves, queuedTargetKeys])

  const highlightedKeys = useMemo(
    () => new Set(highlightedTiles.map((t) => `${t.x},${t.y}`)),
    [highlightedTiles],
  )

  const lookupUnitAtTile = useCallback(
    (state: GameState, tile: Tile): Unit | null => {
      if (!tile.unit_id) return null
      return state.units[tile.unit_id] ?? null
    },
    [],
  )

  const handleTileClick = useCallback(
    (tile: Tile) => {
      if (!gameState) return
      const key = `${tile.loc.x},${tile.loc.y}`

      // Highlighted target takes priority — queue the move.
      if (selectedUnitId != null && highlightedKeys.has(key)) {
        setQueue((prev) => [
          ...prev,
          {
            queue_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            action: {
              type: 'MOVE',
              unit_id: selectedUnitId,
              to: { x: tile.loc.x, y: tile.loc.y },
            },
          },
        ])
        return
      }

      const unitOnTile = lookupUnitAtTile(gameState, tile)
      if (unitOnTile && unitOnTile.owner === currentPlayer) {
        setSelectedUnitId(unitOnTile.id)
        return
      }

      // Clicking anywhere else clears the selection. If the user clicks
      // an enemy unit we deliberately don't surface it as "selected" —
      // selection is a friendly-only concept here.
      setSelectedUnitId(null)
    },
    [gameState, selectedUnitId, highlightedKeys, lookupUnitAtTile, currentPlayer],
  )

  const removeFromQueue = useCallback((queueId: string) => {
    setQueue((prev) => prev.filter((q) => q.queue_id !== queueId))
  }, [])

  const submitMutation = useMutation({
    mutationFn: async () => {
      const payload = queue.map((q) => q.action)
      return api.submitActions(gameId, payload)
    },
    onSuccess: () => {
      setWaiting(true)
      toast({
        title: 'Turn submitted',
        description: 'Waiting for the server to resolve…',
      })
    },
    onError: (err) => {
      const message =
        err instanceof ApiError ? err.message : (err as Error).message
      toast({
        title: 'Submission rejected',
        description: message,
        variant: 'destructive',
      })
      setQueue((prev) =>
        prev.map((q) => ({ ...q, error: q.error ?? message })),
      )
    },
  })

  // turn.resolved: canonical signal that the queue posted, the turn
  // advanced, and we should re-fetch state. We also clear the queue
  // and drop the waiting banner here (not in the mutation's onSuccess)
  // because the server-authoritative moment is resolution, not
  // submission.
  const lastHandledTurn = useRef<number | null>(null)
  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'turn.resolved') return
    const turn = (lastEvent as unknown as { turn?: number }).turn
    if (turn != null && lastHandledTurn.current === turn) return
    if (turn != null) lastHandledTurn.current = turn
    setQueue([])
    setSelectedUnitId(null)
    setWaiting(false)
    queryClient.invalidateQueries({ queryKey: stateQueryKey })
    queryClient.invalidateQueries({
      queryKey: queryKeys.gameDetail(gameId),
    })
  }, [lastEvent, queryClient, stateQueryKey, gameId])

  const selectedUnit =
    selectedUnitId != null && gameState
      ? gameState.units[selectedUnitId] ?? null
      : null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading game state…</p>
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
            {is404 ? `No game with ID "${gameId}".` : error.message}
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
        <p className="text-muted-foreground">No game state available</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Status bar */}
      <div className="border-b px-4 py-2 flex items-center justify-between bg-muted/30">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-medium">
            Turn {gameState.turn} / {gameState.max_turns}
          </span>
          <Badge variant="secondary" className="text-xs">
            Playing as {currentPlayer}
          </Badge>
          {waiting && (
            <Badge variant="outline" className="text-xs">
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              Waiting for turn to resolve
            </Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground">
          {Object.keys(gameState.units).length} units &middot;{' '}
          {Object.keys(gameState.cities).length} cities
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map */}
        <div className="flex-1 relative">
          <PixiMap
            gameState={gameState}
            selectedPlayer={currentPlayer}
            fogOfWarEnabled
            selectedUnitId={selectedUnitId}
            highlightedTiles={highlightedTiles}
            onTileClick={handleTileClick}
          />
        </div>

        {/* Sidebar */}
        <div className="w-80 border-l bg-background/95 backdrop-blur flex flex-col">
          <Card className="rounded-none border-0 border-b">
            <CardHeader className="py-3">
              <CardTitle className="text-sm">Selection</CardTitle>
            </CardHeader>
            <CardContent className="text-sm space-y-1">
              {selectedUnit ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="capitalize font-medium">
                      {selectedUnit.type}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      #{selectedUnit.id}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    HP {selectedUnit.hp} &middot; Moves left{' '}
                    {selectedUnit.moves_left} &middot; ({selectedUnit.loc.x},{' '}
                    {selectedUnit.loc.y})
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {highlightedTiles.length} legal move
                    {highlightedTiles.length === 1 ? '' : 's'}
                  </div>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Click one of your units to see its valid moves.
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="rounded-none border-0 border-b flex-1 flex flex-col min-h-0">
            <CardHeader className="py-3">
              <CardTitle className="text-sm flex items-center justify-between">
                <span>Queued orders ({queue.length})</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-auto space-y-2 pt-0">
              {queue.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No orders queued. Click a highlighted tile to queue a
                  move.
                </p>
              ) : (
                queue.map((q) => (
                  <div
                    key={q.queue_id}
                    className="flex items-center justify-between rounded border px-2 py-1.5 text-xs"
                  >
                    <div className="flex flex-col">
                      <span className="font-medium">
                        Move unit #{q.action.unit_id} → ({q.action.to.x},{' '}
                        {q.action.to.y})
                      </span>
                      {q.error && (
                        <span className="text-destructive">{q.error}</span>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Remove queued order"
                      onClick={() => removeFromQueue(q.queue_id)}
                      className="h-6 w-6 p-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <div className="p-3 border-t">
            <Button
              className="w-full"
              disabled={submitMutation.isPending || waiting}
              onClick={() => submitMutation.mutate()}
            >
              <Send className="h-4 w-4 mr-2" />
              {submitMutation.isPending
                ? 'Submitting…'
                : waiting
                  ? 'Waiting…'
                  : `End Turn${queue.length ? ` (${queue.length})` : ''}`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
