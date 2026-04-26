'use client'

import { useMemo, useState } from 'react'
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
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { setGameCredentials } from '@/lib/game-auth'
import { useToast } from '@/hooks/use-toast'
import type { CreateLobbyRequest, SlotConfigRequest } from '@/types/game'

interface CreateGameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type SlotOverride = {
  type: 'human' | 'agent'
  name: string
}

type SlotDraft = SlotOverride

function reconcileSlots(
  count: number,
  creatorSeated: boolean,
  creator: string,
  overrides: Record<number, SlotOverride>,
): SlotDraft[] {
  // Slot rows are derived from the current state (count + creator
  // toggle + per-slot user overrides). The user's edits are kept in
  // ``overrides``; everything else is computed.
  const next: SlotDraft[] = []
  for (let i = 0; i < count; i++) {
    const override = overrides[i]
    if (override) {
      // If creator is now unseated, clear the slot that was implicitly
      // taken by the creator (so the name doesn't accidentally pin the
      // slot to the unseated creator).
      if (override.type === 'human' && override.name === creator && !creatorSeated) {
        next.push({ type: 'human', name: '' })
      } else {
        next.push({ ...override })
      }
    } else if (i === 0 && creatorSeated) {
      next.push({ type: 'human', name: creator })
    } else {
      next.push({ type: 'human', name: '' })
    }
  }
  return next
}

export function CreateGameDialog({ open, onOpenChange }: CreateGameDialogProps) {
  const [gameId, setGameId] = useState('')
  const [playerId, setPlayerId] = useState('')
  const [playerSlots, setPlayerSlots] = useState('2')
  const [creatorSeated, setCreatorSeated] = useState(true)
  const [slotOverrides, setSlotOverrides] = useState<Record<number, SlotOverride>>({})
  const [mapWidth, setMapWidth] = useState('20')
  const [mapHeight, setMapHeight] = useState('20')
  const [seed, setSeed] = useState('42')

  const { toast } = useToast()
  const queryClient = useQueryClient()
  const router = useRouter()

  // Slot rows are derived state — computed from playerSlots / creatorSeated
  // / playerId plus per-slot user overrides. Keeping this as a memo avoids
  // the cascading-render anti-pattern that ``useEffect(() => setSlots(…))``
  // would introduce.
  const slots = useMemo(() => {
    const desired = Math.max(2, Math.min(8, parseInt(playerSlots) || 0))
    return reconcileSlots(desired, creatorSeated, playerId.trim(), slotOverrides)
  }, [playerSlots, creatorSeated, playerId, slotOverrides])

  const updateSlot = (index: number, patch: Partial<SlotOverride>) => {
    setSlotOverrides((prev) => {
      const current = prev[index] ?? slots[index] ?? { type: 'human', name: '' }
      return { ...prev, [index]: { ...current, ...patch } }
    })
  }

  const validation = useMemo(() => {
    const errors: string[] = []
    if (!gameId.trim()) errors.push('Game ID required')
    if (creatorSeated && !playerId.trim()) errors.push('Display name required when seated')
    const agentNames = slots.filter((s) => s.type === 'agent').map((s) => s.name.trim())
    if (agentNames.some((n) => !n)) errors.push('Every Agent slot needs a name')
    const seen = new Set<string>()
    for (const name of agentNames) {
      if (seen.has(name)) {
        errors.push(`Agent name "${name}" is duplicated`)
        break
      }
      seen.add(name)
    }
    if (creatorSeated && playerId.trim() && agentNames.includes(playerId.trim())) {
      errors.push("Your display name can't match an Agent slot name")
    }
    return errors
  }, [gameId, playerId, creatorSeated, slots])

  const createLobbyMutation = useMutation({
    mutationFn: ({ gameId, request }: { gameId: string; request: CreateLobbyRequest }) =>
      api.createLobby(gameId, request),
    onSuccess: ({ game, api_key }) => {
      // For seated creators, stash the per-game key so subsequent
      // gameplay calls authenticate. For all-Agent owners (api_key
      // null) we still set the displayed playerId for "is creator?"
      // checks even though no per-game key exists.
      if (api_key) {
        setGameCredentials(game.game_id, {
          apiKey: api_key,
          playerId: game.creator ?? playerId,
        })
      } else if (game.creator) {
        setGameCredentials(game.game_id, {
          apiKey: '',
          playerId: game.creator,
        })
      }
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
    setCreatorSeated(true)
    setSlotOverrides({})
    setMapWidth('20')
    setMapHeight('20')
    setSeed('42')
    onOpenChange(false)
  }

  const handleSubmit = () => {
    if (validation.length > 0) {
      toast({
        title: 'Fix lobby configuration',
        description: validation[0],
        variant: 'destructive',
      })
      return
    }

    const slotCount = parseInt(playerSlots)
    if (isNaN(slotCount) || slotCount < 2 || slotCount > 8) {
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

    const slotConfigs: SlotConfigRequest[] = slots.map((slot) => ({
      type: slot.type,
      name: slot.name.trim() || null,
    }))

    const request: CreateLobbyRequest = {
      player_id: playerId.trim() || (creatorSeated ? '' : '__owner__'),
      player_slots: slotCount,
      map_width: width,
      map_height: height,
      seed: parseInt(seed) || 42,
      creator_seated: creatorSeated,
      slots: slotConfigs,
    }

    createLobbyMutation.mutate({ gameId: gameId.trim(), request })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create New Lobby</DialogTitle>
          <DialogDescription>
            Configure each slot. Agent slots get their own API key on create — copy
            them out of the lobby before pressing Start.
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

          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <Label htmlFor="creatorSeated" className="cursor-pointer">
                I&apos;ll take a slot
              </Label>
              <p className="text-xs text-muted-foreground">
                Off → owner-only / all-Agent game.
              </p>
            </div>
            <Switch
              id="creatorSeated"
              checked={creatorSeated}
              onCheckedChange={setCreatorSeated}
            />
          </div>

          {creatorSeated && (
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
                Auto-fills slot 0. You can move it to a different slot below.
              </p>
            </div>
          )}

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

          <div className="space-y-2">
            <Label>Slots</Label>
            {slots.map((slot, i) => {
              const isCreatorSlot =
                creatorSeated &&
                slot.type === 'human' &&
                slot.name.trim() !== '' &&
                slot.name.trim() === playerId.trim()
              return (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded-lg border p-2"
                  data-testid={`create-slot-${i}`}
                >
                  <span className="text-xs text-muted-foreground w-6">{i}</span>
                  <select
                    value={slot.type}
                    onChange={(e) => {
                      const value = e.target.value as 'human' | 'agent'
                      updateSlot(i, {
                        type: value,
                        name: value === 'agent' ? slot.name : '',
                      })
                    }}
                    className="w-28 h-9 rounded-md border border-input bg-background px-2 text-sm"
                    data-testid={`create-slot-${i}-type`}
                  >
                    <option value="human">Human</option>
                    <option value="agent">Agent</option>
                  </select>
                  {slot.type === 'agent' ? (
                    <Input
                      value={slot.name}
                      onChange={(e) => updateSlot(i, { name: e.target.value })}
                      placeholder="Agent name"
                      maxLength={64}
                      className="flex-1"
                      data-testid={`create-slot-${i}-name`}
                    />
                  ) : (
                    <span className="flex-1 text-sm text-muted-foreground italic">
                      {isCreatorSlot ? `You (${slot.name})` : 'Open / invite-only'}
                    </span>
                  )}
                </div>
              )
            })}
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

          {validation.length > 0 && (
            <p className="text-xs text-destructive">{validation[0]}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={createLobbyMutation.isPending || validation.length > 0}
          >
            {createLobbyMutation.isPending ? 'Creating...' : 'Create Lobby'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
