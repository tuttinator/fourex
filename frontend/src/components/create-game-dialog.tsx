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
import { useToast } from '@/hooks/use-toast'
import type { CreateLobbyRequest } from '@/types/game'

interface CreateGameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateGameDialog({ open, onOpenChange }: CreateGameDialogProps) {
  const [gameId, setGameId] = useState('')
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
    onSuccess: (data) => {
      toast({
        title: 'Game lobby created',
        description: `Game ${data.game_id} is waiting for ${data.player_slots} players.`,
      })
      queryClient.invalidateQueries({ queryKey: ["games"] })
      handleClose()
      router.push(`/games/${data.game_id}`)
    },
    onError: (error) => {
      toast({
        title: 'Failed to create game',
        description: error.message,
        variant: 'destructive',
      })
    },
  })

  const handleClose = () => {
    setGameId('')
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
        description: 'Please enter a valid game ID.',
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

    const request: CreateLobbyRequest = {
      player_slots: slots,
      map_width: parseInt(mapWidth) || 20,
      map_height: parseInt(mapHeight) || 20,
      seed: parseInt(seed) || 42,
    }

    createLobbyMutation.mutate({ gameId: gameId.trim(), request })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create New Game</DialogTitle>
          <DialogDescription>
            Set up a game lobby. Players will join before the game starts.
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
