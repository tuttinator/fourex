'use client'

/**
 * Phase 5 gameplay view — every queueable action the PRD's gameplay
 * surface calls for.
 *
 * Selection is either a friendly unit or a friendly city (mutually
 * exclusive). Depending on what's selected, the sidebar surfaces the
 * relevant affordances:
 *   - Unit  → valid moves (yellow highlight), valid attacks (red
 *             highlight), found-city (for a settler-capable worker on
 *             a legal tile), build-improvement (for a worker on a tile
 *             that permits one).
 *   - City  → train-unit / build-building tabs, filtered by cost and
 *             by what the city already has.
 *
 * All affordance lists are fetched from Phase 5's backend endpoints so
 * the UI's filter rules stay in lockstep with the server-side validators.
 * Every queued order goes into a single ``queue`` and flushes atomically
 * on End Turn; ``turn.resolved`` on the lobby WebSocket clears the queue
 * and triggers a game-state refetch.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  AlertCircle,
  Building2,
  ChevronLeft,
  Check,
  Clock,
  Hammer,
  Handshake,
  Landmark,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Swords,
  Trash2,
} from 'lucide-react'
import { api, ApiError, queryKeys } from '@/lib/api'
import { PixiMap } from '@/components/pixi-map'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { useToast } from '@/hooks/use-toast'
import { useLobbyEvents } from '@/hooks/use-lobby-events'
import type {
  BuildableBuilding,
  BuildableBuildingsResponse,
  CanFoundCityResponse,
  Coord,
  DiplomacyMessage,
  DiplomacyRelation,
  DiplomacyStateResponse,
  GameAction,
  GameState,
  PlayerId,
  QueuedAction,
  ResourceBag,
  Tile,
  TrainableUnit,
  TrainableUnitsResponse,
  TreatyRecord,
  TurnSubmissionsResponse,
  Unit,
  ValidAttacksResponse,
  ValidImprovement,
  ValidImprovementsResponse,
  ValidMovesResponse,
} from '@/types/game'
import { MESSAGE_BODY_MAX_LENGTH } from '@/types/game'

const ACTIVE_POLL_INTERVAL = 5000

interface GameplayViewProps {
  gameId: string
  currentPlayer: PlayerId
}

function formatCost(cost: ResourceBag): string {
  const parts: string[] = []
  if (cost.food) parts.push(`${cost.food} food`)
  if (cost.wood) parts.push(`${cost.wood} wood`)
  if (cost.ore) parts.push(`${cost.ore} ore`)
  if (cost.crystal) parts.push(`${cost.crystal} crystal`)
  return parts.length ? parts.join(', ') : 'free'
}

function describeAction(action: GameAction): string {
  switch (action.type) {
    case 'MOVE':
      return `Move unit #${action.unit_id} → (${action.to.x}, ${action.to.y})`
    case 'ATTACK':
      return `Attack ${action.target_type} #${action.target_id} (unit #${action.attacker_id})`
    case 'FOUND_CITY':
      return `Found city (worker #${action.worker_id})`
    case 'BUILD_IMPROVEMENT':
      return `Build ${action.improvement} (worker #${action.worker_id})`
    case 'TRAIN_UNIT':
      return `Train ${action.unit_type} @ city #${action.city_id}`
    case 'BUILD_BUILDING':
      return `Build ${action.building_type} @ city #${action.city_id}`
    case 'SEND_MESSAGE': {
      const preview =
        action.body.length > 40
          ? `${action.body.slice(0, 37)}…`
          : action.body
      return `Message → ${action.recipient}: ${preview}`
    }
  }
}

function newQueueId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

const RESOURCE_META: Array<{
  key: keyof ResourceBag
  emoji: string
  label: string
}> = [
  { key: 'food', emoji: '🌾', label: 'Food' },
  { key: 'wood', emoji: '🪵', label: 'Wood' },
  { key: 'ore', emoji: '⛏️', label: 'Ore' },
  { key: 'crystal', emoji: '💎', label: 'Crystal' },
]

interface YieldBreakdown {
  total: ResourceBag
  lines: string[]
}

/** Estimate the current player's per-turn yield from cities + owned tiles.
 *
 * Mirrors ``_calculate_tile_yield`` and ``collect_resources`` in
 * ``backend/src/game/rules.py`` so the hover hint reflects what the server
 * will credit at the end of the turn. The Granary food multiplier isn't
 * modelled on the client, so city base food is a plain +2.
 */
function computeYieldBreakdown(
  state: GameState,
  player: PlayerId,
): YieldBreakdown {
  const total: ResourceBag = { food: 0, wood: 0, ore: 0, crystal: 0 }
  const lines: string[] = []

  const myCities = Object.values(state.cities).filter((c) => c.owner === player)
  if (myCities.length > 0) {
    const cityFood = myCities.length * 2
    total.food += cityFood
    lines.push(`+${cityFood} food from ${myCities.length} city base`)
  }

  const cityTileKeys = new Set(
    myCities.map((c) => `${c.loc.x},${c.loc.y}`),
  )

  let tileFood = 0
  let tileWood = 0
  let tileOre = 0
  let tileCrystal = 0

  for (const tile of state.tiles) {
    if (tile.owner !== player) continue
    if (cityTileKeys.has(`${tile.loc.x},${tile.loc.y}`)) continue

    let f = 0
    let w = 0
    let o = 0
    let c = 0

    if (tile.resource === 'food') f += 1
    else if (tile.resource === 'wood') w += 1
    else if (tile.resource === 'ore') o += 1
    else if (tile.resource === 'crystal') c += 1
    else if (tile.terrain === 'forest') w += 1

    if (tile.improvement === 'farm' && tile.resource === 'food') f += 2
    else if (tile.improvement === 'mine' && tile.resource === 'ore') o += 2
    else if (tile.improvement === 'lumber_mill') w += 2
    else if (
      tile.improvement === 'crystal_extractor' &&
      tile.resource === 'crystal'
    )
      c += 1

    tileFood += f
    tileWood += w
    tileOre += o
    tileCrystal += c
  }

  total.food += tileFood
  total.wood += tileWood
  total.ore += tileOre
  total.crystal += tileCrystal

  if (tileFood) lines.push(`+${tileFood} food from tile yields`)
  if (tileWood) lines.push(`+${tileWood} wood from tile yields`)
  if (tileOre) lines.push(`+${tileOre} ore from tile yields`)
  if (tileCrystal) lines.push(`+${tileCrystal} crystal from tile yields`)

  return { total, lines }
}

interface ResourceBarProps {
  stockpile: ResourceBag
  yieldBreakdown: YieldBreakdown
}

function ResourceBar({ stockpile, yieldBreakdown }: ResourceBarProps) {
  return (
    <div className="flex items-center gap-3 text-sm">
      {RESOURCE_META.map(({ key, emoji, label }) => {
        const amount = stockpile[key] ?? 0
        const delta = yieldBreakdown.total[key] ?? 0
        const relevantLines = yieldBreakdown.lines.filter((l) =>
          l.endsWith(` ${key} from tile yields`) ||
          (key === 'food' && l.endsWith('city base')),
        )
        const tooltip =
          `${label}: ${amount}\n` +
          (delta > 0
            ? `+${delta} per turn\n${relevantLines.join('\n')}`
            : 'no income this turn')
        return (
          <span
            key={key}
            title={tooltip}
            className="flex items-center gap-1 tabular-nums"
          >
            <span aria-hidden="true">{emoji}</span>
            <span className="font-medium">{amount}</span>
            {delta > 0 && (
              <span className="text-xs text-muted-foreground">
                (+{delta})
              </span>
            )}
          </span>
        )
      })}
    </div>
  )
}

export function GameplayView({ gameId, currentPlayer }: GameplayViewProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null)
  const [selectedCityId, setSelectedCityId] = useState<number | null>(null)
  const [queue, setQueue] = useState<QueuedAction[]>([])
  const [waiting, setWaiting] = useState(false)
  // Phase 6: per-player submission roster for the current turn. The
  // initial snapshot arrives from ``GET /turn-submissions`` on mount (and
  // on every turn rollover); live deltas come from the ``turn.submitted``
  // WebSocket event. Resets on ``turn.resolved``.
  const [submittedPlayers, setSubmittedPlayers] = useState<Set<PlayerId>>(
    () => new Set(),
  )
  // Phase 7: diplomacy thread selection and per-opponent unread counter.
  // ``lastSeenMessageIds[opponent]`` is the highest message id the local
  // user has already seen in the thread with that opponent; anything
  // above it contributes to the unread badge. Opening a thread bumps
  // the high-water mark to the latest id in that thread.
  const [selectedOpponent, setSelectedOpponent] =
    useState<PlayerId | null>(null)
  const [lastSeenMessageIds, setLastSeenMessageIds] = useState<
    Record<PlayerId, number>
  >({})

  const { lastEvent } = useLobbyEvents(gameId)

  const stateQueryKey = queryKeys.gameState(gameId, currentPlayer)

  const {
    data: gameState,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: stateQueryKey,
    queryFn: () => api.getGameState(gameId),
    refetchInterval: ACTIVE_POLL_INTERVAL,
  })

  // Restore queued orders from the server on mount / when the turn rolls
  // over, so a page refresh after submitting preserves the "waiting for
  // turn to resolve" UI and shows the submitted orders.
  const { data: mySubmission } = useQuery({
    queryKey: ['game', gameId, 'mySubmission', gameState?.turn ?? null],
    queryFn: () => api.getMySubmission(gameId),
    enabled: gameState != null,
  })

  const hydratedTurnRef = useRef<number | null>(null)
  useEffect(() => {
    if (!mySubmission) return
    if (hydratedTurnRef.current === mySubmission.turn) return
    hydratedTurnRef.current = mySubmission.turn
    if (mySubmission.submitted) {
      setQueue(
        mySubmission.actions.map((action) => ({
          queue_id: newQueueId(),
          action,
        })),
      )
      setWaiting(true)
    }
  }, [mySubmission])

  // Phase 6: hydrate the submission roster on mount and every turn
  // rollover. Live updates then arrive via the turn.submitted WS event;
  // the snapshot is a safety net against missed frames (e.g. after a
  // reconnect) and fixes the "refresh mid-turn" case.
  const { data: turnSubmissions } = useQuery<TurnSubmissionsResponse | null>({
    queryKey: ['game', gameId, 'turnSubmissions', gameState?.turn ?? null],
    queryFn: () => api.getTurnSubmissions(gameId),
    enabled: gameState != null,
  })

  const hydratedSubmissionsTurnRef = useRef<number | null>(null)
  useEffect(() => {
    if (!turnSubmissions) return
    if (hydratedSubmissionsTurnRef.current === turnSubmissions.turn) return
    hydratedSubmissionsTurnRef.current = turnSubmissions.turn
    const next = new Set(turnSubmissions.submitted_players)
    queueMicrotask(() => setSubmittedPlayers(next))
  }, [turnSubmissions])

  // ---- Diplomacy state (Phase 7) -----------------------------------------
  //
  // The full diplomacy slice (relations, treaties, messages) is fetched
  // off the shared ``/diplomacy`` endpoint. Refetches are driven by
  // ``turn.resolved`` (below, in the existing handler) and by a
  // ``diplomacy.message_received`` live event. The stale poll is off —
  // the event surface is authoritative here.

  const diplomacyQueryKey = queryKeys.diplomacy(gameId)
  const { data: diplomacyState } = useQuery<DiplomacyStateResponse | null>({
    queryKey: diplomacyQueryKey,
    queryFn: () => api.getDiplomacy(gameId),
    enabled: gameState != null,
  })

  // ---- Per-unit affordance queries ---------------------------------------

  const selectedUnit: Unit | null =
    selectedUnitId != null && gameState
      ? gameState.units[selectedUnitId] ?? null
      : null

  const { data: validMoves } = useQuery<ValidMovesResponse | null>({
    queryKey: ['game', gameId, 'validMoves', selectedUnitId],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getValidMoves(gameId, selectedUnitId),
    enabled: selectedUnitId != null,
  })

  const { data: validAttacks } = useQuery<ValidAttacksResponse | null>({
    queryKey: ['game', gameId, 'validAttacks', selectedUnitId],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getValidAttacks(gameId, selectedUnitId),
    enabled: selectedUnitId != null,
  })

  const { data: canFoundCity } = useQuery<CanFoundCityResponse | null>({
    queryKey: ['game', gameId, 'canFoundCity', selectedUnitId],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getCanFoundCity(gameId, selectedUnitId),
    enabled: selectedUnitId != null && selectedUnit?.type === 'worker',
  })

  const { data: validImprovements } =
    useQuery<ValidImprovementsResponse | null>({
      queryKey: ['game', gameId, 'validImprovements', selectedUnitId],
      queryFn: () =>
        selectedUnitId == null
          ? Promise.resolve(null)
          : api.getValidImprovements(gameId, selectedUnitId),
      enabled: selectedUnitId != null && selectedUnit?.type === 'worker',
    })

  // ---- Per-city affordance queries ---------------------------------------

  const selectedCity =
    selectedCityId != null && gameState
      ? gameState.cities[selectedCityId] ?? null
      : null

  const { data: trainableUnits } = useQuery<TrainableUnitsResponse | null>({
    queryKey: ['game', gameId, 'trainableUnits', selectedCityId],
    queryFn: () =>
      selectedCityId == null
        ? Promise.resolve(null)
        : api.getTrainableUnits(gameId, selectedCityId),
    enabled: selectedCityId != null,
  })

  const { data: buildableBuildings } =
    useQuery<BuildableBuildingsResponse | null>({
      queryKey: ['game', gameId, 'buildableBuildings', selectedCityId],
      queryFn: () =>
        selectedCityId == null
          ? Promise.resolve(null)
          : api.getBuildableBuildings(gameId, selectedCityId),
      enabled: selectedCityId != null,
    })

  // ---- Highlight derivation ----------------------------------------------

  // Tiles already targeted by queued moves for this unit — subtract from
  // move highlights so we don't suggest a tile the player already booked.
  const queuedMoveKeys = useMemo(() => {
    const out = new Set<string>()
    for (const q of queue) {
      if (q.action.type === 'MOVE' && q.action.unit_id === selectedUnitId) {
        out.add(`${q.action.to.x},${q.action.to.y}`)
      }
    }
    return out
  }, [queue, selectedUnitId])

  // Attack targets already queued for this attacker — subtract from the
  // attack highlight set so one hostile isn't double-clicked.
  const queuedAttackKeys = useMemo(() => {
    const out = new Set<string>()
    if (selectedUnitId == null || !validAttacks) return out
    for (const q of queue) {
      const a = q.action
      if (a.type !== 'ATTACK') continue
      if (a.attacker_id !== selectedUnitId) continue
      const target = validAttacks.targets.find(
        (t) => t.target_type === a.target_type && t.target_id === a.target_id,
      )
      if (target) out.add(`${target.x},${target.y}`)
    }
    return out
  }, [queue, selectedUnitId, validAttacks])

  const highlightedTiles: Coord[] = useMemo(() => {
    if (!validMoves) return []
    return validMoves.moves
      .filter((m) => !queuedMoveKeys.has(`${m.x},${m.y}`))
      .map((m) => ({ x: m.x, y: m.y }))
  }, [validMoves, queuedMoveKeys])

  const attackTiles: Coord[] = useMemo(() => {
    if (!validAttacks) return []
    return validAttacks.targets
      .filter((t) => !queuedAttackKeys.has(`${t.x},${t.y}`))
      .map((t) => ({ x: t.x, y: t.y }))
  }, [validAttacks, queuedAttackKeys])

  const highlightedKeys = useMemo(
    () => new Set(highlightedTiles.map((t) => `${t.x},${t.y}`)),
    [highlightedTiles],
  )

  const attackTargetByKey = useMemo(() => {
    const map = new Map<
      string,
      { target_type: 'unit' | 'city'; target_id: number }
    >()
    if (!validAttacks) return map
    for (const t of validAttacks.targets) {
      if (queuedAttackKeys.has(`${t.x},${t.y}`)) continue
      map.set(`${t.x},${t.y}`, {
        target_type: t.target_type,
        target_id: t.target_id,
      })
    }
    return map
  }, [validAttacks, queuedAttackKeys])

  // ---- Tile-click routing -------------------------------------------------

  const lookupUnitAtTile = useCallback(
    (state: GameState, tile: Tile): Unit | null => {
      if (!tile.unit_id) return null
      return state.units[tile.unit_id] ?? null
    },
    [],
  )

  const handleTileClick = useCallback(
    (tile: Tile) => {
      if (!gameState) return
      const key = `${tile.loc.x},${tile.loc.y}`

      // Attack target takes priority — red tiles are the most-specific
      // affordance when a unit is selected.
      const attackTarget = attackTargetByKey.get(key)
      if (selectedUnitId != null && attackTarget) {
        setQueue((prev) => [
          ...prev,
          {
            queue_id: newQueueId(),
            action: {
              type: 'ATTACK',
              attacker_id: selectedUnitId,
              target_id: attackTarget.target_id,
              target_type: attackTarget.target_type,
            },
          },
        ])
        return
      }

      // Move highlight next.
      if (selectedUnitId != null && highlightedKeys.has(key)) {
        setQueue((prev) => [
          ...prev,
          {
            queue_id: newQueueId(),
            action: {
              type: 'MOVE',
              unit_id: selectedUnitId,
              to: { x: tile.loc.x, y: tile.loc.y },
            },
          },
        ])
        return
      }

      // Friendly unit on tile → select unit (clears city selection).
      const unitOnTile = lookupUnitAtTile(gameState, tile)
      if (unitOnTile && unitOnTile.owner === currentPlayer) {
        setSelectedUnitId(unitOnTile.id)
        setSelectedCityId(null)
        return
      }

      // Friendly city on tile → select city (clears unit selection).
      if (tile.city_id) {
        const city = gameState.cities[tile.city_id]
        if (city && city.owner === currentPlayer) {
          setSelectedCityId(city.id)
          setSelectedUnitId(null)
          return
        }
      }

      // Otherwise clear selection.
      setSelectedUnitId(null)
      setSelectedCityId(null)
    },
    [
      gameState,
      selectedUnitId,
      highlightedKeys,
      attackTargetByKey,
      lookupUnitAtTile,
      currentPlayer,
    ],
  )

  // ---- Queue helpers ------------------------------------------------------

  const removeFromQueue = useCallback((queueId: string) => {
    setQueue((prev) => prev.filter((q) => q.queue_id !== queueId))
  }, [])

  const appendToQueue = useCallback((action: GameAction) => {
    setQueue((prev) => [...prev, { queue_id: newQueueId(), action }])
  }, [])

  // Disable Found City if already queued for this worker.
  const alreadyQueuedFoundCity = useMemo(
    () =>
      selectedUnitId != null &&
      queue.some(
        (q) =>
          q.action.type === 'FOUND_CITY' &&
          q.action.worker_id === selectedUnitId,
      ),
    [queue, selectedUnitId],
  )

  // Disable improvement buttons if one's already queued for this worker.
  const alreadyQueuedImprovement = useMemo(
    () =>
      selectedUnitId != null &&
      queue.some(
        (q) =>
          q.action.type === 'BUILD_IMPROVEMENT' &&
          q.action.worker_id === selectedUnitId,
      ),
    [queue, selectedUnitId],
  )

  // Hide already-queued buildings from the city panel so the same
  // building isn't stacked twice.
  const queuedBuildingsForCity = useMemo(() => {
    const out = new Set<string>()
    if (selectedCityId == null) return out
    for (const q of queue) {
      const a = q.action
      if (a.type !== 'BUILD_BUILDING') continue
      if (a.city_id !== selectedCityId) continue
      out.add(a.building_type)
    }
    return out
  }, [queue, selectedCityId])

  // ---- End Turn -----------------------------------------------------------

  const submitMutation = useMutation({
    mutationFn: async () => {
      const payload = queue.map((q) => q.action)
      return api.submitActions(gameId, payload)
    },
    onSuccess: () => {
      setWaiting(true)
      toast({
        title: 'Turn submitted',
        description: 'Waiting for the server to resolve…',
      })
    },
    onError: (err) => {
      const message =
        err instanceof ApiError ? err.message : (err as Error).message
      toast({
        title: 'Submission rejected',
        description: message,
        variant: 'destructive',
      })
      setQueue((prev) =>
        prev.map((q) => ({ ...q, error: q.error ?? message })),
      )
    },
  })

  const lastHandledTurn = useRef<number | null>(null)
  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'turn.resolved') return
    const turn = (lastEvent as unknown as { turn?: number }).turn
    if (turn != null && lastHandledTurn.current === turn) return
    if (turn != null) lastHandledTurn.current = turn
    setQueue([])
    setSelectedUnitId(null)
    setSelectedCityId(null)
    setWaiting(false)
    // Clear the submission roster for the upcoming turn — the hydration
    // query will reseed it (empty) on the next render, but resetting here
    // avoids a flicker where last turn's "submitted" ticks linger.
    setSubmittedPlayers(new Set())
    queryClient.invalidateQueries({ queryKey: stateQueryKey })
    queryClient.invalidateQueries({
      queryKey: queryKeys.gameDetail(gameId),
    })
    queryClient.invalidateQueries({ queryKey: diplomacyQueryKey })
  }, [lastEvent, queryClient, stateQueryKey, gameId, diplomacyQueryKey])

  // Phase 7: diplomacy.message_received. The backend scopes this event
  // to sender+recipient connections only, so we can invalidate the
  // diplomacy query on any frame we see and bump the unread counter for
  // the *other* party in that thread (i.e. the sender, from our vantage
  // point — our own echoes don't count as unread).
  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'diplomacy.message_received') return
    const payload = lastEvent as unknown as {
      message?: {
        id: number
        sender: PlayerId
        recipient: PlayerId
        body: string
        turn_sent: number
      }
    }
    const msg = payload.message
    if (!msg) return
    queryClient.invalidateQueries({ queryKey: diplomacyQueryKey })
    // If we're already looking at the thread with this counterparty,
    // mark the new message as seen so the badge doesn't tick up only to
    // be cleared on the next render.
    const counterparty = msg.sender === currentPlayer ? msg.recipient : msg.sender
    if (counterparty === selectedOpponent) {
      queueMicrotask(() =>
        setLastSeenMessageIds((prev) => ({
          ...prev,
          [counterparty]: Math.max(prev[counterparty] ?? 0, msg.id),
        })),
      )
    }
  }, [
    lastEvent,
    queryClient,
    diplomacyQueryKey,
    currentPlayer,
    selectedOpponent,
  ])

  // Phase 6: fold turn.submitted deltas into the roster set. The event
  // payload carries the full snapshot ("submitted_players") so we trust
  // it verbatim rather than accumulating — resubmissions are idempotent
  // and any missed frame is covered by the hydration query.
  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'turn.submitted') return
    const payload = lastEvent as unknown as {
      submitted_players?: PlayerId[]
      turn?: number
    }
    if (!Array.isArray(payload.submitted_players)) return
    // Only react if this event is for the turn we're currently showing.
    // Stale events (from a prior turn that just resolved) are ignored so
    // they don't reintroduce submitters after the roster was cleared.
    if (
      gameState != null &&
      payload.turn != null &&
      payload.turn !== gameState.turn
    ) {
      return
    }
    const next = new Set(payload.submitted_players)
    queueMicrotask(() => setSubmittedPlayers(next))
  }, [lastEvent, gameState])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading game state…</p>
        </div>
      </div>
    )
  }

  if (error) {
    const is404 = error instanceof ApiError && error.status === 404
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-2">
            {is404 ? 'Game not found' : 'Failed to load game state'}
          </p>
          <p className="text-sm text-muted-foreground mb-4">
            {is404 ? `No game with ID "${gameId}".` : error.message}
          </p>
          {!is404 && (
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Retry
            </Button>
          )}
        </div>
      </div>
    )
  }

  if (!gameState) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <p className="text-muted-foreground">No game state available</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Status bar */}
      <div className="border-b px-4 py-2 flex items-center justify-between bg-muted/30">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-medium">
            Turn {gameState.turn} / {gameState.max_turns}
          </span>
          <Badge variant="secondary" className="text-xs">
            Playing as {currentPlayer}
          </Badge>
          {(() => {
            const outstanding = gameState.players.filter(
              (p) => !submittedPlayers.has(p),
            )
            if (outstanding.length === 0) return null
            // Only surface the waiting badge if the current player has
            // already submitted — otherwise the UI would nag about
            // opponents before the user's even queued their own turn.
            if (!waiting) return null
            return (
              <Badge variant="outline" className="text-xs">
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                Waiting for {outstanding.length} player
                {outstanding.length === 1 ? '' : 's'}
              </Badge>
            )
          })()}
        </div>
        <div className="flex items-center gap-4">
          <ResourceBar
            stockpile={
              gameState.stockpiles[currentPlayer] ?? {
                food: 0,
                wood: 0,
                ore: 0,
                crystal: 0,
              }
            }
            yieldBreakdown={computeYieldBreakdown(gameState, currentPlayer)}
          />
          <div className="text-xs text-muted-foreground">
            {Object.keys(gameState.units).length} units &middot;{' '}
            {Object.keys(gameState.cities).length} cities
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative">
          <PixiMap
            gameState={gameState}
            selectedPlayer={currentPlayer}
            fogOfWarEnabled
            selectedUnitId={selectedUnitId}
            selectedCityId={selectedCityId}
            highlightedTiles={highlightedTiles}
            attackTiles={attackTiles}
            onTileClick={handleTileClick}
          />
        </div>

        {/* Sidebar */}
        <div className="w-96 border-l bg-background/95 backdrop-blur flex flex-col h-full min-h-0">
          <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">
          {selectedCity ? (
            <CityPanel
              city={selectedCity}
              trainable={trainableUnits?.units ?? null}
              buildable={buildableBuildings?.buildings ?? null}
              queuedBuildings={queuedBuildingsForCity}
              onTrainUnit={(unit_type) =>
                appendToQueue({
                  type: 'TRAIN_UNIT',
                  city_id: selectedCity.id,
                  unit_type,
                })
              }
              onBuildBuilding={(building_type) =>
                appendToQueue({
                  type: 'BUILD_BUILDING',
                  city_id: selectedCity.id,
                  building_type,
                })
              }
            />
          ) : (
            <UnitPanel
              unit={selectedUnit}
              highlightedCount={highlightedTiles.length}
              attackCount={attackTiles.length}
              canFoundCity={canFoundCity ?? null}
              validImprovements={validImprovements?.improvements ?? null}
              foundCityQueued={alreadyQueuedFoundCity}
              improvementQueued={alreadyQueuedImprovement}
              onFoundCity={() =>
                selectedUnit &&
                appendToQueue({
                  type: 'FOUND_CITY',
                  worker_id: selectedUnit.id,
                })
              }
              onBuildImprovement={(improvement) =>
                selectedUnit &&
                appendToQueue({
                  type: 'BUILD_IMPROVEMENT',
                  worker_id: selectedUnit.id,
                  improvement,
                })
              }
            />
          )}

          {/* Submission roster (Phase 6) */}
          <SubmissionRoster
            players={gameState.players}
            currentPlayer={currentPlayer}
            submittedPlayers={submittedPlayers}
          />

          {/* Diplomacy panel (Phase 7) */}
          <DiplomacyPanel
            currentPlayer={currentPlayer}
            diplomacy={diplomacyState ?? null}
            selectedOpponent={selectedOpponent}
            onSelectOpponent={(opponent) => {
              setSelectedOpponent(opponent)
              // Viewing the thread clears unread: advance the high-water
              // mark to the latest message id visible between us and
              // ``opponent``.
              if (opponent && diplomacyState) {
                const maxId = diplomacyState.messages.reduce((acc, m) => {
                  if (
                    (m.sender === currentPlayer && m.recipient === opponent) ||
                    (m.sender === opponent && m.recipient === currentPlayer)
                  ) {
                    return Math.max(acc, m.id)
                  }
                  return acc
                }, lastSeenMessageIds[opponent] ?? 0)
                setLastSeenMessageIds((prev) => ({
                  ...prev,
                  [opponent]: maxId,
                }))
              }
            }}
            lastSeenMessageIds={lastSeenMessageIds}
            pendingQueuedForOpponent={queue
              .map((q) => q.action)
              .filter(
                (a): a is Extract<GameAction, { type: 'SEND_MESSAGE' }> =>
                  a.type === 'SEND_MESSAGE',
              )}
            onQueueMessage={(recipient, body) =>
              appendToQueue({ type: 'SEND_MESSAGE', recipient, body })
            }
          />

          {/* Queue panel */}
          <Card className="rounded-none border-0 border-b flex-1 flex flex-col">
            <CardHeader className="py-3">
              <CardTitle className="text-sm flex items-center justify-between">
                <span>Queued orders ({queue.length})</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-0">
              {queue.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No orders queued. Select a unit or city to see what you
                  can do this turn.
                </p>
              ) : (
                queue.map((q) => (
                  <div
                    key={q.queue_id}
                    className="flex items-center justify-between rounded border px-2 py-1.5 text-xs"
                  >
                    <div className="flex flex-col">
                      <span className="font-medium">
                        {describeAction(q.action)}
                      </span>
                      {q.error && (
                        <span className="text-destructive">{q.error}</span>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Remove queued order"
                      onClick={() => removeFromQueue(q.queue_id)}
                      className="h-6 w-6 p-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
          </div>

          <div className="p-3 border-t shrink-0">
            <Button
              className="w-full"
              disabled={submitMutation.isPending || waiting}
              onClick={() => submitMutation.mutate()}
            >
              <Send className="h-4 w-4 mr-2" />
              {submitMutation.isPending
                ? 'Submitting…'
                : waiting
                  ? 'Waiting…'
                  : `End Turn${queue.length ? ` (${queue.length})` : ''}`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Sidebar sub-panels ---------------------------------------------------

interface UnitPanelProps {
  unit: Unit | null
  highlightedCount: number
  attackCount: number
  canFoundCity: CanFoundCityResponse | null
  validImprovements: ValidImprovement[] | null
  foundCityQueued: boolean
  improvementQueued: boolean
  onFoundCity: () => void
  onBuildImprovement: (improvement: ValidImprovement['improvement']) => void
}

function UnitPanel({
  unit,
  highlightedCount,
  attackCount,
  canFoundCity,
  validImprovements,
  foundCityQueued,
  improvementQueued,
  onFoundCity,
  onBuildImprovement,
}: UnitPanelProps) {
  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm">Selection</CardTitle>
      </CardHeader>
      <CardContent className="text-sm space-y-3">
        {!unit ? (
          <p className="text-xs text-muted-foreground">
            Click one of your units or cities to see what you can do.
          </p>
        ) : (
          <>
            <div>
              <div className="flex items-center justify-between">
                <span className="capitalize font-medium">{unit.type}</span>
                <span className="text-muted-foreground text-xs">
                  #{unit.id}
                </span>
              </div>
              <div className="text-xs text-muted-foreground">
                HP {unit.hp} &middot; Moves left {unit.moves_left} &middot;
                ({unit.loc.x}, {unit.loc.y})
              </div>
              <div className="text-xs text-muted-foreground">
                {highlightedCount} legal move
                {highlightedCount === 1 ? '' : 's'}
                {attackCount > 0 && (
                  <>
                    {' '}
                    &middot; {attackCount} attack target
                    {attackCount === 1 ? '' : 's'}
                  </>
                )}
              </div>
            </div>

            {canFoundCity && (
              <div>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-start"
                  disabled={!canFoundCity.can_found || foundCityQueued}
                  onClick={onFoundCity}
                  title={canFoundCity.reason ?? undefined}
                >
                  <Landmark className="h-4 w-4 mr-2" />
                  Found city ({canFoundCity.cost.food} food)
                  {foundCityQueued && ' — queued'}
                </Button>
                {!canFoundCity.can_found && canFoundCity.reason && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {canFoundCity.reason}
                  </p>
                )}
              </div>
            )}

            {validImprovements && validImprovements.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium flex items-center gap-1">
                  <Hammer className="h-3.5 w-3.5" />
                  Improvements
                </div>
                {validImprovements.map((imp) => (
                  <Button
                    key={imp.improvement}
                    variant="outline"
                    size="sm"
                    className="w-full justify-between text-xs"
                    disabled={!imp.affordable || improvementQueued}
                    onClick={() => onBuildImprovement(imp.improvement)}
                    title={
                      !imp.affordable
                        ? `Cannot afford (${formatCost(imp.cost)})`
                        : undefined
                    }
                  >
                    <span className="capitalize">
                      {imp.improvement.replace(/_/g, ' ')}
                    </span>
                    <span className="text-muted-foreground">
                      {formatCost(imp.cost)}
                    </span>
                  </Button>
                ))}
                {improvementQueued && (
                  <p className="text-xs text-muted-foreground">
                    An improvement is already queued for this worker.
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

interface CityPanelProps {
  city: { id: number; loc: Coord; hp: number; buildings: string[] }
  trainable: TrainableUnit[] | null
  buildable: BuildableBuilding[] | null
  queuedBuildings: Set<string>
  onTrainUnit: (unit_type: TrainableUnit['unit_type']) => void
  onBuildBuilding: (building_type: BuildableBuilding['building_type']) => void
}

function CityPanel({
  city,
  trainable,
  buildable,
  queuedBuildings,
  onTrainUnit,
  onBuildBuilding,
}: CityPanelProps) {
  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center justify-between">
          <span>
            <Building2 className="inline h-4 w-4 mr-1" />
            City #{city.id}
          </span>
          <span className="text-xs text-muted-foreground">
            ({city.loc.x}, {city.loc.y}) &middot; HP {city.hp}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <Tabs defaultValue="train" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="train">
              <Sparkles className="h-3.5 w-3.5 mr-1" />
              Train
            </TabsTrigger>
            <TabsTrigger value="build">
              <Hammer className="h-3.5 w-3.5 mr-1" />
              Build
            </TabsTrigger>
          </TabsList>

          <TabsContent value="train" className="space-y-1 mt-2">
            {!trainable ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : trainable.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No trainable units.
              </p>
            ) : (
              trainable.map((u) => (
                <Button
                  key={u.unit_type}
                  variant="outline"
                  size="sm"
                  className="w-full justify-between text-xs"
                  disabled={!u.affordable}
                  onClick={() => onTrainUnit(u.unit_type)}
                  title={
                    !u.affordable
                      ? `Cannot afford (${formatCost(u.cost)})`
                      : undefined
                  }
                >
                  <span className="capitalize flex items-center gap-1">
                    <Swords className="h-3 w-3" />
                    {u.unit_type}
                  </span>
                  <span className="text-muted-foreground">
                    {formatCost(u.cost)}
                  </span>
                </Button>
              ))
            )}
          </TabsContent>

          <TabsContent value="build" className="space-y-1 mt-2">
            {!buildable ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : (
              buildable
                .filter((b) => !b.already_built)
                .map((b) => {
                  const queued = queuedBuildings.has(b.building_type)
                  return (
                    <Button
                      key={b.building_type}
                      variant="outline"
                      size="sm"
                      className="w-full justify-between text-xs"
                      disabled={!b.affordable || queued}
                      onClick={() => onBuildBuilding(b.building_type)}
                      title={b.effect}
                    >
                      <span className="capitalize">
                        {b.building_type}
                        {queued && ' — queued'}
                      </span>
                      <span className="text-muted-foreground">
                        {formatCost(b.cost)}
                      </span>
                    </Button>
                  )
                })
            )}
            {buildable && buildable.every((b) => b.already_built) && (
              <p className="text-xs text-muted-foreground">
                Every building is already constructed.
              </p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

interface DiplomacyPanelProps {
  currentPlayer: PlayerId
  diplomacy: DiplomacyStateResponse | null
  selectedOpponent: PlayerId | null
  onSelectOpponent: (opponent: PlayerId | null) => void
  lastSeenMessageIds: Record<PlayerId, number>
  pendingQueuedForOpponent: Array<{
    type: 'SEND_MESSAGE'
    recipient: PlayerId
    body: string
  }>
  onQueueMessage: (recipient: PlayerId, body: string) => void
}

interface DiplomacyThreadViewProps {
  currentPlayer: PlayerId
  diplomacy: DiplomacyStateResponse
  opponent: PlayerId
  pendingQueuedForOpponent: Array<{
    type: 'SEND_MESSAGE'
    recipient: PlayerId
    body: string
  }>
  onSelectOpponent: (opponent: PlayerId | null) => void
  onQueueMessage: (recipient: PlayerId, body: string) => void
}

function DiplomacyThreadView({
  currentPlayer,
  diplomacy,
  opponent,
  pendingQueuedForOpponent,
  onSelectOpponent,
  onQueueMessage,
}: DiplomacyThreadViewProps) {
  const [draft, setDraft] = useState('')
  const thread: DiplomacyMessage[] = diplomacy.messages
    .filter(
      (m) =>
        (m.sender === currentPlayer && m.recipient === opponent) ||
        (m.sender === opponent && m.recipient === currentPlayer),
    )
    .sort((a, b) => a.id - b.id)
  const queuedOutbound = pendingQueuedForOpponent.filter(
    (a) => a.recipient === opponent,
  )
  const relation = findRelation(diplomacy.relations, currentPlayer, opponent)
  const rel = relationLabel(relation)
  const overLimit = draft.length > MESSAGE_BODY_MAX_LENGTH
  const canSend = draft.trim().length > 0 && !overLimit

  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center justify-between gap-2">
          <button
            className="flex items-center gap-1 hover:underline"
            onClick={() => onSelectOpponent(null)}
            aria-label="Back to diplomacy overview"
            data-testid="diplomacy-back"
          >
            <ChevronLeft className="h-4 w-4" />
            <span className="truncate">{opponent}</span>
          </button>
          <span className={`text-xs ${rel.className}`}>{rel.label}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div
          className="max-h-52 overflow-y-auto space-y-1 rounded border bg-muted/20 p-2"
          data-testid="diplomacy-thread"
        >
          {thread.length === 0 && queuedOutbound.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No messages yet. Send the first line to open the channel.
            </p>
          ) : (
            <>
              {thread.map((m) => {
                const mine = m.sender === currentPlayer
                return (
                  <div
                    key={m.id}
                    className={`text-xs ${mine ? 'text-right' : 'text-left'}`}
                    data-testid={`diplomacy-message-${m.id}`}
                  >
                    <div
                      className={`inline-block rounded px-2 py-1 ${
                        mine
                          ? 'bg-primary/10 text-primary-foreground/90'
                          : 'bg-background border'
                      }`}
                    >
                      <span className="block font-medium text-[10px] text-muted-foreground">
                        {mine ? 'you' : m.sender} · turn {m.turn_sent}
                      </span>
                      <span className="whitespace-pre-wrap">{m.body}</span>
                    </div>
                  </div>
                )
              })}
              {queuedOutbound.map((q, idx) => (
                <div
                  key={`queued-${idx}`}
                  className="text-xs text-right opacity-60"
                  data-testid="diplomacy-message-queued"
                >
                  <div className="inline-block rounded border border-dashed px-2 py-1">
                    <span className="block font-medium text-[10px] text-muted-foreground">
                      queued · sends on End Turn
                    </span>
                    <span className="whitespace-pre-wrap">{q.body}</span>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
        <div className="space-y-1">
          <textarea
            className="w-full min-h-16 resize-none rounded border bg-background px-2 py-1 text-xs"
            placeholder="Compose a private message…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-testid="diplomacy-compose"
            maxLength={MESSAGE_BODY_MAX_LENGTH + 1}
          />
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>
              {draft.length}/{MESSAGE_BODY_MAX_LENGTH}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={!canSend}
              onClick={() => {
                onQueueMessage(opponent, draft.trim())
                setDraft('')
              }}
              data-testid="diplomacy-send"
            >
              <Send className="h-3.5 w-3.5 mr-1" />
              Queue message
            </Button>
          </div>
          {overLimit && (
            <p className="text-[10px] text-destructive">
              Message exceeds the {MESSAGE_BODY_MAX_LENGTH}-character limit.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function relationLabel(
  relation: 'peace' | 'alliance' | 'war',
): { label: string; className: string } {
  switch (relation) {
    case 'war':
      return { label: 'at war', className: 'text-destructive' }
    case 'alliance':
      return { label: 'allied', className: 'text-emerald-600' }
    default:
      return { label: 'peace', className: 'text-muted-foreground' }
  }
}

function findRelation(
  relations: DiplomacyRelation[],
  a: PlayerId,
  b: PlayerId,
): 'peace' | 'alliance' | 'war' {
  for (const r of relations) {
    if (
      (r.player_a === a && r.player_b === b) ||
      (r.player_a === b && r.player_b === a)
    ) {
      return r.state
    }
  }
  return 'peace'
}

function treatiesFor(
  treaties: TreatyRecord[],
  a: PlayerId,
  b: PlayerId,
): TreatyRecord[] {
  return treaties.filter(
    (t) =>
      (t.parties[0] === a && t.parties[1] === b) ||
      (t.parties[0] === b && t.parties[1] === a),
  )
}

/** Phase 7 diplomacy sidebar panel.
 *
 * Top view: list of every *other* discovered player with their relation
 * state, treaty count, and an unread-message badge derived from
 * ``diplomacy.message_received`` events that arrived while a thread was
 * closed. Clicking an opponent drills into the thread view — a scrolling
 * message log plus a compose form that queues a ``SEND_MESSAGE`` action
 * into the shared End-Turn queue (not a fire-and-forget REST call), so
 * the PRD's "queued-until-End-Turn" invariant holds for diplomacy too.
 */
function DiplomacyPanel({
  currentPlayer,
  diplomacy,
  selectedOpponent,
  onSelectOpponent,
  lastSeenMessageIds,
  pendingQueuedForOpponent,
  onQueueMessage,
}: DiplomacyPanelProps) {
  if (!diplomacy) {
    return (
      <Card className="rounded-none border-0 border-b">
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Handshake className="h-4 w-4" />
            Diplomacy
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    )
  }

  const opponents = diplomacy.discovered.filter((p) => p !== currentPlayer)

  if (selectedOpponent) {
    return (
      <DiplomacyThreadView
        key={selectedOpponent}
        currentPlayer={currentPlayer}
        diplomacy={diplomacy}
        opponent={selectedOpponent}
        pendingQueuedForOpponent={pendingQueuedForOpponent}
        onSelectOpponent={onSelectOpponent}
        onQueueMessage={onQueueMessage}
      />
    )
  }

  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Handshake className="h-4 w-4" />
          Diplomacy
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 pt-0">
        {opponents.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No other players discovered yet.
          </p>
        ) : (
          opponents.map((opponent) => {
            const relation = findRelation(
              diplomacy.relations,
              currentPlayer,
              opponent,
            )
            const rel = relationLabel(relation)
            const treaties = treatiesFor(
              diplomacy.active_treaties,
              currentPlayer,
              opponent,
            )
            const lastSeen = lastSeenMessageIds[opponent] ?? 0
            const unread = diplomacy.messages.filter(
              (m) =>
                m.sender === opponent &&
                m.recipient === currentPlayer &&
                m.id > lastSeen,
            ).length
            return (
              <button
                key={opponent}
                onClick={() => onSelectOpponent(opponent)}
                className="w-full flex items-center justify-between text-xs rounded px-2 py-1.5 hover:bg-muted/50 border"
                data-testid={`diplomacy-opponent-${opponent}`}
                data-unread={unread > 0 ? 'true' : 'false'}
              >
                <span className="flex flex-col items-start">
                  <span className="font-medium truncate">{opponent}</span>
                  <span className={`text-[10px] ${rel.className}`}>
                    {rel.label}
                    {treaties.length > 0 &&
                      ` · ${treaties.length} treat${treaties.length === 1 ? 'y' : 'ies'}`}
                  </span>
                </span>
                <span className="flex items-center gap-1">
                  {unread > 0 && (
                    <Badge
                      variant="destructive"
                      className="h-4 px-1 text-[10px]"
                      data-testid={`diplomacy-unread-${opponent}`}
                    >
                      {unread}
                    </Badge>
                  )}
                  <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                </span>
              </button>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

interface SubmissionRosterProps {
  players: PlayerId[]
  currentPlayer: PlayerId
  submittedPlayers: Set<PlayerId>
}

/** Per-player turn-submission indicators (Phase 6).
 *
 * Fed by the ``turn.submitted`` WebSocket event and rehydrated from
 * ``GET /turn-submissions`` on mount / turn rollover. Each opponent
 * renders as "submitted" (green check) or "deciding" (amber clock);
 * the current player's own row shows the same state so the user has a
 * single place to confirm their own submission landed.
 */
function SubmissionRoster({
  players,
  currentPlayer,
  submittedPlayers,
}: SubmissionRosterProps) {
  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm">Turn submissions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 pt-0">
        {players.map((p) => {
          const submitted = submittedPlayers.has(p)
          const isSelf = p === currentPlayer
          return (
            <div
              key={p}
              className="flex items-center justify-between text-xs rounded px-2 py-1 bg-muted/30"
              data-testid={`submission-row-${p}`}
              data-submitted={submitted ? 'true' : 'false'}
            >
              <span className="font-medium truncate">
                {p}
                {isSelf && (
                  <span className="ml-1 text-muted-foreground">(you)</span>
                )}
              </span>
              {submitted ? (
                <span className="flex items-center gap-1 text-green-600">
                  <Check className="h-3.5 w-3.5" />
                  submitted
                </span>
              ) : (
                <span className="flex items-center gap-1 text-amber-600">
                  <Clock className="h-3.5 w-3.5" />
                  deciding
                </span>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
