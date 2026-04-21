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
  FileText,
  Plus,
  Trash2,
  Check,
  X,
  ScrollText,
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
  ResourceBag,
  TreatyClause,
  TreatyProposalRecord,
  TreatyRecord,
} from '@/types/game'
import {
  FREE_TEXT_CLAUSE_MAX_LENGTH,
  MESSAGE_BODY_MAX_LENGTH,
  MESSAGES_PER_TURN_LIMIT,
  PEACE_CLAUSE_MAX_DURATION,
  TREATY_PROPOSAL_EXPIRY_TURNS,
} from '@/types/game'

import { getGamePlayerId } from '@/lib/game-auth'

function getAuthPlayerId(gameId: string): PlayerId | null {
  return getGamePlayerId(gameId)
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
    case 'treaty_violated':
      return {
        label: 'Treaty violated',
        className: 'border-destructive bg-destructive/10 text-destructive',
        Icon: Skull,
      }
    case 'treaty_cancelled':
      return {
        label: 'Treaty cancelled',
        className:
          'border-orange-500 bg-orange-500/10 text-orange-700 dark:text-orange-400',
        Icon: ScrollText,
      }
    case 'treaty_expired':
      return {
        label: 'Treaty expired',
        className: 'border-border bg-muted/40 text-foreground',
        Icon: ScrollText,
      }
    case 'proposal_accepted':
      return {
        label: 'Proposal accepted',
        className:
          'border-green-600 bg-green-500/10 text-green-700 dark:text-green-400',
        Icon: Check,
      }
    case 'proposal_declined':
      return {
        label: 'Proposal declined',
        className: 'border-border bg-muted/40 text-foreground',
        Icon: X,
      }
    case 'proposal_withdrawn':
      return {
        label: 'Proposal withdrawn',
        className: 'border-border bg-muted/40 text-foreground',
        Icon: X,
      }
    case 'proposal_expired':
      return {
        label: 'Proposal expired',
        className: 'border-border bg-muted/40 text-foreground',
        Icon: X,
      }
    case 'treaty_proposed':
      return {
        label: 'Treaty proposed',
        className: 'border-border bg-muted/40 text-foreground',
        Icon: FileText,
      }
    default:
      return {
        label: event.type.replace(/_/g, ' '),
        className: 'border-border bg-muted/40 text-foreground',
        Icon: Handshake,
      }
  }
}

function bagToString(bag: ResourceBag | undefined): string {
  if (!bag) return '0'
  const parts: string[] = []
  if (bag.food) parts.push(`${bag.food} food`)
  if (bag.wood) parts.push(`${bag.wood} wood`)
  if (bag.ore) parts.push(`${bag.ore} ore`)
  if (bag.crystal) parts.push(`${bag.crystal} crystal`)
  return parts.length === 0 ? '0' : parts.join(', ')
}

function bagIsZero(bag: ResourceBag | undefined): boolean {
  if (!bag) return true
  return !bag.food && !bag.wood && !bag.ore && !bag.crystal
}

function bagIsValid(bag: ResourceBag | undefined): boolean {
  if (!bag) return true
  return (
    Number.isFinite(bag.food) &&
    Number.isFinite(bag.wood) &&
    Number.isFinite(bag.ore) &&
    Number.isFinite(bag.crystal) &&
    bag.food >= 0 &&
    bag.wood >= 0 &&
    bag.ore >= 0 &&
    bag.crystal >= 0
  )
}

function emptyBag(): ResourceBag {
  return { food: 0, wood: 0, ore: 0, crystal: 0, science: 0 }
}

const BAG_KEYS: (keyof ResourceBag)[] = ['food', 'wood', 'ore', 'crystal']

function BagInputs({
  label,
  bag,
  onChange,
  testIdPrefix,
}: {
  label: string
  bag: ResourceBag
  onChange: (bag: ResourceBag) => void
  testIdPrefix: string
}) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="grid grid-cols-4 gap-1">
        {BAG_KEYS.map((key) => (
          <label
            key={key}
            className="flex flex-col text-[10px] text-muted-foreground"
          >
            <span className="capitalize">{key}</span>
            <input
              type="number"
              min={0}
              value={bag[key]}
              onChange={(e) => {
                const v = Number(e.target.value)
                onChange({
                  ...bag,
                  [key]: Number.isFinite(v) && v >= 0 ? v : 0,
                })
              }}
              className="border rounded-md bg-background px-1 py-0.5 text-xs"
              data-testid={`${testIdPrefix}-${key}`}
            />
          </label>
        ))}
      </div>
    </div>
  )
}

function clauseSummary(clause: TreatyClause): string {
  if (clause.clause_type === 'peace') {
    const remaining = clause.turns_remaining ?? clause.duration_turns
    return `Peace (${remaining ?? '?'} turns remaining)`
  }
  if (clause.clause_type === 'free_text') {
    return `Free text: ${clause.text ?? ''}`
  }
  if (clause.clause_type === 'resource_swap') {
    return `Swap: proposer gives ${bagToString(
      clause.proposer_gives,
    )} / recipient gives ${bagToString(clause.recipient_gives)}`
  }
  // recurring_tribute
  const remaining = clause.turns_remaining ?? clause.duration_turns
  return `Tribute: ${clause.payer ?? '?'} pays ${bagToString(
    clause.amount,
  )} per turn (${remaining ?? '?'} turns remaining)`
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
  const currentPlayer = getAuthPlayerId(gameId)

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

  const proposeTreaty = useMutation({
    mutationFn: ({
      recipient,
      clauses,
    }: {
      recipient: PlayerId
      clauses: TreatyClause[]
    }) => api.proposeTreaty(gameId, recipient, clauses),
    onSuccess: (_, { recipient }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      setProposalClauses([])
      toast({
        title: 'Proposal queued',
        description: `Treaty proposal to ${recipient} will be sent at end of turn.`,
      })
    },
    onError: (err, { recipient }) => {
      toast({
        title: `Could not propose treaty to ${recipient}`,
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const respondToTreaty = useMutation({
    mutationFn: ({
      proposalId,
      accept,
    }: {
      proposalId: number
      accept: boolean
    }) => api.respondToTreaty(gameId, proposalId, accept),
    onSuccess: (_, { accept }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      toast({
        title: accept ? 'Acceptance queued' : 'Decline queued',
        description: 'Resolves at end of turn.',
      })
    },
    onError: (err) => {
      toast({
        title: 'Could not respond to proposal',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const withdrawTreaty = useMutation({
    mutationFn: (proposalId: number) =>
      api.withdrawTreaty(gameId, proposalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      toast({
        title: 'Withdraw queued',
        description: 'Proposal will be withdrawn at end of turn.',
      })
    },
    onError: (err) => {
      toast({
        title: 'Could not withdraw proposal',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const cancelTreaty = useMutation({
    mutationFn: (treatyId: number) => api.cancelTreaty(gameId, treatyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.diplomacy(gameId) })
      toast({
        title: 'Cancellation queued',
        description: 'Treaty cancellation resolves at end of turn.',
      })
    },
    onError: (err) => {
      toast({
        title: 'Could not cancel treaty',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const [selectedCounterpart, setSelectedCounterpart] =
    useState<PlayerId | null>(null)
  const [draft, setDraft] = useState('')
  const [proposalRecipient, setProposalRecipient] = useState<PlayerId | ''>('')
  const [proposalClauses, setProposalClauses] = useState<TreatyClause[]>([])
  const [peaceDuration, setPeaceDuration] = useState<number>(10)
  const [freeText, setFreeText] = useState('')
  const [proposerGives, setProposerGives] = useState<ResourceBag>(emptyBag())
  const [recipientGives, setRecipientGives] = useState<ResourceBag>(emptyBag())
  const [tributePayer, setTributePayer] = useState<PlayerId | ''>('')
  const [tributeAmount, setTributeAmount] = useState<ResourceBag>(emptyBag())
  const [tributeDuration, setTributeDuration] = useState<number>(5)

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
  const pendingProposals = diplomacy?.pending_proposals ?? []
  const activeTreaties = diplomacy?.active_treaties ?? []
  const allPlayers = gameDetail?.players ?? []
  const currentPlayerIndex = allPlayers.indexOf(currentPlayer)

  const inbox = pendingProposals.filter(
    (p) => p.recipient === currentPlayer,
  )
  const outbox = pendingProposals.filter(
    (p) => p.proposer === currentPlayer,
  )

  const effectiveRecipient =
    proposalRecipient && discovered.includes(proposalRecipient)
      ? proposalRecipient
      : discovered[0] ?? ''

  const hasPeaceClause = proposalClauses.some(
    (c) => c.clause_type === 'peace',
  )
  const freeTextTooLong = freeText.length > FREE_TEXT_CLAUSE_MAX_LENGTH
  const peaceDurationValid =
    Number.isFinite(peaceDuration) &&
    peaceDuration >= 1 &&
    peaceDuration <= PEACE_CLAUSE_MAX_DURATION

  function addPeaceClause() {
    if (!peaceDurationValid || hasPeaceClause) return
    setProposalClauses((prev) => [
      ...prev,
      {
        clause_type: 'peace',
        duration_turns: peaceDuration,
        turns_remaining: peaceDuration,
      },
    ])
  }

  function addFreeTextClause() {
    const trimmed = freeText.trim()
    if (!trimmed || freeTextTooLong) return
    setProposalClauses((prev) => [
      ...prev,
      { clause_type: 'free_text', text: trimmed },
    ])
    setFreeText('')
  }

  const swapValid =
    bagIsValid(proposerGives) &&
    bagIsValid(recipientGives) &&
    !(bagIsZero(proposerGives) && bagIsZero(recipientGives))

  const effectiveTributePayer: PlayerId | '' =
    tributePayer &&
    (tributePayer === currentPlayer || tributePayer === effectiveRecipient)
      ? tributePayer
      : currentPlayer
  const tributeDurationValid =
    Number.isFinite(tributeDuration) &&
    tributeDuration >= 1 &&
    tributeDuration <= PEACE_CLAUSE_MAX_DURATION
  const tributeValid =
    Boolean(effectiveRecipient) &&
    bagIsValid(tributeAmount) &&
    !bagIsZero(tributeAmount) &&
    tributeDurationValid

  function addSwapClause() {
    if (!swapValid) return
    setProposalClauses((prev) => [
      ...prev,
      {
        clause_type: 'resource_swap',
        proposer_gives: { ...proposerGives },
        recipient_gives: { ...recipientGives },
      },
    ])
    setProposerGives(emptyBag())
    setRecipientGives(emptyBag())
  }

  function addTributeClause() {
    if (!tributeValid) return
    setProposalClauses((prev) => [
      ...prev,
      {
        clause_type: 'recurring_tribute',
        payer: effectiveTributePayer || currentPlayer || undefined,
        amount: { ...tributeAmount },
        duration_turns: tributeDuration,
        turns_remaining: tributeDuration,
      },
    ])
    setTributeAmount(emptyBag())
  }

  function removeClauseAt(idx: number) {
    setProposalClauses((prev) => prev.filter((_, i) => i !== idx))
  }

  function submitProposal() {
    if (!effectiveRecipient || proposalClauses.length === 0) return
    const clausesToSend: TreatyClause[] = proposalClauses.map((c) => {
      if (c.clause_type === 'peace') {
        return { clause_type: 'peace', duration_turns: c.duration_turns }
      }
      if (c.clause_type === 'free_text') {
        return { clause_type: 'free_text', text: c.text ?? '' }
      }
      if (c.clause_type === 'resource_swap') {
        return {
          clause_type: 'resource_swap',
          proposer_gives: c.proposer_gives ?? emptyBag(),
          recipient_gives: c.recipient_gives ?? emptyBag(),
        }
      }
      return {
        clause_type: 'recurring_tribute',
        payer: c.payer ?? currentPlayer ?? undefined,
        amount: c.amount ?? emptyBag(),
        duration_turns: c.duration_turns,
      }
    })
    proposeTreaty.mutate({
      recipient: effectiveRecipient,
      clauses: clausesToSend,
    })
  }

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

        <div className="grid gap-6 md:grid-cols-2">
          <Card data-testid="proposal-builder">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Propose treaty
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {discovered.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Discover another player before proposing a treaty.
                </p>
              ) : (
                <>
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-muted-foreground">
                      Recipient
                    </label>
                    <select
                      className="w-full border rounded-md bg-background px-2 py-1 text-sm"
                      value={effectiveRecipient}
                      onChange={(e) =>
                        setProposalRecipient(e.target.value as PlayerId)
                      }
                      data-testid="proposal-recipient"
                    >
                      {discovered.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="border rounded-md p-3 space-y-2">
                    <div className="text-xs font-medium text-muted-foreground">
                      Add peace clause
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min={1}
                        max={PEACE_CLAUSE_MAX_DURATION}
                        value={peaceDuration}
                        onChange={(e) =>
                          setPeaceDuration(Number(e.target.value))
                        }
                        className="w-24 border rounded-md bg-background px-2 py-1 text-sm"
                        data-testid="peace-duration"
                      />
                      <span className="text-xs text-muted-foreground">
                        turns
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="ml-auto"
                        disabled={!peaceDurationValid || hasPeaceClause}
                        onClick={addPeaceClause}
                        title={
                          hasPeaceClause
                            ? 'Only one peace clause per proposal'
                            : undefined
                        }
                        data-testid="add-peace"
                      >
                        <Plus className="h-4 w-4 mr-1" />
                        Peace
                      </Button>
                    </div>
                  </div>

                  <div className="border rounded-md p-3 space-y-2">
                    <div className="text-xs font-medium text-muted-foreground">
                      Add free-text clause
                    </div>
                    <textarea
                      rows={2}
                      value={freeText}
                      onChange={(e) => setFreeText(e.target.value)}
                      placeholder="Plain-language obligation (non-binding)…"
                      className="w-full resize-y border rounded-md bg-background p-2 text-sm"
                      data-testid="free-text-input"
                    />
                    <div className="flex items-center justify-between">
                      <span
                        className={`text-xs ${
                          freeTextTooLong
                            ? 'text-destructive'
                            : 'text-muted-foreground'
                        }`}
                      >
                        {freeText.length}/{FREE_TEXT_CLAUSE_MAX_LENGTH}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!freeText.trim() || freeTextTooLong}
                        onClick={addFreeTextClause}
                        data-testid="add-free-text"
                      >
                        <Plus className="h-4 w-4 mr-1" />
                        Clause
                      </Button>
                    </div>
                  </div>

                  <div className="border rounded-md p-3 space-y-2">
                    <div className="text-xs font-medium text-muted-foreground">
                      Add resource swap
                    </div>
                    <BagInputs
                      label="You give"
                      bag={proposerGives}
                      onChange={setProposerGives}
                      testIdPrefix="swap-proposer"
                    />
                    <BagInputs
                      label={`${effectiveRecipient || 'Recipient'} gives`}
                      bag={recipientGives}
                      onChange={setRecipientGives}
                      testIdPrefix="swap-recipient"
                    />
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!swapValid}
                        onClick={addSwapClause}
                        data-testid="add-resource-swap"
                      >
                        <Plus className="h-4 w-4 mr-1" />
                        Swap clause
                      </Button>
                    </div>
                  </div>

                  <div className="border rounded-md p-3 space-y-2">
                    <div className="text-xs font-medium text-muted-foreground">
                      Add recurring tribute
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-muted-foreground">
                        Payer
                      </label>
                      <select
                        className="flex-1 border rounded-md bg-background px-2 py-1 text-sm"
                        value={effectiveTributePayer}
                        onChange={(e) =>
                          setTributePayer(e.target.value as PlayerId)
                        }
                        data-testid="tribute-payer"
                      >
                        <option value={currentPlayer}>
                          {currentPlayer} (you)
                        </option>
                        {effectiveRecipient && (
                          <option value={effectiveRecipient}>
                            {effectiveRecipient}
                          </option>
                        )}
                      </select>
                    </div>
                    <BagInputs
                      label="Amount per turn"
                      bag={tributeAmount}
                      onChange={setTributeAmount}
                      testIdPrefix="tribute-amount"
                    />
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-muted-foreground">
                        Duration
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={PEACE_CLAUSE_MAX_DURATION}
                        value={tributeDuration}
                        onChange={(e) =>
                          setTributeDuration(Number(e.target.value))
                        }
                        className="w-24 border rounded-md bg-background px-2 py-1 text-sm"
                        data-testid="tribute-duration"
                      />
                      <span className="text-xs text-muted-foreground">
                        turns
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="ml-auto"
                        disabled={!tributeValid}
                        onClick={addTributeClause}
                        data-testid="add-recurring-tribute"
                      >
                        <Plus className="h-4 w-4 mr-1" />
                        Tribute clause
                      </Button>
                    </div>
                  </div>

                  {proposalClauses.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-xs font-medium text-muted-foreground">
                        Clauses ({proposalClauses.length})
                      </div>
                      <ul className="space-y-1">
                        {proposalClauses.map((c, idx) => (
                          <li
                            key={idx}
                            className="flex items-center justify-between gap-2 border rounded-md px-2 py-1 text-sm"
                            data-testid="draft-clause"
                          >
                            <span className="truncate">
                              {clauseSummary(c)}
                            </span>
                            <button
                              type="button"
                              className="opacity-70 hover:opacity-100"
                              onClick={() => removeClauseAt(idx)}
                              aria-label="Remove clause"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <Button
                    className="w-full"
                    disabled={
                      !gameActive ||
                      !effectiveRecipient ||
                      proposalClauses.length === 0 ||
                      proposeTreaty.isPending
                    }
                    title={
                      !gameActive
                        ? `Proposals only while active (status: ${
                            gameStatus ?? 'unknown'
                          }).`
                        : undefined
                    }
                    onClick={submitProposal}
                    data-testid="submit-proposal"
                  >
                    <Send className="h-4 w-4 mr-2" />
                    Send proposal
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Proposals expire after {TREATY_PROPOSAL_EXPIRY_TURNS} turns
                    if not answered.
                  </p>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ScrollText className="h-5 w-5" />
                Active treaties
              </CardTitle>
            </CardHeader>
            <CardContent>
              {activeTreaties.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No active treaties.
                </p>
              ) : (
                <ul className="space-y-2">
                  {activeTreaties.map((t: TreatyRecord) => {
                    const otherParty =
                      t.parties[0] === currentPlayer
                        ? t.parties[1]
                        : t.parties[0]
                    return (
                      <li
                        key={t.id}
                        className="border rounded-md p-3 space-y-2"
                        data-testid={`treaty-${t.id}`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="font-mono text-sm">
                            with {otherParty}
                          </div>
                          <span className="text-xs text-muted-foreground">
                            Ratified turn {t.turn_ratified}
                          </span>
                        </div>
                        <ul className="text-xs space-y-0.5">
                          {t.clauses.map((c, i) => (
                            <li key={i}>• {clauseSummary(c)}</li>
                          ))}
                        </ul>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={!gameActive || cancelTreaty.isPending}
                          onClick={() => cancelTreaty.mutate(t.id)}
                          data-testid={`cancel-treaty-${t.id}`}
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          Cancel (violation if active)
                        </Button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Proposals inbox</CardTitle>
            </CardHeader>
            <CardContent>
              {inbox.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No pending proposals addressed to you.
                </p>
              ) : (
                <ul className="space-y-2">
                  {inbox.map((p: TreatyProposalRecord) => (
                    <li
                      key={p.id}
                      className="border rounded-md p-3 space-y-2"
                      data-testid={`inbox-proposal-${p.id}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-mono text-sm">
                          from {p.proposer}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          Expires turn {p.expires_on_turn}
                        </span>
                      </div>
                      <ul className="text-xs space-y-0.5">
                        {p.clauses.map((c, i) => (
                          <li key={i}>• {clauseSummary(c)}</li>
                        ))}
                      </ul>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          disabled={!gameActive || respondToTreaty.isPending}
                          onClick={() =>
                            respondToTreaty.mutate({
                              proposalId: p.id,
                              accept: true,
                            })
                          }
                          data-testid={`accept-${p.id}`}
                        >
                          <Check className="h-4 w-4 mr-1" />
                          Accept
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!gameActive || respondToTreaty.isPending}
                          onClick={() =>
                            respondToTreaty.mutate({
                              proposalId: p.id,
                              accept: false,
                            })
                          }
                          data-testid={`decline-${p.id}`}
                        >
                          <X className="h-4 w-4 mr-1" />
                          Decline
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Proposals outbox</CardTitle>
            </CardHeader>
            <CardContent>
              {outbox.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  You have no pending proposals awaiting reply.
                </p>
              ) : (
                <ul className="space-y-2">
                  {outbox.map((p: TreatyProposalRecord) => (
                    <li
                      key={p.id}
                      className="border rounded-md p-3 space-y-2"
                      data-testid={`outbox-proposal-${p.id}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-mono text-sm">
                          to {p.recipient}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          Expires turn {p.expires_on_turn}
                        </span>
                      </div>
                      <ul className="text-xs space-y-0.5">
                        {p.clauses.map((c, i) => (
                          <li key={i}>• {clauseSummary(c)}</li>
                        ))}
                      </ul>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!gameActive || withdrawTreaty.isPending}
                        onClick={() => withdrawTreaty.mutate(p.id)}
                        data-testid={`withdraw-${p.id}`}
                      >
                        <X className="h-4 w-4 mr-1" />
                        Withdraw
                      </Button>
                    </li>
                  ))}
                </ul>
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
