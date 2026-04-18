'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  AlertCircle,
  Loader2,
  MessageSquare,
  Send,
  Swords,
  Skull,
  Handshake,
} from 'lucide-react'

import { api, queryKeys, getPlayerColor } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import type {
  DiplomacyEvent,
  DiplomacyMessage,
  DiplomacyRelation,
  DiplomacyStateResponse,
  PlayerId,
} from '@/types/game'
import {
  MESSAGE_BODY_MAX_LENGTH,
  MESSAGES_PER_TURN_LIMIT,
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
        className: 'border-destructive bg-destructive/10 text-destructive',
        Icon: Skull,
      }
    case 'war_declared':
      return {
        label:
          event.payload?.cause === 'treacherous_attack'
            ? 'War (from betrayal)'
            : 'War declared',
        className:
          'border-orange-500 bg-orange-500/10 text-orange-700 dark:text-orange-400',
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

function threadForCounterpart(
  messages: DiplomacyMessage[],
  viewer: PlayerId,
  counterpart: PlayerId,
): DiplomacyMessage[] {
  return messages
    .filter(
      (m) =>
        (m.sender === viewer && m.recipient === counterpart) ||
        (m.sender === counterpart && m.recipient === viewer),
    )
    .sort((a, b) => a.id - b.id)
}

export default function DiplomacyPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const currentPlayer = getAuthPlayerId()

  const { data: gameDetail } = useQuery({
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

  const sendMessage = useMutation({
    mutationFn: ({ recipient, body }: { recipient: PlayerId; body: string }) =>
      api.sendMessage(gameId, recipient, body),
    onSuccess: (_, { recipient }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      setDraft('')
      toast({
        title: 'Message queued',
        description: `It will be delivered to ${recipient} at end of turn.`,
      })
    },
    onError: (err, { recipient }) => {
      toast({
        title: `Could not send message to ${recipient}`,
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const [selectedCounterpart, setSelectedCounterpart] =
    useState<PlayerId | null>(null)
  const [draft, setDraft] = useState('')

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
  const messages = diplomacy?.messages ?? []
  const allPlayers = gameDetail?.players ?? []
  const currentPlayerIndex = allPlayers.indexOf(currentPlayer)

  const gameStatus = gameDetail?.status
  const gameActive = gameStatus === 'active'
  const turnGateReason = !gameActive
    ? `Messages can only be sent while the game is active (status: ${gameStatus ?? 'unknown'}).`
    : null

  const sentThisTurn = messages.filter(
    (m) => m.sender === currentPlayer && m.turn_sent === (diplomacy?.turn ?? 0),
  ).length
  const messagesRemaining = Math.max(
    0,
    MESSAGES_PER_TURN_LIMIT - sentThisTurn,
  )

  const effectiveSelected =
    selectedCounterpart && discovered.includes(selectedCounterpart)
      ? selectedCounterpart
      : discovered[0] ?? null

  const thread = effectiveSelected
    ? threadForCounterpart(messages, currentPlayer, effectiveSelected)
    : []

  const unreadCounts: Record<PlayerId, number> = {}
  for (const c of discovered) {
    unreadCounts[c] = messages.filter(
      (m) => m.sender === c && m.recipient === currentPlayer,
    ).length
  }

  const draftTooLong = draft.length > MESSAGE_BODY_MAX_LENGTH
  const canSend =
    gameActive &&
    Boolean(effectiveSelected) &&
    draft.trim().length > 0 &&
    !draftTooLong &&
    messagesRemaining > 0 &&
    !sendMessage.isPending

  const sendDisabledReason = !gameActive
    ? turnGateReason
    : messagesRemaining <= 0
      ? `You have already sent ${MESSAGES_PER_TURN_LIMIT} messages this turn.`
      : draftTooLong
        ? `Message is ${draft.length} characters; limit is ${MESSAGE_BODY_MAX_LENGTH}.`
        : null

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
                  currentPlayerIndex >= 0
                    ? getPlayerColor(currentPlayerIndex)
                    : '#888',
              }}
            />
            <span className="font-mono">{currentPlayer}</span>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-4 py-6 flex-1 space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
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
                                targetIndex >= 0
                                  ? getPlayerColor(targetIndex)
                                  : '#888',
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

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <MessageSquare className="h-5 w-5" />
                Messages
              </span>
              <span className="text-xs font-normal text-muted-foreground">
                {messagesRemaining} of {MESSAGES_PER_TURN_LIMIT} sends left this
                turn
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {discovered.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Once you discover other players, you will be able to send them
                up to {MESSAGES_PER_TURN_LIMIT} private messages per turn.
              </p>
            ) : (
              <div className="grid gap-4 md:grid-cols-[200px_1fr]">
                <div className="border rounded-md p-2 space-y-1">
                  {discovered.map((counterpart) => {
                    const isSelected = counterpart === effectiveSelected
                    const idx = allPlayers.indexOf(counterpart)
                    const unread = unreadCounts[counterpart] ?? 0
                    return (
                      <button
                        key={counterpart}
                        type="button"
                        onClick={() => setSelectedCounterpart(counterpart)}
                        className={`w-full text-left px-2 py-1 rounded flex items-center gap-2 text-sm ${
                          isSelected
                            ? 'bg-primary/10 font-medium'
                            : 'hover:bg-muted'
                        }`}
                        data-testid={`counterpart-${counterpart}`}
                      >
                        <span
                          className="inline-block h-3 w-3 rounded-full shrink-0"
                          style={{
                            backgroundColor:
                              idx >= 0 ? getPlayerColor(idx) : '#888',
                          }}
                        />
                        <span className="font-mono truncate">{counterpart}</span>
                        {unread > 0 && (
                          <Badge variant="secondary" className="ml-auto">
                            {unread}
                          </Badge>
                        )}
                      </button>
                    )
                  })}
                </div>

                <div className="flex flex-col border rounded-md">
                  {effectiveSelected ? (
                    <>
                      <div className="border-b px-3 py-2 flex items-center justify-between">
                        <div className="text-sm">
                          Thread with{' '}
                          <span className="font-mono">{effectiveSelected}</span>
                        </div>
                        <Badge
                          variant={relationVariant(
                            findRelation(
                              relations,
                              currentPlayer,
                              effectiveSelected,
                            ),
                          )}
                        >
                          {relationLabel(
                            findRelation(
                              relations,
                              currentPlayer,
                              effectiveSelected,
                            ),
                          )}
                        </Badge>
                      </div>

                      <ScrollArea className="h-[40vh] px-3 py-2">
                        {thread.length === 0 ? (
                          <p className="text-sm text-muted-foreground">
                            No messages yet. Say something.
                          </p>
                        ) : (
                          <ul className="space-y-2">
                            {thread.map((m) => {
                              const mine = m.sender === currentPlayer
                              return (
                                <li
                                  key={m.id}
                                  className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                                    mine
                                      ? 'ml-auto bg-primary text-primary-foreground'
                                      : 'mr-auto bg-muted'
                                  }`}
                                  data-testid="message"
                                  data-sender={m.sender}
                                >
                                  <div className="whitespace-pre-wrap break-words">
                                    {m.body}
                                  </div>
                                  <div className="text-[10px] opacity-70 mt-1">
                                    Turn {m.turn_sent} · {mine ? 'you' : m.sender}
                                  </div>
                                </li>
                              )
                            })}
                          </ul>
                        )}
                      </ScrollArea>

                      <div className="border-t p-3 space-y-2">
                        <textarea
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          placeholder={
                            sendDisabledReason ??
                            `Message ${effectiveSelected}...`
                          }
                          rows={3}
                          maxLength={MESSAGE_BODY_MAX_LENGTH + 200}
                          disabled={!gameActive}
                          title={sendDisabledReason ?? undefined}
                          className="w-full resize-y border rounded-md p-2 bg-background text-sm disabled:opacity-60"
                          data-testid="message-draft"
                        />
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`text-xs ${
                              draftTooLong
                                ? 'text-destructive'
                                : 'text-muted-foreground'
                            }`}
                          >
                            {draft.length}/{MESSAGE_BODY_MAX_LENGTH}
                          </span>
                          <Button
                            size="sm"
                            disabled={!canSend}
                            title={sendDisabledReason ?? undefined}
                            onClick={() => {
                              if (!effectiveSelected) return
                              sendMessage.mutate({
                                recipient: effectiveSelected,
                                body: draft,
                              })
                            }}
                            data-testid="message-send"
                          >
                            <Send className="h-4 w-4 mr-2" />
                            Send
                          </Button>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="p-4 text-sm text-muted-foreground">
                      Select a counterpart to start a thread.
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
