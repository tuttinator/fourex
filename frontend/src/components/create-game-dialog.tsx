'use client'

import { useState } from 'react'
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
import { Badge } from '@/components/ui/badge'
import { api, queryKeys } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'
import { X, Plus } from 'lucide-react'
import type { CreateGameRequest } from '@/types/game'

interface CreateGameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateGameDialog({ open, onOpenChange }: CreateGameDialogProps) {
  const [gameId, setGameId] = useState('')
  const [players, setPlayers] = useState<string[]>(['agent_1', 'agent_2'])
  const [newPlayer, setNewPlayer] = useState('')
  const [seed, setSeed] = useState('42')
  
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const createGameMutation = useMutation({
    mutationFn: ({ gameId, request }: { gameId: string; request: CreateGameRequest }) =>
      api.createGame(gameId, request),
    onSuccess: () => {
      toast({
        title: 'Game created successfully',
        description: `Game ${gameId} has been created with ${players.length} players.`,
      })
      queryClient.invalidateQueries({ queryKey: queryKeys.games })
      handleClose()
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
    setPlayers(['agent_1', 'agent_2'])
    setNewPlayer('')
    setSeed('42')
    onOpenChange(false)
  }

  const addPlayer = () => {
    if (newPlayer.trim() && !players.includes(newPlayer.trim()) && players.length < 8) {
      setPlayers([...players, newPlayer.trim()])
      setNewPlayer('')
    }
  }

  const removePlayer = (playerToRemove: string) => {
    if (players.length > 2) {
      setPlayers(players.filter(p => p !== playerToRemove))
    }
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

    if (players.length < 2 || players.length > 8) {
      toast({
        title: 'Invalid player count',
        description: 'Games require 2-8 players.',
        variant: 'destructive',
      })
      return
    }

    const request: CreateGameRequest = {
      players,
      seed: parseInt(seed) || 42,
    }

    createGameMutation.mutate({ gameId: gameId.trim(), request })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create New Game</DialogTitle>
          <DialogDescription>
            Set up a new 4X strategy game for AI agents to compete.
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
            <Label>Players ({players.length}/8)</Label>
            <div className="flex flex-wrap gap-2 mt-1 mb-2">
              {players.map((player) => (
                <Badge key={player} variant="secondary" className="pr-1">
                  {player}
                  {players.length > 2 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4 ml-1 hover:bg-destructive hover:text-destructive-foreground"
                      onClick={() => removePlayer(player)}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  )}
                </Badge>
              ))}
            </div>
            
            {players.length < 8 && (
              <div className="flex gap-2">
                <Input
                  value={newPlayer}
                  onChange={(e) => setNewPlayer(e.target.value)}
                  placeholder="agent_name"
                  onKeyDown={(e) => e.key === 'Enter' && addPlayer()}
                />
                <Button onClick={addPlayer} size="icon" variant="outline">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            )}
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
            disabled={createGameMutation.isPending}
          >
            {createGameMutation.isPending ? 'Creating...' : 'Create Game'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}