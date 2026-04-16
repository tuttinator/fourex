'use client'

import { useParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { api, queryKeys, getPlayerColor } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ArrowLeft,
  Eye,
  Loader2,
  AlertCircle,
  Play,
  Users,
  LogIn,
  LogOut,
  Map,
  Hash,
  Clock,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

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

function getAuthPlayerId(): string | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('auth_token')
  if (!token || !token.startsWith('player_')) return null
  return token.slice(7)
}

export default function GameDetailPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const currentPlayer = getAuthPlayerId()

  const { data: game, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: 5000,
  })

  const joinMutation = useMutation({
    mutationFn: () => api.joinGame(gameId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ["games"] })
      toast({ title: 'Joined game', description: `You joined ${gameId}.` })
    },
    onError: (error) => {
      toast({ title: 'Failed to join', description: error.message, variant: 'destructive' })
    },
  })

  const leaveMutation = useMutation({
    mutationFn: () => api.leaveGame(gameId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ["games"] })
      toast({ title: 'Left game', description: `You left ${gameId}.` })
    },
    onError: (error) => {
      toast({ title: 'Failed to leave', description: error.message, variant: 'destructive' })
    },
  })

  const startMutation = useMutation({
    mutationFn: () => api.startGame(gameId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ["games"] })
      toast({ title: 'Game started', description: `${gameId} is now active!` })
    },
    onError: (error) => {
      toast({ title: 'Failed to start', description: error.message, variant: 'destructive' })
    },
  })

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

  const isCreator = currentPlayer === game.creator
  const isInGame = currentPlayer !== null && game.players.includes(currentPlayer)
  const isFull = game.players.length >= game.player_slots
  const canStart = isCreator && isFull && game.status === 'waiting'

  // If game is active or ended, show redirect to observe
  if (game.status === 'active' || game.status === 'ended') {
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

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-2xl">{game.game_id}</CardTitle>
              <Badge variant={statusVariant(game.status)}>{game.status}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Turn:</span>{' '}
                <span className="font-medium">{game.turn} / {game.max_turns}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Players:</span>{' '}
                <span className="font-medium">{game.players.length}</span>
              </div>
              {game.winner && (
                <div className="col-span-2">
                  <span className="text-muted-foreground">Winner:</span>{' '}
                  <span className="font-medium">{game.winner}</span>
                  {game.victory_type && (
                    <span className="text-muted-foreground"> ({game.victory_type})</span>
                  )}
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <Button asChild className="flex-1">
                <Link href={`/games/${game.game_id}/observe`}>
                  <Eye className="h-4 w-4 mr-2" />
                  Observe
                </Link>
              </Button>
              <Button asChild variant="outline" className="flex-1">
                <Link href={`/games/${game.game_id}/replay`}>
                  <Play className="h-4 w-4 mr-2" />
                  Replay
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Waiting room view
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
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
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
          <CardContent className="pt-6">
            {!currentPlayer ? (
              <p className="text-sm text-muted-foreground text-center">
                Set an auth token (player_NAME) in localStorage to join this game.
              </p>
            ) : (
              <div className="flex gap-2">
                {!isInGame && !isFull && (
                  <Button
                    onClick={() => joinMutation.mutate()}
                    disabled={joinMutation.isPending}
                    className="flex-1"
                  >
                    <LogIn className="h-4 w-4 mr-2" />
                    {joinMutation.isPending ? 'Joining...' : 'Join Game'}
                  </Button>
                )}
                {isInGame && !isCreator && (
                  <Button
                    variant="outline"
                    onClick={() => leaveMutation.mutate()}
                    disabled={leaveMutation.isPending}
                    className="flex-1"
                  >
                    <LogOut className="h-4 w-4 mr-2" />
                    {leaveMutation.isPending ? 'Leaving...' : 'Leave Game'}
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
                {!isInGame && isFull && (
                  <p className="text-sm text-muted-foreground text-center w-full">
                    This game is full.
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
