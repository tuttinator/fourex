'use client'

import { useParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import Link from 'next/link'
import { api, queryKeys, getPlayerColor } from '@/lib/api'
import { ObservationView } from '@/components/observation-view'
import { GameplayView } from '@/components/gameplay-view'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  Play,
  Users,
  LogIn,
  LogOut,
  Map,
  Hash,
  Clock,
  Link as LinkIcon,
  Check,
  Bot,
  KeyRound,
  Copy,
  AlertTriangle,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useLobbyEvents } from '@/hooks/use-lobby-events'
import {
  clearGameCredentials,
  getGameApiKey,
  getGamePlayerId,
  setGameCredentials,
} from '@/lib/game-auth'

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'active': return 'default'
    case 'waiting': return 'secondary'
    case 'ended': return 'outline'
    default: return 'secondary'
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function GameDetailPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [joinPlayerId, setJoinPlayerId] = useState('')
  const [copied, setCopied] = useState(false)
  const [apiKeyCopied, setApiKeyCopied] = useState(false)
  const [copiedSlotIndex, setCopiedSlotIndex] = useState<number | null>(null)
  const [confirmRegenSlot, setConfirmRegenSlot] = useState<number | null>(null)

  // Per-game player id is stored in localStorage when we create/join.
  // Re-read on every render so a fresh join reflects immediately.
  const currentPlayer =
    typeof window !== 'undefined' ? getGamePlayerId(gameId) : null

  // Live lobby events: the hook invalidates the game-detail query on
  // every lobby.* broadcast. We keep a polling fallback so observers
  // without an API key (invite recipients who haven't joined yet) still
  // see the roster update, and so a WS drop degrades gracefully.
  const { status: wsStatus } = useLobbyEvents(gameId)
  const pollingInterval = wsStatus === 'open' ? 15000 : 5000

  const { data: game, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: pollingInterval,
  })

  const joinMutation = useMutation({
    mutationFn: (playerId: string) =>
      api.joinLobby(gameId, { player_id: playerId }),
    onSuccess: ({ game, api_key }) => {
      setGameCredentials(game.game_id, {
        apiKey: api_key ?? '',
        playerId: joinPlayerId.trim(),
      })
      setJoinPlayerId('')
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Joined lobby', description: `Seated as ${joinPlayerId.trim()}.` })
    },
    onError: (err) => {
      toast({ title: 'Failed to join', description: err.message, variant: 'destructive' })
    },
  })

  const leaveMutation = useMutation({
    mutationFn: () => api.leaveGame(gameId),
    onSuccess: () => {
      clearGameCredentials(gameId)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Left lobby', description: `You left ${gameId}.` })
    },
    onError: (err) => {
      toast({ title: 'Failed to leave', description: err.message, variant: 'destructive' })
    },
  })

  const startMutation = useMutation({
    mutationFn: async () => {
      // Owners running an all-Agent game have no per-game API key, so
      // ``startGame`` (per-game-key auth) won't work. The BFF-routed
      // ``startGameAsOwner`` accepts the Auth.js JWT instead. Pick the
      // right endpoint based on whether we hold a key for this game.
      const playerId = getGamePlayerId(gameId)
      const hasGameplayKey =
        playerId !== null && game?.players.includes(playerId) === true
      return hasGameplayKey
        ? api.startGame(gameId)
        : api.startGameAsOwner(gameId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Game started', description: `${gameId} is now active!` })
    },
    onError: (err) => {
      toast({ title: 'Failed to start', description: err.message, variant: 'destructive' })
    },
  })

  const regenerateMutation = useMutation({
    mutationFn: (slotIndex: number) => api.regenerateSlotKey(gameId, slotIndex),
    onSuccess: () => {
      setConfirmRegenSlot(null)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({ title: 'Key regenerated', description: 'The previous key is now invalid.' })
    },
    onError: (err) => {
      setConfirmRegenSlot(null)
      toast({ title: 'Regenerate failed', description: err.message, variant: 'destructive' })
    },
  })

  const copySlotKey = async (slotIndex: number, plaintext: string) => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopiedSlotIndex(slotIndex)
      toast({
        title: `Slot ${slotIndex} key copied`,
        description: 'Paste it into your agent now — it disappears when the game starts.',
      })
      setTimeout(() => setCopiedSlotIndex((prev) => (prev === slotIndex ? null : prev)), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the key manually and copy.',
        variant: 'destructive',
      })
    }
  }

  const copyApiKey = async (apiKey: string) => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(apiKey)
      setApiKeyCopied(true)
      toast({
        title: 'API key copied',
        description: 'Paste it into your MCP-enabled agent (e.g. Claude Code).',
      })
      setTimeout(() => setApiKeyCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the key manually and copy.',
        variant: 'destructive',
      })
    }
  }

  const copyInviteLink = async () => {
    if (typeof window === 'undefined') return
    const url = `${window.location.origin}/games/${gameId}`
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      toast({ title: 'Invite link copied', description: url })
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Copy the URL from your address bar.',
        variant: 'destructive',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p>Loading game...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-4">Failed to load game: {error.message}</p>
          <div className="flex gap-2 justify-center">
            <Button variant="outline" onClick={() => refetch()}>Retry</Button>
            <Button asChild variant="outline">
              <Link href="/games">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Games
              </Link>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (!game) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Game not found</p>
          <Button asChild variant="outline">
            <Link href="/games">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Games
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  // Active or ended: show observation view with header
  if (game.status === 'active' || game.status === 'ended') {
    return (
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button asChild variant="ghost" size="sm">
                <Link href="/games">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Back
                </Link>
              </Button>
              <h1 className="text-xl font-semibold">{game.game_id}</h1>
              <Badge variant={statusVariant(game.status)}>{game.status}</Badge>
              {game.winner && (
                <span className="text-sm text-muted-foreground">
                  Winner: {game.winner}
                  {game.victory_type && ` (${game.victory_type})`}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Button asChild variant="outline" size="sm">
                <Link href={`/games/${game.game_id}/diplomacy`}>
                  <Users className="h-4 w-4 mr-2" />
                  Diplomacy
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link href={`/games/${game.game_id}/replay`}>
                  <Play className="h-4 w-4 mr-2" />
                  Replay
                </Link>
              </Button>
            </div>
          </div>
        </div>

        {/* Seated players in an active game get the gameplay controls;
            observers and spectators on ended games drop to the read-only
            observation view. */}
        <div className="flex-1 overflow-hidden">
          {game.status === 'active' &&
          currentPlayer &&
          game.players.includes(currentPlayer) ? (
            <GameplayView gameId={gameId} currentPlayer={currentPlayer} />
          ) : (
            <ObservationView gameId={gameId} />
          )}
        </div>
      </div>
    )
  }

  // Waiting room view
  const isCreator = currentPlayer !== null && currentPlayer === game.creator
  const isInGame = currentPlayer !== null && game.players.includes(currentPlayer)
  // Phase 3: a slot is "ready" when it has a name (Human seated, or
  // Agent name fixed at create) AND for Agents also has a minted
  // key. That's the same check the backend's start_game guard runs.
  const slotsArr = game.slots && game.slots.length > 0 ? game.slots : []
  const allSlotsReady =
    slotsArr.length === game.player_slots &&
    slotsArr.every((s) => {
      if (!s.name) return false
      if (s.type === 'agent' && !s.player_api_key_id) return false
      return true
    })
  const isFull = slotsArr.length > 0
    ? allSlotsReady
    : game.players.length >= game.player_slots
  const canStart = isCreator && isFull && game.status === 'waiting'
  const agentSlotsWithKeys = slotsArr.filter(
    (s) => s.type === 'agent' && s.plaintext_key,
  )

  return (
    <div className="container mx-auto px-4 py-8 max-w-3xl">
      <div className="mb-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/games">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Games
          </Link>
        </Button>
      </div>

      <div className="space-y-6">
        {/* Game Header */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-2xl">{game.game_id}</CardTitle>
              <Badge variant="secondary">Waiting for players</Badge>
            </div>
            {game.creator && (
              <p className="text-sm text-muted-foreground">
                Created by {game.creator}
              </p>
            )}
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
              <div className="flex items-center gap-2">
                <Map className="h-4 w-4 text-muted-foreground" />
                <span>{game.map_width}x{game.map_height}</span>
              </div>
              <div className="flex items-center gap-2">
                <Hash className="h-4 w-4 text-muted-foreground" />
                <span>Seed: {game.seed}</span>
              </div>
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-muted-foreground" />
                <span>{game.player_slots} slots</span>
              </div>
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span>{formatDate(game.created_at)}</span>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={copyInviteLink}
              className="w-full"
            >
              {copied ? (
                <Check className="h-4 w-4 mr-2" />
              ) : (
                <LinkIcon className="h-4 w-4 mr-2" />
              )}
              {copied ? 'Copied!' : 'Copy invite link'}
            </Button>

          </CardContent>
        </Card>

        {agentSlotsWithKeys.length > 0 && (
          <Card data-testid="per-slot-agent-keys-panel">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-4 w-4" />
                Agent slot API keys
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Hand each Agent slot&apos;s key to its agent. Keys disappear from
                this page the instant you press Start — copy them now or hit
                <span className="font-medium"> Regenerate</span> to mint a fresh
                one (the previous key stops working).
              </p>
              {agentSlotsWithKeys.map((slot) => (
                <div
                  key={slot.slot_index}
                  className="rounded-lg border p-3 space-y-2"
                  data-testid={`agent-slot-key-${slot.slot_index}`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs text-muted-foreground">
                        Slot {slot.slot_index} · Agent
                      </span>
                      <p className="font-medium text-sm">{slot.name}</p>
                    </div>
                    {confirmRegenSlot === slot.slot_index ? (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfirmRegenSlot(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => regenerateMutation.mutate(slot.slot_index)}
                          disabled={regenerateMutation.isPending}
                          data-testid={`agent-slot-key-${slot.slot_index}-regenerate-confirm`}
                        >
                          {regenerateMutation.isPending ? 'Working...' : 'Confirm'}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setConfirmRegenSlot(slot.slot_index)}
                        data-testid={`agent-slot-key-${slot.slot_index}-regenerate`}
                      >
                        Regenerate
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={slot.plaintext_key ?? ''}
                      readOnly
                      onFocus={(e) => e.currentTarget.select()}
                      className="font-mono text-xs"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        slot.plaintext_key &&
                        copySlotKey(slot.slot_index, slot.plaintext_key)
                      }
                      data-testid={`agent-slot-key-${slot.slot_index}-copy`}
                    >
                      {copiedSlotIndex === slot.slot_index ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {(() => {
          // Phase 1 hand-off panel for the seated creator's own
          // per-game key. The backend echoes the key on a per-game-key
          // bearer; the BFF-routed lobby fetch sends the JWT instead,
          // so we fall back to the localStorage copy stashed when this
          // user created the lobby.
          const seatedCreator =
            currentPlayer !== null && game.creator === currentPlayer
          if (!seatedCreator) return null
          const localKey =
            typeof window !== 'undefined' ? getGameApiKey(gameId) : null
          const apiKey = game.api_key || localKey || null
          if (!apiKey) return null
          return (
          <Card data-testid="agent-api-key-panel">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-4 w-4" />
                Hand off to an MCP agent
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Point your agent at the live MCP endpoint (
                <code className="mx-1 px-1 py-0.5 rounded bg-muted text-foreground">
                  https://mcp.parley.quest/
                </code>
                , streamable-http) and paste this game URL plus the API key
                below. In Claude Code, the
                <code className="mx-1 px-1 py-0.5 rounded bg-muted text-foreground">
                  /play-parley
                </code>
                skill walks through the handshake.
              </p>
              <div>
                <Label htmlFor="agent-api-key" className="text-xs flex items-center gap-1">
                  <KeyRound className="h-3 w-3" />
                  Per-game API key
                </Label>
                <div className="mt-1 flex gap-2">
                  <Input
                    id="agent-api-key"
                    value={apiKey}
                    readOnly
                    onFocus={(e) => e.currentTarget.select()}
                    className="font-mono text-xs"
                    data-testid="agent-api-key-input"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => copyApiKey(apiKey)}
                    data-testid="agent-api-key-copy"
                  >
                    {apiKeyCopied ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                    <span className="ml-2">{apiKeyCopied ? 'Copied' : 'Copy'}</span>
                  </Button>
                </div>
              </div>
              <p className="text-xs text-amber-600 dark:text-amber-500 flex items-start gap-1">
                <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                <span>
                  Copy the key now — once the game starts it disappears from this
                  page. If you lose it, you can mint a fresh lobby instead.
                </span>
              </p>
            </CardContent>
          </Card>
          )
        })()}

        {/* Player Slots */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              Players ({game.players.length}/{game.player_slots})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {(() => {
                // Prefer the Phase 2 ``slots`` array — it's the canonical
                // shape and also lets us render type badges. When the
                // response predates the column (legacy server, null
                // column), synthesise an all-Human view from
                // ``players`` so the UI degrades cleanly.
                const slots: { slot_index: number; type: 'human' | 'agent'; name: string | null }[] =
                  game.slots && game.slots.length > 0
                    ? game.slots.map((s) => ({
                        slot_index: s.slot_index,
                        type: s.type,
                        name: s.name,
                      }))
                    : Array.from({ length: game.player_slots }, (_, i) => ({
                        slot_index: i,
                        type: 'human' as const,
                        name: game.players[i] ?? null,
                      }))
                return slots.map((slot) => {
                  const i = slot.slot_index
                  const player = slot.name
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between p-3 rounded-lg border"
                      data-testid={`lobby-slot-${i}`}
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: player ? getPlayerColor(i) : '#6b7280' }}
                        />
                        {player ? (
                          <span className="font-medium">{player}</span>
                        ) : (
                          <span className="text-muted-foreground italic">Empty slot</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs capitalize">
                          {slot.type}
                        </Badge>
                        {player && i === 0 && game.creator === player && (
                          <Badge variant="outline" className="text-xs">Creator</Badge>
                        )}
                      </div>
                    </div>
                  )
                })
              })()}
            </div>
          </CardContent>
        </Card>

        {/* Actions */}
        <Card>
          <CardContent className="pt-6 space-y-4">
            {!isInGame && !isFull && (
              <div className="space-y-3">
                <div>
                  <Label htmlFor="joinPlayerId">Your display name in this game</Label>
                  <Input
                    id="joinPlayerId"
                    value={joinPlayerId}
                    onChange={(e) => setJoinPlayerId(e.target.value)}
                    placeholder="bob"
                    className="mt-1"
                    maxLength={64}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Must be unique within this lobby and not already taken.
                  </p>
                </div>
                <Button
                  onClick={() => {
                    const trimmed = joinPlayerId.trim()
                    if (!trimmed) {
                      toast({
                        title: 'Display name required',
                        description: 'Pick a name to play under.',
                        variant: 'destructive',
                      })
                      return
                    }
                    joinMutation.mutate(trimmed)
                  }}
                  disabled={joinMutation.isPending}
                  className="w-full"
                >
                  <LogIn className="h-4 w-4 mr-2" />
                  {joinMutation.isPending ? 'Joining...' : 'Join Lobby'}
                </Button>
                <p className="text-xs text-muted-foreground text-center">
                  You must be signed in to join. If nothing happens, check you&apos;re signed in.
                </p>
              </div>
            )}

            {isInGame && (
              <div className="flex gap-2">
                {!isCreator && (
                  <Button
                    variant="outline"
                    onClick={() => leaveMutation.mutate()}
                    disabled={leaveMutation.isPending}
                    className="flex-1"
                  >
                    <LogOut className="h-4 w-4 mr-2" />
                    {leaveMutation.isPending ? 'Leaving...' : 'Leave Lobby'}
                  </Button>
                )}
                {isCreator && (
                  <Button
                    onClick={() => startMutation.mutate()}
                    disabled={!canStart || startMutation.isPending}
                    className="flex-1"
                  >
                    <Play className="h-4 w-4 mr-2" />
                    {startMutation.isPending
                      ? 'Starting...'
                      : canStart
                        ? 'Start Game'
                        : 'Waiting for slots'}
                  </Button>
                )}
              </div>
            )}

            {/* All-Agent (owner-only) creators aren't in ``players`` so the
                ``isInGame`` branch above doesn't fire — surface the Start
                control here instead. */}
            {!isInGame && isCreator && (
              <Button
                onClick={() => startMutation.mutate()}
                disabled={!canStart || startMutation.isPending}
                className="w-full"
                data-testid="owner-start-button"
              >
                <Play className="h-4 w-4 mr-2" />
                {startMutation.isPending
                  ? 'Starting...'
                  : canStart
                    ? 'Start Game'
                    : 'Waiting for slots'}
              </Button>
            )}

            {!isInGame && !isCreator && isFull && (
              <p className="text-sm text-muted-foreground text-center">
                This lobby is full.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
