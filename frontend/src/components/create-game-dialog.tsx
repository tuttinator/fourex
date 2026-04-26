'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { setGameCredentials } from '@/lib/game-auth'
import { useToast } from '@/hooks/use-toast'
import type { CreateLobbyRequest } from '@/types/game'

interface CreateGameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateGameDialog({ open, onOpenChange }: CreateGameDialogProps) {
  const [gameId, setGameId] = useState('')
  const [playerId, setPlayerId] = useState('')
  const [playerSlots, setPlayerSlots] = useState('2')
  const [mapWidth, setMapWidth] = useState('20')
  const [mapHeight, setMapHeight] = useState('20')
  const [seed, setSeed] = useState('42')

  const { toast } = useToast()
  const queryClient = useQueryClient()
  const router = useRouter()

  const createLobbyMutation = useMutation({
    mutationFn: ({ gameId, request }: { gameId: string; request: CreateLobbyRequest }) =>
      api.createLobby(gameId, request),
    onSuccess: ({ game, api_key }) => {
      setGameCredentials(game.game_id, {
        apiKey: api_key,
        playerId: game.creator ?? playerId,
      })
      toast({
        title: 'Lobby created',
        description: `Game ${game.game_id} is waiting for ${game.player_slots} players.`,
      })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      handleClose()
      router.push(`/games/${game.game_id}`)
    },
    onError: (error) => {
      toast({
        title: 'Failed to create lobby',
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const handleClose = () => {
    setGameId('')
    setPlayerId('')
    setPlayerSlots('2')
    setMapWidth('20')
    setMapHeight('20')
    setSeed('42')
    onOpenChange(false)
  }

  const handleSubmit = () => {
    if (!gameId.trim()) {
      toast({
        title: 'Invalid game ID',
        description: 'Please enter a game ID.',
        variant: 'destructive',
      })
      return
    }

    if (!playerId.trim()) {
      toast({
        title: 'Display name required',
        description: 'Pick the display name you want for this lobby.',
        variant: 'destructive',
      })
      return
    }

    const slots = parseInt(playerSlots)
    if (isNaN(slots) || slots < 2 || slots > 8) {
      toast({
        title: 'Invalid player slots',
        description: 'Player slots must be between 2 and 8.',
        variant: 'destructive',
      })
      return
    }

    const width = parseInt(mapWidth)
    if (isNaN(width) || width < 10 || width > 100) {
      toast({
        title: 'Invalid map width',
        description: 'Map width must be between 10 and 100.',
        variant: 'destructive',
      })
      return
    }

    const height = parseInt(mapHeight)
    if (isNaN(height) || height < 10 || height > 100) {
      toast({
        title: 'Invalid map height',
        description: 'Map height must be between 10 and 100.',
        variant: 'destructive',
      })
      return
    }

    const request: CreateLobbyRequest = {
      player_id: playerId.trim(),
      player_slots: slots,
      map_width: width,
      map_height: height,
      seed: parseInt(seed) || 42,
    }

    createLobbyMutation.mutate({ gameId: gameId.trim(), request })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create New Lobby</DialogTitle>
          <DialogDescription>
            Configure the lobby. You will be seated in slot 0 under the display name you choose.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label htmlFor="gameId">Game ID</Label>
            <Input
              id="gameId"
              value={gameId}
              onChange={(e) => setGameId(e.target.value)}
              placeholder="my-test-game"
              className="mt-1"
            />
          </div>

          <div>
            <Label htmlFor="playerId">Your display name in this game</Label>
            <Input
              id="playerId"
              value={playerId}
              onChange={(e) => setPlayerId(e.target.value)}
              placeholder="alice"
              className="mt-1"
              maxLength={64}
            />
            <p className="text-xs text-muted-foreground mt-1">
              This is how you appear on the map and in diplomacy — not your account email.
            </p>
          </div>

          <div>
            <Label htmlFor="playerSlots">Player Slots</Label>
            <Input
              id="playerSlots"
              value={playerSlots}
              onChange={(e) => setPlayerSlots(e.target.value)}
              type="number"
              min={2}
              max={8}
              className="mt-1"
            />
            <p className="text-xs text-muted-foreground mt-1">2-8 players</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="mapWidth">Map Width</Label>
              <Input
                id="mapWidth"
                value={mapWidth}
                onChange={(e) => setMapWidth(e.target.value)}
                type="number"
                min={10}
                max={100}
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">10-100 tiles</p>
            </div>
            <div>
              <Label htmlFor="mapHeight">Map Height</Label>
              <Input
                id="mapHeight"
                value={mapHeight}
                onChange={(e) => setMapHeight(e.target.value)}
                type="number"
                min={10}
                max={100}
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">10-100 tiles</p>
            </div>
          </div>

          <div>
            <Label htmlFor="seed">Random Seed</Label>
            <Input
              id="seed"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="42"
              type="number"
              className="mt-1"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={createLobbyMutation.isPending}
          >
            {createLobbyMutation.isPending ? 'Creating...' : 'Create Lobby'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
