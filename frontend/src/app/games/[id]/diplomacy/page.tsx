'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, AlertCircle, Loader2, Swords, Skull, Handshake } from 'lucide-react'

import { api, queryKeys, getPlayerColor } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import type {
  DiplomacyEvent,
  DiplomacyRelation,
  DiplomacyStateResponse,
  PlayerId,
} from '@/types/game'

function getAuthPlayerId(): PlayerId | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('auth_token')
  if (!token || !token.startsWith('player_')) return null
  return token.slice(7)
}

function relationLabel(state: DiplomacyRelation['state']): string {
  switch (state) {
    case 'war':
      return 'War'
    case 'alliance':
      return 'Alliance'
    case 'peace':
      return 'Peace'
  }
}

function relationVariant(
  state: DiplomacyRelation['state'],
): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (state) {
    case 'war':
      return 'destructive'
    case 'alliance':
      return 'default'
    case 'peace':
      return 'secondary'
  }
}

function findRelation(
  relations: DiplomacyRelation[],
  a: PlayerId,
  b: PlayerId,
): DiplomacyRelation['state'] {
  const match = relations.find(
    (r) =>
      (r.player_a === a && r.player_b === b) ||
      (r.player_a === b && r.player_b === a),
  )
  return match?.state ?? 'peace'
}

function eventStyle(event: DiplomacyEvent): {
  label: string
  className: string
  Icon: typeof Swords
} {
  switch (event.type) {
    case 'treacherous_attack':
      return {
        label: 'Treacherous attack',
        // strong destructive accent for betrayal
        className: 'border-destructive bg-destructive/10 text-destructive',
        Icon: Skull,
      }
    case 'war_declared':
      return {
        label:
          event.payload?.cause === 'treacherous_attack'
            ? 'War (from betrayal)'
            : 'War declared',
        className: 'border-orange-500 bg-orange-500/10 text-orange-700 dark:text-orange-400',
        Icon: Swords,
      }
    default:
      return {
        label: event.type.replace(/_/g, ' '),
        className: 'border-border bg-muted/40 text-foreground',
        Icon: Handshake,
      }
  }
}

export default function DiplomacyPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const currentPlayer = getAuthPlayerId()

  const {
    data: gameDetail,
  } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
  })

  const {
    data: diplomacy,
    isLoading,
    error,
    refetch,
  } = useQuery<DiplomacyStateResponse>({
    queryKey: queryKeys.diplomacy(gameId),
    queryFn: () => api.getDiplomacy(gameId),
    refetchInterval: 5000,
    enabled: Boolean(currentPlayer),
  })

  const declareWar = useMutation({
    mutationFn: (target: PlayerId) => api.declareWar(gameId, target),
    onSuccess: (_, target) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      toast({
        title: 'War queued',
        description: `Declaration against ${target} will resolve at end of turn.`,
      })
    },
    onError: (err, target) => {
      toast({
        title: `Could not declare war on ${target}`,
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  if (!currentPlayer) {
    return (
      <div className="container mx-auto px-4 py-10">
        <Card>
          <CardHeader>
            <CardTitle>Sign in required</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Diplomacy is per-player. Sign in (set an auth token) before opening
              this page so we can show your relations and event feed.
            </p>
            <Button asChild variant="outline" className="mt-4">
              <Link href={`/games/${gameId}`}>
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to game
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p>Loading diplomacy...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-4">
            Failed to load diplomacy: {error.message}
          </p>
          <div className="flex gap-2 justify-center">
            <Button variant="outline" onClick={() => refetch()}>Retry</Button>
            <Button asChild variant="outline">
              <Link href={`/games/${gameId}`}>
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to game
              </Link>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const discovered = diplomacy?.discovered ?? []
  const relations = diplomacy?.relations ?? []
  const events = diplomacy?.events ?? []
  const allPlayers = gameDetail?.players ?? []
  const currentPlayerIndex = allPlayers.indexOf(currentPlayer)

  return (
    <div className="min-h-screen flex flex-col">
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button asChild variant="ghost" size="sm">
              <Link href={`/games/${gameId}`}>
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to game
              </Link>
            </Button>
            <h1 className="text-xl font-semibold">Diplomacy</h1>
            <Badge variant="outline">{gameId}</Badge>
            <span className="text-sm text-muted-foreground">
              Turn {diplomacy?.turn ?? '?'}
            </span>
          </div>
          <div
            className="text-sm text-muted-foreground flex items-center gap-2"
            data-testid="current-player"
          >
            Acting as:
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{
                backgroundColor:
                  currentPlayerIndex >= 0 ? getPlayerColor(currentPlayerIndex) : '#888',
              }}
            />
            <span className="font-mono">{currentPlayer}</span>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-4 py-6 grid gap-6 md:grid-cols-2 flex-1">
        <Card>
          <CardHeader>
            <CardTitle>Relations</CardTitle>
          </CardHeader>
          <CardContent>
            {discovered.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                You have not yet discovered any other players. Move a unit
                within sight of an opponent to open diplomatic channels.
              </p>
            ) : (
              <ul className="space-y-3">
                {discovered.map((target) => {
                  const state = findRelation(relations, currentPlayer, target)
                  const targetIndex = allPlayers.indexOf(target)
                  return (
                    <li
                      key={target}
                      className="flex items-center justify-between gap-3 border rounded-md px-3 py-2"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className="inline-block h-3 w-3 rounded-full"
                          style={{
                            backgroundColor:
                              targetIndex >= 0 ? getPlayerColor(targetIndex) : '#888',
                          }}
                        />
                        <span className="font-mono">{target}</span>
                        <Badge variant={relationVariant(state)}>
                          {relationLabel(state)}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-2">
                        {state !== 'war' && (
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={declareWar.isPending}
                            onClick={() => declareWar.mutate(target)}
                          >
                            <Swords className="h-4 w-4 mr-2" />
                            Declare war
                          </Button>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>World events</CardTitle>
          </CardHeader>
          <CardContent>
            {events.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No diplomatic events yet. Declarations of war and treacherous
                attacks will appear here as they happen.
              </p>
            ) : (
              <ScrollArea className="max-h-[60vh] pr-2">
                <ul className="space-y-2">
                  {[...events]
                    .sort((a, b) => b.id - a.id)
                    .map((event) => {
                      const { label, className, Icon } = eventStyle(event)
                      return (
                        <li
                          key={event.id}
                          className={`border-l-4 rounded px-3 py-2 ${className}`}
                          data-event-type={event.type}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4" />
                              <span className="font-medium">{label}</span>
                            </div>
                            <span className="text-xs opacity-70">
                              Turn {event.turn}
                            </span>
                          </div>
                          <div className="text-sm font-mono mt-1">
                            {event.actor}
                            {event.counterparty && (
                              <>
                                <span className="opacity-60"> → </span>
                                {event.counterparty}
                              </>
                            )}
                          </div>
                        </li>
                      )
                    })}
                </ul>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
