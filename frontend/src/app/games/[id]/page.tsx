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
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useLobbyEvents } from '@/hooks/use-lobby-events'
import {
  clearGameCredentials,
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
  const [mcpInviteOpen, setMcpInviteOpen] = useState(false)
  const [mcpAgentName, setMcpAgentName] = useState('')
  const [mcpSnippetCopied, setMcpSnippetCopied] = useState(false)

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
        apiKey: api_key,
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
    mutationFn: () => api.startGame(gameId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Game started', description: `${gameId} is now active!` })
    },
    onError: (err) => {
      toast({ title: 'Failed to start', description: err.message, variant: 'destructive' })
    },
  })

  const mcpSnippet = (() => {
    const name = mcpAgentName.trim() || 'agent'
    return `join_game(game_id="${gameId}", player_name="${name}")`
  })()

  const copyMcpSnippet = async () => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(mcpSnippet)
      setMcpSnippetCopied(true)
      toast({
        title: 'MCP snippet copied',
        description: 'Paste it into your agent (e.g. Claude Code).',
      })
      setTimeout(() => setMcpSnippetCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the snippet manually and copy.',
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
  const isFull = game.players.length >= game.player_slots
  const canStart = isCreator && isFull && game.status === 'waiting'

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

            <div className="mt-3">
              <button
                type="button"
                onClick={() => setMcpInviteOpen((v) => !v)}
                className="flex w-full items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                aria-expanded={mcpInviteOpen}
                data-testid="mcp-invite-toggle"
              >
                {mcpInviteOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                <Bot className="h-4 w-4" />
                <span>Invite an MCP agent</span>
              </button>
              {mcpInviteOpen && (
                <div className="mt-3 space-y-3" data-testid="mcp-invite-panel">
                  <p className="text-xs text-muted-foreground">
                    Paste this into an MCP-enabled client (e.g. Claude Code with the
                    <code className="mx-1 px-1 py-0.5 rounded bg-muted text-foreground">fourex-mcp</code>
                    server configured) to seat an AI agent at this table.
                  </p>
                  <div>
                    <Label htmlFor="mcpAgentName" className="text-xs">
                      Agent display name
                    </Label>
                    <Input
                      id="mcpAgentName"
                      value={mcpAgentName}
                      onChange={(e) => setMcpAgentName(e.target.value)}
                      placeholder="agent"
                      className="mt-1 h-8 text-sm"
                      maxLength={64}
                    />
                  </div>
                  <pre
                    className="text-xs rounded border bg-muted px-3 py-2 overflow-x-auto font-mono"
                    data-testid="mcp-invite-snippet"
                  >
                    {mcpSnippet}
                  </pre>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={copyMcpSnippet}
                    className="w-full"
                    data-testid="mcp-invite-copy"
                  >
                    {mcpSnippetCopied ? (
                      <Check className="h-4 w-4 mr-2" />
                    ) : (
                      <LinkIcon className="h-4 w-4 mr-2" />
                    )}
                    {mcpSnippetCopied ? 'Copied!' : 'Copy MCP tool call'}
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

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
              {Array.from({ length: game.player_slots }, (_, i) => {
                const player = game.players[i]
                return (
                  <div
                    key={i}
                    className="flex items-center justify-between p-3 rounded-lg border"
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
                    {player && i === 0 && game.creator === player && (
                      <Badge variant="outline" className="text-xs">Creator</Badge>
                    )}
                  </div>
                )
              })}
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
                        : `Waiting for ${game.player_slots - game.players.length} more player${game.player_slots - game.players.length !== 1 ? 's' : ''}`}
                  </Button>
                )}
              </div>
            )}

            {!isInGame && isFull && (
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
