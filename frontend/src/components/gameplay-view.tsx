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

import type React from 'react'
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
  ArrowDown,
  ArrowUp,
  Building2,
  ChevronLeft,
  Check,
  Clock,
  FileSignature,
  Hammer,
  Handshake,
  Landmark,
  Loader2,
  Lock,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Swords,
  Trash2,
  X,
} from 'lucide-react'
import { api, ApiError, queryKeys } from '@/lib/api'
import { PixiMap } from '@/components/pixi-map'
import { RulesReferencePanel } from '@/components/rules-reference-panel'
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
  BuildJob,
  CanFoundCityResponse,
  City,
  Coord,
  DiplomacyMessage,
  DiplomacyRelation,
  DiplomacyStateResponse,
  GameAction,
  GameState,
  AutomationCancelledEvent,
  OrderCancelledEvent,
  PlayerId,
  QueuedAction,
  QueueableTilesResponse,
  ResearchState,
  ResourceBag,
  Tech,
  TechId,
  TechTreeResponse,
  Tile,
  TrainableUnit,
  TrainableUnitsResponse,
  TreatyClause,
  TreatyProposalRecord,
  TreatyRecord,
  TurnSubmissionsResponse,
  Unit,
  ValidAttacksResponse,
  ValidImprovement,
  ValidImprovementsResponse,
  ValidMovesResponse,
} from '@/types/game'
import {
  FREE_TEXT_CLAUSE_MAX_LENGTH,
  MESSAGE_BODY_MAX_LENGTH,
  PEACE_CLAUSE_MAX_DURATION,
} from '@/types/game'

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
    case 'SET_CITY_PRODUCTION':
      return `Queue ${action.unit_type ?? action.building_type} @ city #${action.city_id}`
    case 'CANCEL_CITY_PRODUCTION':
      return `Cancel queue[${action.queue_index}] @ city #${action.city_id}`
    case 'REORDER_CITY_QUEUE':
      return `Reorder queue @ city #${action.city_id} → [${action.new_order.join(', ')}]`
    case 'SEND_MESSAGE': {
      const preview =
        action.body.length > 40
          ? `${action.body.slice(0, 37)}…`
          : action.body
      return `Message → ${action.recipient}: ${preview}`
    }
    case 'PROPOSE_TREATY': {
      const kinds = action.clauses
        .map((c) => c.clause_type.replace(/_/g, ' '))
        .join(', ')
      return `Propose treaty → ${action.recipient} (${kinds || 'empty'})`
    }
    case 'RESPOND_TO_TREATY':
      return `${action.accept ? 'Accept' : 'Decline'} proposal #${action.proposal_id}`
    case 'WITHDRAW_TREATY':
      return `Withdraw proposal #${action.proposal_id}`
    case 'CANCEL_TREATY':
      return `Cancel treaty #${action.treaty_id}`
    case 'DECLARE_WAR':
      return `Declare war on ${action.target_player}`
    case 'SET_ACTIVE_RESEARCH':
      return action.tech_id
        ? `Research ${action.tech_id}`
        : 'Clear active research'
    case 'QUEUE_ORDER':
      return `Queue move unit #${action.unit_id} → (${action.destination.x}, ${action.destination.y})`
    case 'CANCEL_ORDER':
      return `Cancel queued order for unit #${action.unit_id}`
    case 'SET_AUTOMATION':
      return `Set unit #${action.unit_id} → ${action.mode.replace(/_/g, ' ')}`
    case 'CLEAR_AUTOMATION':
      return `Clear automation on unit #${action.unit_id}`
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
  { key: 'science', emoji: '🔬', label: 'Science' },
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
  const total: ResourceBag = {
    food: 0,
    wood: 0,
    ore: 0,
    crystal: 0,
    science: 0,
  }
  const lines: string[] = []

  const myCities = Object.values(state.cities).filter((c) => c.owner === player)
  if (myCities.length > 0) {
    const cityFood = myCities.length * 2
    total.food += cityFood
    lines.push(`+${cityFood} food from ${myCities.length} city base`)

    let cityScience = 0
    for (const city of myCities) {
      cityScience += 1
      if (city.buildings.includes('library')) cityScience += 2
      if (city.buildings.includes('temple')) cityScience += 1
    }
    total.science += cityScience
    lines.push(`+${cityScience} science from ${myCities.length} city base`)
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

interface ResearchIndicatorProps {
  research: ResearchState | null
  scienceStockpile: number
  sciencePerTurn: number
}

/** Minimal Phase 5 research indicator. Shows the active tech and the
 * accumulated progress in science points; the full tech-tree panel
 * with click-to-select and an ETA-in-turns lands in Phase 6.
 */
function ResearchIndicator({
  research,
  scienceStockpile,
  sciencePerTurn,
}: ResearchIndicatorProps) {
  const active = research?.active ?? null
  const progress = research?.progress ?? 0
  const label = active
    ? active
        .split('_')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ')
    : null

  const tooltip = active
    ? `Researching: ${label}\nProgress: ${progress} science\nStockpile: ${scienceStockpile} · +${sciencePerTurn}/turn`
    : `No active research\nStockpile: ${scienceStockpile} · +${sciencePerTurn}/turn`

  return (
    <span
      title={tooltip}
      className="flex items-center gap-1 text-xs text-muted-foreground tabular-nums"
    >
      <span aria-hidden="true">🔬</span>
      {active ? (
        <span>
          Researching <span className="font-medium">{label}</span>
          <span className="ml-1">({progress})</span>
        </span>
      ) : (
        <span className="italic">No research</span>
      )}
    </span>
  )
}

function ResourceBar({ stockpile, yieldBreakdown }: ResourceBarProps) {
  return (
    <div className="flex items-center gap-3 text-sm">
      {RESOURCE_META.map(({ key, emoji, label }) => {
        const amount = stockpile[key] ?? 0
        const delta = yieldBreakdown.total[key] ?? 0
        const relevantLines = yieldBreakdown.lines.filter((l) =>
          l.endsWith(` ${key} from tile yields`) ||
          (key === 'food' && l.includes(' food from ') && l.endsWith('city base')) ||
          (key === 'science' && l.includes(' science from ') && l.endsWith('city base')),
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

// Phase 4 gameplay-improvements — a commandable entity on a tile. See
// ``collectFriendlyEntities``.
type StackEntry =
  | { kind: 'unit'; unit: Unit }
  | { kind: 'city'; city: City }

interface StackSelectorPopoverProps {
  entries: StackEntry[]
  anchor: { x: number; y: number }
  onSelect: (entry: StackEntry) => void
  onClose: () => void
}

function StackSelectorPopover({
  entries,
  anchor,
  onSelect,
  onClose,
}: StackSelectorPopoverProps) {
  // Dismiss on Escape so the popover is keyboard-closable — click-away
  // is handled by the transparent overlay below.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <>
      <div
        data-testid="stack-selector-backdrop"
        className="absolute inset-0 z-40"
        onClick={onClose}
      />
      <div
        data-testid="stack-selector"
        role="menu"
        className="absolute z-50 min-w-[180px] rounded-md border bg-popover text-popover-foreground shadow-lg p-1"
        style={{ left: anchor.x + 12, top: anchor.y + 12 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          Stack ({entries.length})
        </div>
        {entries.map((entry) => {
          if (entry.kind === 'unit') {
            return (
              <button
                key={`unit-${entry.unit.id}`}
                type="button"
                data-testid={`stack-entry-unit-${entry.unit.id}`}
                onClick={() => onSelect(entry)}
                className="w-full flex items-center justify-between gap-4 rounded px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
              >
                <span className="capitalize font-medium">{entry.unit.type}</span>
                <span className="text-xs text-muted-foreground">
                  HP {entry.unit.hp} &middot; Mv {entry.unit.moves_left}
                </span>
              </button>
            )
          }
          return (
            <button
              key={`city-${entry.city.id}`}
              type="button"
              data-testid={`stack-entry-city-${entry.city.id}`}
              onClick={() => onSelect(entry)}
              className="w-full flex items-center justify-between gap-4 rounded px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
            >
              <span className="font-medium">City</span>
              <span className="text-xs text-muted-foreground">HP {entry.city.hp}</span>
            </button>
          )
        })}
      </div>
    </>
  )
}

export function GameplayView({ gameId, currentPlayer }: GameplayViewProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null)
  const [selectedCityId, setSelectedCityId] = useState<number | null>(null)
  const [queue, setQueue] = useState<QueuedAction[]>([])
  const [waiting, setWaiting] = useState(false)
  // Phase 4 gameplay-improvements: stacked-tile selector. When the player
  // clicks a tile that holds 2+ selectable friendly entities (units+city
  // or 2+ units), we show a popover so they can pick which entity to
  // command rather than implicitly grabbing the top of the stack.
  const [stackSelector, setStackSelector] = useState<{
    tile: Tile
    screenX: number
    screenY: number
  } | null>(null)
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
    const isFirstHydration = hydratedTurnRef.current === null
    hydratedTurnRef.current = mySubmission.turn
    if (mySubmission.submitted) {
      const restored = mySubmission.actions.map((action) => ({
        queue_id: newQueueId(),
        action,
      }))
      queueMicrotask(() => {
        setQueue(restored)
        setWaiting(true)
      })
    } else if (!isFirstHydration) {
      // Turn rolled over and we haven't submitted yet — clear any stale
      // queue, selection, and waiting flag left over from the previous
      // turn in case the turn.resolved WS frame was missed (reconnect,
      // tab backgrounded, polling fallback). Mirrors the WS handler's
      // reset so the two paths converge on the same fresh-turn state.
      // First hydration on mount is skipped so we don't race against
      // user interactions that land before mySubmission resolves.
      queueMicrotask(() => {
        setQueue([])
        setSelectedUnitId(null)
        setSelectedCityId(null)
        setWaiting(false)
      })
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

  // Phase 6 — tech tree panel data. Invalidated on turn.resolved (below)
  // and on research.completed so the UI reflects the unlock the moment
  // it lands rather than waiting for the next poll.
  const techTreeQueryKey = queryKeys.techTree(gameId)
  const { data: techTreeData } = useQuery<TechTreeResponse | null>({
    queryKey: techTreeQueryKey,
    queryFn: () => api.getTechTree(gameId),
    enabled: gameState != null,
  })

  // ---- Per-unit affordance queries ---------------------------------------

  const selectedUnit: Unit | null =
    selectedUnitId != null && gameState
      ? gameState.units[selectedUnitId] ?? null
      : null

  // Affordance queries are keyed on ``gameState.turn`` so each turn gets
  // its own cache bucket. Without the turn in the key the app's 5-minute
  // staleTime would return the previous turn's valid-moves/attacks for a
  // re-selected unit whose moves_left has since drained to 0 — the tiles
  // would render as highlighted even though the server would now reject
  // the move.
  const affordanceTurn = gameState?.turn ?? null

  const { data: validMoves } = useQuery<ValidMovesResponse | null>({
    queryKey: ['game', gameId, 'validMoves', selectedUnitId, affordanceTurn],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getValidMoves(gameId, selectedUnitId),
    enabled: selectedUnitId != null && affordanceTurn != null,
  })

  const { data: validAttacks } = useQuery<ValidAttacksResponse | null>({
    queryKey: ['game', gameId, 'validAttacks', selectedUnitId, affordanceTurn],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getValidAttacks(gameId, selectedUnitId),
    enabled: selectedUnitId != null && affordanceTurn != null,
  })

  // Phase 5: multi-turn queueable destinations for the selected unit.
  // Independent of ``validMoves`` because this endpoint ignores
  // ``moves_left`` — it returns every reachable tile so the player can
  // click a far-off tile to enqueue a ``QUEUE_ORDER`` action.
  const { data: queueableTilesData } =
    useQuery<QueueableTilesResponse | null>({
      queryKey: [
        'game',
        gameId,
        'queueableTiles',
        selectedUnitId,
        affordanceTurn,
      ],
      queryFn: () =>
        selectedUnitId == null
          ? Promise.resolve(null)
          : api.getQueueableTiles(gameId, selectedUnitId),
      enabled: selectedUnitId != null && affordanceTurn != null,
    })

  const { data: canFoundCity } = useQuery<CanFoundCityResponse | null>({
    queryKey: ['game', gameId, 'canFoundCity', selectedUnitId, affordanceTurn],
    queryFn: () =>
      selectedUnitId == null
        ? Promise.resolve(null)
        : api.getCanFoundCity(gameId, selectedUnitId),
    enabled:
      selectedUnitId != null &&
      affordanceTurn != null &&
      selectedUnit?.type === 'worker',
  })

  const { data: validImprovements } =
    useQuery<ValidImprovementsResponse | null>({
      queryKey: [
        'game',
        gameId,
        'validImprovements',
        selectedUnitId,
        affordanceTurn,
      ],
      queryFn: () =>
        selectedUnitId == null
          ? Promise.resolve(null)
          : api.getValidImprovements(gameId, selectedUnitId),
      enabled:
        selectedUnitId != null &&
        affordanceTurn != null &&
        selectedUnit?.type === 'worker',
    })

  // ---- Per-city affordance queries ---------------------------------------

  const selectedCity =
    selectedCityId != null && gameState
      ? gameState.cities[selectedCityId] ?? null
      : null

  const { data: trainableUnits } = useQuery<TrainableUnitsResponse | null>({
    queryKey: [
      'game',
      gameId,
      'trainableUnits',
      selectedCityId,
      affordanceTurn,
    ],
    queryFn: () =>
      selectedCityId == null
        ? Promise.resolve(null)
        : api.getTrainableUnits(gameId, selectedCityId),
    enabled: selectedCityId != null && affordanceTurn != null,
  })

  const { data: buildableBuildings } =
    useQuery<BuildableBuildingsResponse | null>({
      queryKey: [
        'game',
        gameId,
        'buildableBuildings',
        selectedCityId,
        affordanceTurn,
      ],
      queryFn: () =>
        selectedCityId == null
          ? Promise.resolve(null)
          : api.getBuildableBuildings(gameId, selectedCityId),
      enabled: selectedCityId != null && affordanceTurn != null,
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

  // Phase 5: tiles already targeted by a locally-queued QUEUE_ORDER for
  // the selected unit — removed from the queueable-tile highlight so
  // clicks aren't no-ops.
  const queuedOrderKeys = useMemo(() => {
    const out = new Set<string>()
    for (const q of queue) {
      if (
        q.action.type === 'QUEUE_ORDER' &&
        q.action.unit_id === selectedUnitId
      ) {
        out.add(`${q.action.destination.x},${q.action.destination.y}`)
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

  // Per-destination path preview — the server returns the chosen path
  // alongside each reachable tile so the client doesn't duplicate any
  // pathfinding rules (Phase 2).
  const movePathsByTile = useMemo(() => {
    const out: Record<string, Coord[]> = {}
    if (!validMoves) return out
    for (const m of validMoves.moves) {
      const key = `${m.x},${m.y}`
      if (queuedMoveKeys.has(key)) continue
      out[key] = m.path
    }
    return out
  }, [validMoves, queuedMoveKeys])

  const attackTiles: Coord[] = useMemo(() => {
    if (!validAttacks) return []
    return validAttacks.targets
      .filter((t) => !queuedAttackKeys.has(`${t.x},${t.y}`))
      .map((t) => ({ x: t.x, y: t.y }))
  }, [validAttacks, queuedAttackKeys])

  // Phase 5: split the queueable-tiles response into tiles the user can
  // still click (not within this turn's budget, not already queued, not
  // flagged as a move/attack in the same turn). Pre-compute the path
  // lookup for hover preview and the committed-order overlay.
  const queueableTilesCoords: Coord[] = useMemo(() => {
    if (!queueableTilesData) return []
    const budgetLeft = validMoves?.moves_left ?? 0
    return queueableTilesData.tiles
      .filter((t) => {
        const key = `${t.x},${t.y}`
        if (queuedOrderKeys.has(key)) return false
        if (queuedMoveKeys.has(key)) return false
        if (t.cost <= budgetLeft) return false
        return true
      })
      .map((t) => ({ x: t.x, y: t.y }))
  }, [queueableTilesData, validMoves, queuedOrderKeys, queuedMoveKeys])

  const queueableKeys = useMemo(
    () => new Set(queueableTilesCoords.map((t) => `${t.x},${t.y}`)),
    [queueableTilesCoords],
  )

  const queueablePathsByTile = useMemo(() => {
    const out: Record<string, Coord[]> = {}
    if (!queueableTilesData) return out
    for (const t of queueableTilesData.tiles) {
      const key = `${t.x},${t.y}`
      if (!queueableKeys.has(key)) continue
      out[key] = t.path
    }
    return out
  }, [queueableTilesData, queueableKeys])

  // The server-persisted queued order (head of the unit's orders_queue)
  // for the selected unit. Used to render the committed blue path so
  // the player always sees where a queued unit is heading, even after a
  // page refresh.
  const queuedOrderForSelected = useMemo(() => {
    if (!selectedUnit) return null
    const head = selectedUnit.orders_queue?.[0]
    return head ?? null
  }, [selectedUnit])

  const queuedOrderPath = useMemo<Coord[] | null>(() => {
    if (!queuedOrderForSelected || !queueableTilesData) return null
    const key = `${queuedOrderForSelected.destination.x},${queuedOrderForSelected.destination.y}`
    const match = queueableTilesData.tiles.find(
      (t) => `${t.x},${t.y}` === key,
    )
    return match?.path ?? null
  }, [queuedOrderForSelected, queueableTilesData])

  // Also surface locally-queued (pre-submit) QUEUE_ORDER for the
  // selected unit as a path overlay so the player gets immediate visual
  // feedback after clicking.
  const locallyQueuedOrderForSelected = useMemo(() => {
    if (selectedUnitId == null) return null
    for (let i = queue.length - 1; i >= 0; i--) {
      const a = queue[i].action
      if (a.type === 'QUEUE_ORDER' && a.unit_id === selectedUnitId) return a
      if (a.type === 'CANCEL_ORDER' && a.unit_id === selectedUnitId) return null
    }
    return null
  }, [queue, selectedUnitId])

  const committedOrderPath = useMemo<Coord[] | null>(() => {
    const localOrder = locallyQueuedOrderForSelected
    if (localOrder && queueableTilesData) {
      const key = `${localOrder.destination.x},${localOrder.destination.y}`
      const match = queueableTilesData.tiles.find(
        (t) => `${t.x},${t.y}` === key,
      )
      if (match) return match.path
    }
    return queuedOrderPath
  }, [locallyQueuedOrderForSelected, queueableTilesData, queuedOrderPath])

  const committedOrderDestination = useMemo<Coord | null>(() => {
    if (locallyQueuedOrderForSelected)
      return locallyQueuedOrderForSelected.destination
    if (queuedOrderForSelected) return queuedOrderForSelected.destination
    return null
  }, [locallyQueuedOrderForSelected, queuedOrderForSelected])

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
      const topId = tile.unit_ids?.[tile.unit_ids.length - 1]
      if (topId === undefined) return null
      return state.units[topId] ?? null
    },
    [],
  )

  // Phase 4 gameplay-improvements: enumerate the player-commandable
  // entities sitting on a tile. We only include friendlies because the
  // click handler only ever sets a selection for things the current
  // player controls — enemy presence is surfaced elsewhere (hover
  // tooltip, attack-target overlay).
  const collectFriendlyEntities = useCallback(
    (state: GameState, tile: Tile, owner: PlayerId): StackEntry[] => {
      const out: StackEntry[] = []
      const unitIds = tile.unit_ids ?? []
      for (const unitId of unitIds) {
        const unit = state.units[unitId]
        if (unit && unit.owner === owner) out.push({ kind: 'unit', unit })
      }
      if (tile.city_id) {
        const city = state.cities[tile.city_id]
        if (city && city.owner === owner) out.push({ kind: 'city', city })
      }
      return out
    },
    [],
  )

  const handleTileClick = useCallback(
    (tile: Tile, screen?: { x: number; y: number }) => {
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
        setStackSelector(null)
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
        setStackSelector(null)
        return
      }

      // Phase 5 multi-turn queueable destination — tiles beyond this
      // turn's budget but reachable. Replaces any prior QUEUE_ORDER for
      // the same unit in the pending queue so rapid clicks don't pile up
      // stale orders.
      if (selectedUnitId != null && queueableKeys.has(key)) {
        setQueue((prev) => {
          const filtered = prev.filter(
            (q) =>
              !(
                q.action.type === 'QUEUE_ORDER' &&
                q.action.unit_id === selectedUnitId
              ),
          )
          return [
            ...filtered,
            {
              queue_id: newQueueId(),
              action: {
                type: 'QUEUE_ORDER',
                unit_id: selectedUnitId,
                destination: { x: tile.loc.x, y: tile.loc.y },
              },
            },
          ]
        })
        setStackSelector(null)
        return
      }

      // Phase 4 gameplay-improvements: if the clicked tile has 2+
      // friendly selectable entities, open the stack selector so the
      // player picks which entity to command.
      const friendly = collectFriendlyEntities(gameState, tile, currentPlayer)
      if (friendly.length >= 2 && screen) {
        setStackSelector({ tile, screenX: screen.x, screenY: screen.y })
        return
      }

      // Single friendly entity (or none) — fall through to the
      // direct-selection behaviour.
      setStackSelector(null)

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
      queueableKeys,
      lookupUnitAtTile,
      collectFriendlyEntities,
      currentPlayer,
    ],
  )

  // Phase 4 gameplay-improvements: derive the selectable entries on the
  // stack-selector tile from the live game state. Using the current
  // ``gameState`` (not a snapshot captured at click time) keeps the
  // popover coherent if a WS tick arrives between click and render.
  const stackSelectorEntries = useMemo<StackEntry[]>(() => {
    if (!stackSelector || !gameState) return []
    // Resolve the latest copy of the tile by coord — ``gameState.tiles``
    // is rebuilt on every refetch so the captured ``tile`` reference
    // would otherwise go stale.
    const { x, y } = stackSelector.tile.loc
    const fresh =
      gameState.tiles.find((t) => t.loc.x === x && t.loc.y === y) ??
      stackSelector.tile
    return collectFriendlyEntities(gameState, fresh, currentPlayer)
  }, [stackSelector, gameState, collectFriendlyEntities, currentPlayer])

  // Auto-dismiss the selector if the tile no longer has 2+ selectable
  // entities (e.g. a unit moved away or was killed between ticks).
  // Deferred via queueMicrotask to match the hydration-effect pattern
  // used elsewhere in this file and satisfy the cascading-render lint.
  useEffect(() => {
    if (!stackSelector) return
    if (stackSelectorEntries.length < 2) {
      queueMicrotask(() => setStackSelector(null))
    }
  }, [stackSelector, stackSelectorEntries.length])

  const selectStackEntry = useCallback((entry: StackEntry) => {
    if (entry.kind === 'unit') {
      setSelectedUnitId(entry.unit.id)
      setSelectedCityId(null)
    } else {
      setSelectedCityId(entry.city.id)
      setSelectedUnitId(null)
    }
    setStackSelector(null)
  }, [])

  // Phase 4 gameplay-improvements: Tab cycles the active selection
  // through every friendly entity on the currently-selected tile. No-op
  // if focus is inside a form control so typing in the diplomacy
  // composer isn't hijacked.
  useEffect(() => {
    if (!gameState) return
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const target = e.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
        if (target.isContentEditable) return
      }
      // Find the tile that holds the current selection.
      let tile: Tile | null = null
      if (selectedUnitId != null) {
        const u = gameState.units[selectedUnitId]
        if (u) {
          tile = gameState.tiles.find(
            (t) => t.loc.x === u.loc.x && t.loc.y === u.loc.y,
          ) ?? null
        }
      } else if (selectedCityId != null) {
        const c = gameState.cities[selectedCityId]
        if (c) {
          tile = gameState.tiles.find(
            (t) => t.loc.x === c.loc.x && t.loc.y === c.loc.y,
          ) ?? null
        }
      }
      if (!tile) return
      const entries = collectFriendlyEntities(gameState, tile, currentPlayer)
      if (entries.length < 2) return
      e.preventDefault()
      const currentIdx = entries.findIndex((entry) =>
        entry.kind === 'unit'
          ? entry.unit.id === selectedUnitId
          : entry.city.id === selectedCityId,
      )
      const step = e.shiftKey ? -1 : 1
      const nextIdx =
        (currentIdx + step + entries.length) % entries.length
      selectStackEntry(entries[nextIdx])
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [
    gameState,
    selectedUnitId,
    selectedCityId,
    collectFriendlyEntities,
    currentPlayer,
    selectStackEntry,
  ])

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

  // Last SET_ACTIVE_RESEARCH in the queue wins — the tech panel shows
  // the queued pick as "selected" ahead of server confirmation so the
  // click-to-set-active interaction feels immediate. ``undefined`` when
  // nothing is queued (the research indicator falls back to the
  // server-reported active tech).
  const queuedResearchTechId = useMemo<TechId | null | undefined>(() => {
    for (let i = queue.length - 1; i >= 0; i--) {
      const a = queue[i].action
      if (a.type === 'SET_ACTIVE_RESEARCH') return a.tech_id
    }
    return undefined
  }, [queue])

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
    queueMicrotask(() => {
      setQueue([])
      setSelectedUnitId(null)
      setSelectedCityId(null)
      setWaiting(false)
      // Clear the submission roster for the upcoming turn — the hydration
      // query will reseed it (empty) on the next render, but resetting here
      // avoids a flicker where last turn's "submitted" ticks linger.
      setSubmittedPlayers(new Set())
    })
    queryClient.invalidateQueries({ queryKey: stateQueryKey })
    queryClient.invalidateQueries({
      queryKey: queryKeys.gameDetail(gameId),
    })
    queryClient.invalidateQueries({ queryKey: diplomacyQueryKey })
    queryClient.invalidateQueries({ queryKey: techTreeQueryKey })
  }, [
    lastEvent,
    queryClient,
    stateQueryKey,
    gameId,
    diplomacyQueryKey,
    techTreeQueryKey,
  ])

  // Phase 6: research.completed — the backend emits this owner-scoped
  // the moment a tech lands. Invalidate the tech-tree query so the
  // panel and the city menus reflect the unlock immediately, and
  // surface a toast naming the unlocked items so the player gets the
  // reward feedback without hunting through the panel.
  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'research.completed') return
    const payload = lastEvent as unknown as {
      tech_id?: TechId
      tech_name?: string
      unlocks_units?: string[]
      unlocks_buildings?: string[]
    }
    const name = payload.tech_name ?? payload.tech_id ?? 'Unknown tech'
    const unlocks = [
      ...(payload.unlocks_units ?? []),
      ...(payload.unlocks_buildings ?? []),
    ]
    toast({
      title: `Researched: ${name}`,
      description:
        unlocks.length > 0
          ? `Unlocked ${unlocks.join(', ')}`
          : 'No new unlocks.',
    })
    queryClient.invalidateQueries({ queryKey: techTreeQueryKey })
    queryClient.invalidateQueries({ queryKey: stateQueryKey })
  }, [lastEvent, queryClient, techTreeQueryKey, stateQueryKey, toast])

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

  // Phase 8 / Phase 9: diplomacy lifecycle live updates. Any of the
  // scoped diplomacy events (treaty proposal/response/cancellation from
  // Phase 8 + war declaration from Phase 9) invalidates the diplomacy
  // query so the panel reflects post-resolution state. The events are
  // already scoped to the parties on the server so receiving a frame is
  // itself enough evidence we need to refetch.
  useEffect(() => {
    if (!lastEvent) return
    const t = lastEvent.type
    if (
      t !== 'diplomacy.proposal_received' &&
      t !== 'diplomacy.proposal_responded' &&
      t !== 'diplomacy.treaty_cancelled' &&
      t !== 'diplomacy.war_declared'
    ) {
      return
    }
    queryClient.invalidateQueries({ queryKey: diplomacyQueryKey })
  }, [lastEvent, queryClient, diplomacyQueryKey])

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

  // Phase 5: surface queued-order cancellations as toasts. Owner-scoped
  // ``order_events`` accumulate in ``GameState`` — track the highest id
  // we've already shown so the user sees each event exactly once, even
  // across refetches.
  const lastShownOrderEventIdRef = useRef<number>(0)
  useEffect(() => {
    const events: OrderCancelledEvent[] = gameState?.order_events ?? []
    if (events.length === 0) return
    let maxSeen = lastShownOrderEventIdRef.current
    const fresh = events.filter((e) => e.id > lastShownOrderEventIdRef.current)
    for (const ev of fresh) {
      if (ev.id > maxSeen) maxSeen = ev.id
      const reasonText: Record<OrderCancelledEvent['reason'], string> = {
        enemy_sighted: 'enemy spotted',
        obstructed: 'path obstructed',
        attacked: 'unit was attacked',
        completed: 'destination reached',
      }
      toast({
        title: `Queued move cancelled (unit #${ev.unit_id})`,
        description:
          ev.reason === 'completed'
            ? 'Unit reached its destination.'
            : `Cancelled: ${reasonText[ev.reason]}.`,
        variant: ev.reason === 'completed' ? 'default' : 'destructive',
      })
    }
    lastShownOrderEventIdRef.current = maxSeen
  }, [gameState?.order_events, toast])

  // Phase 6: surface automation cancellations as toasts. Same
  // high-water-mark pattern as the queued-order events above.
  const lastShownAutomationEventIdRef = useRef<number>(0)
  useEffect(() => {
    const events: AutomationCancelledEvent[] =
      gameState?.automation_events ?? []
    if (events.length === 0) return
    let maxSeen = lastShownAutomationEventIdRef.current
    const fresh = events.filter(
      (e) => e.id > lastShownAutomationEventIdRef.current,
    )
    for (const ev of fresh) {
      if (ev.id > maxSeen) maxSeen = ev.id
      const reasonText: Record<AutomationCancelledEvent['reason'], string> = {
        enemy_adjacent: 'enemy moved adjacent',
        manual_override: 'manual action submitted',
        no_target: 'no improvable tile reachable',
      }
      toast({
        title: `Auto-improve stopped (unit #${ev.unit_id})`,
        description: `Cancelled: ${reasonText[ev.reason]}.`,
        variant: 'destructive',
      })
    }
    lastShownAutomationEventIdRef.current = maxSeen
  }, [gameState?.automation_events, toast])

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
                science: 0,
              }
            }
            yieldBreakdown={computeYieldBreakdown(gameState, currentPlayer)}
          />
          <ResearchIndicator
            research={gameState.research?.[currentPlayer] ?? null}
            scienceStockpile={
              gameState.stockpiles[currentPlayer]?.science ?? 0
            }
            sciencePerTurn={
              computeYieldBreakdown(gameState, currentPlayer).total.science
            }
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
            movePathsByTile={movePathsByTile}
            attackTiles={attackTiles}
            queueableTiles={queueableTilesCoords}
            queueablePathsByTile={queueablePathsByTile}
            queuedOrderPath={committedOrderPath}
            queuedOrderDestination={committedOrderDestination}
            onTileClick={handleTileClick}
          />
          {stackSelector && stackSelectorEntries.length >= 2 ? (
            <StackSelectorPopover
              entries={stackSelectorEntries}
              anchor={{ x: stackSelector.screenX, y: stackSelector.screenY }}
              onSelect={selectStackEntry}
              onClose={() => setStackSelector(null)}
            />
          ) : null}
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
              productionRate={
                2 +
                (selectedCity.build_queue?.[0]?.type === 'unit' &&
                selectedCity.buildings?.includes('barracks')
                  ? 1
                  : 0)
              }
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
              onCancelQueueEntry={(queue_index) =>
                appendToQueue({
                  type: 'CANCEL_CITY_PRODUCTION',
                  city_id: selectedCity.id,
                  queue_index,
                })
              }
              onReorderQueue={(new_order) =>
                appendToQueue({
                  type: 'REORDER_CITY_QUEUE',
                  city_id: selectedCity.id,
                  new_order,
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
              queuedOrderDestination={committedOrderDestination}
              queueableCount={queueableTilesCoords.length}
              automationTogglePending={queue.some(
                (q) =>
                  (q.action.type === 'SET_AUTOMATION' ||
                    q.action.type === 'CLEAR_AUTOMATION') &&
                  selectedUnit !== null &&
                  q.action.unit_id === selectedUnit.id,
              )}
              onToggleAutoImprove={() => {
                if (!selectedUnit) return
                const isActive =
                  selectedUnit.automation === 'auto_improve'
                // Drop any pending automation toggle for this unit so the
                // user can't stack two conflicting toggles in the same
                // turn buffer.
                setQueue((prev) => {
                  const filtered = prev.filter(
                    (q) =>
                      !(
                        (q.action.type === 'SET_AUTOMATION' ||
                          q.action.type === 'CLEAR_AUTOMATION') &&
                        q.action.unit_id === selectedUnit.id
                      ),
                  )
                  return [
                    ...filtered,
                    {
                      queue_id: newQueueId(),
                      action: isActive
                        ? {
                            type: 'CLEAR_AUTOMATION',
                            unit_id: selectedUnit.id,
                          }
                        : {
                            type: 'SET_AUTOMATION',
                            unit_id: selectedUnit.id,
                            mode: 'auto_improve',
                          },
                    },
                  ]
                })
              }}
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
              onCancelQueuedOrder={() => {
                if (!selectedUnit) return
                // Drop any locally-buffered QUEUE_ORDER for this unit and
                // append a CANCEL_ORDER for any server-persisted queue.
                setQueue((prev) => {
                  const filtered = prev.filter(
                    (q) =>
                      !(
                        q.action.type === 'QUEUE_ORDER' &&
                        q.action.unit_id === selectedUnit.id
                      ),
                  )
                  // Only append CANCEL_ORDER if the server actually has a
                  // queue — otherwise we'd send a no-op the validator
                  // rejects.
                  const hasServerQueue =
                    (selectedUnit.orders_queue?.length ?? 0) > 0
                  if (!hasServerQueue) return filtered
                  // De-dupe: don't append a second CANCEL_ORDER if one is
                  // already queued.
                  const alreadyCancelling = filtered.some(
                    (q) =>
                      q.action.type === 'CANCEL_ORDER' &&
                      q.action.unit_id === selectedUnit.id,
                  )
                  if (alreadyCancelling) return filtered
                  return [
                    ...filtered,
                    {
                      queue_id: newQueueId(),
                      action: {
                        type: 'CANCEL_ORDER',
                        unit_id: selectedUnit.id,
                      },
                    },
                  ]
                })
              }}
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
            queuedActions={queue.map((q) => q.action)}
            onQueueMessage={(recipient, body) =>
              appendToQueue({ type: 'SEND_MESSAGE', recipient, body })
            }
            onQueueProposeTreaty={(recipient, clauses) =>
              appendToQueue({ type: 'PROPOSE_TREATY', recipient, clauses })
            }
            onQueueRespondToTreaty={(proposal_id, accept) =>
              appendToQueue({ type: 'RESPOND_TO_TREATY', proposal_id, accept })
            }
            onQueueWithdrawTreaty={(proposal_id) =>
              appendToQueue({ type: 'WITHDRAW_TREATY', proposal_id })
            }
            onQueueCancelTreaty={(treaty_id) =>
              appendToQueue({ type: 'CANCEL_TREATY', treaty_id })
            }
            onQueueDeclareWar={(target_player) =>
              appendToQueue({ type: 'DECLARE_WAR', target_player })
            }
          />

          {/* Rules reference (Phase 1) — static canonical payload. */}
          <RulesReferencePanel />

          {/* Tech tree panel (Phase 6) */}
          <TechTreePanel
            techTree={techTreeData?.tech_tree ?? null}
            research={techTreeData?.research ?? null}
            sciencePerTurn={
              computeYieldBreakdown(gameState, currentPlayer).total.science
            }
            queuedResearchTechId={queuedResearchTechId}
            onSelectActive={(tech_id) =>
              appendToQueue({ type: 'SET_ACTIVE_RESEARCH', tech_id })
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
  /** Phase 5: active queued-order destination (server or locally
   * buffered). When present, the panel shows a one-click cancel. */
  queuedOrderDestination: Coord | null
  /** Phase 5: count of reachable destinations beyond this turn's budget.
   * Used to explain the blue tile highlight to the player. */
  queueableCount: number
  /** Phase 6: true if the currently-selected worker has a pending
   * SET_AUTOMATION / CLEAR_AUTOMATION action in the local submission
   * buffer. Used to grey out the toggle so it is not hammered twice. */
  automationTogglePending: boolean
  onFoundCity: () => void
  onBuildImprovement: (improvement: ValidImprovement['improvement']) => void
  onCancelQueuedOrder: () => void
  /** Phase 6: toggle auto-improve on the selected worker. */
  onToggleAutoImprove: () => void
}

function UnitPanel({
  unit,
  highlightedCount,
  attackCount,
  canFoundCity,
  validImprovements,
  foundCityQueued,
  improvementQueued,
  queuedOrderDestination,
  queueableCount,
  automationTogglePending,
  onFoundCity,
  onBuildImprovement,
  onCancelQueuedOrder,
  onToggleAutoImprove,
}: UnitPanelProps) {
  const isWorker = unit?.type === 'worker'
  const automationActive = unit?.automation === 'auto_improve'
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
                {queueableCount > 0 && (
                  <>
                    {' '}
                    &middot; {queueableCount} queueable
                  </>
                )}
              </div>
            </div>

            {queuedOrderDestination && (
              <div className="rounded border border-blue-500/40 bg-blue-500/10 px-2 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    Queued move → ({queuedOrderDestination.x},{' '}
                    {queuedOrderDestination.y})
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-6 px-2 text-xs"
                    onClick={onCancelQueuedOrder}
                  >
                    Cancel
                  </Button>
                </div>
                <p className="text-muted-foreground mt-1">
                  Cancels automatically on newly visible enemies,
                  obstruction, or combat damage.
                </p>
              </div>
            )}

            {isWorker && (
              <div className="rounded border border-amber-500/40 bg-amber-500/5 px-2 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    Auto-improve{' '}
                    <span
                      className={
                        automationActive
                          ? 'text-amber-600'
                          : 'text-muted-foreground'
                      }
                    >
                      {automationActive ? 'on' : 'off'}
                    </span>
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-6 px-2 text-xs"
                    disabled={automationTogglePending}
                    onClick={onToggleAutoImprove}
                    data-testid="auto-improve-toggle"
                  >
                    {automationActive ? 'Disable' : 'Enable'}
                  </Button>
                </div>
                <p className="text-muted-foreground mt-1">
                  Routes the worker to the nearest unimproved owned tile
                  and builds on arrival. Cancels automatically if an
                  enemy moves adjacent.
                </p>
              </div>
            )}

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
  city: {
    id: number
    loc: Coord
    hp: number
    buildings: string[]
    build_queue: BuildJob[]
  }
  trainable: TrainableUnit[] | null
  buildable: BuildableBuilding[] | null
  queuedBuildings: Set<string>
  /** Production points this city accrues per turn for the active job's
   * kind. Used to render "N turns remaining" on the progress indicator. */
  productionRate: number
  onTrainUnit: (unit_type: TrainableUnit['unit_type']) => void
  onBuildBuilding: (building_type: BuildableBuilding['building_type']) => void
  /** Phase 4: queue manipulation. Arguments are queue indices into the
   * server-known ``city.build_queue``; the UI submits the action for
   * the next End Turn resolution. */
  onCancelQueueEntry: (queue_index: number) => void
  onReorderQueue: (new_order: number[]) => void
}

function CityPanel({
  city,
  trainable,
  buildable,
  queuedBuildings,
  productionRate,
  onTrainUnit,
  onBuildBuilding,
  onCancelQueueEntry,
  onReorderQueue,
}: CityPanelProps) {
  const queue = useMemo(() => city.build_queue ?? [], [city.build_queue])
  const activeJob = queue[0] ?? null
  const turnsRemaining = activeJob
    ? Math.max(
        1,
        Math.ceil((activeJob.total_cost - activeJob.progress) / productionRate),
      )
    : 0
  const progressPct = activeJob
    ? Math.min(
        100,
        Math.round((activeJob.progress / activeJob.total_cost) * 100),
      )
    : 0
  const swapEntries = (a: number, b: number) => {
    if (a < 0 || b < 0 || a >= queue.length || b >= queue.length) return
    const order = queue.map((_, idx) => idx)
    ;[order[a], order[b]] = [order[b], order[a]]
    onReorderQueue(order)
  }
  const queuedBuildingsCombined = useMemo(() => {
    const out = new Set<string>(queuedBuildings)
    for (const job of queue) {
      if (job.type === 'building') out.add(job.target)
    }
    return out
  }, [queuedBuildings, queue])
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
        {activeJob && (
          <div
            data-testid="city-production-indicator"
            className="mb-3 rounded-md border bg-muted/40 px-2 py-2 text-xs"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1 font-medium">
                <Clock className="h-3 w-3" />
                Producing <span className="capitalize">{activeJob.target}</span>
              </span>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">
                  {turnsRemaining} turn{turnsRemaining === 1 ? '' : 's'} left
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => onCancelQueueEntry(0)}
                  title={`Cancel ${activeJob.target} — forfeits ${activeJob.progress} production`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            <div className="mt-1 h-1.5 w-full rounded bg-background">
              <div
                className="h-1.5 rounded bg-primary"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="mt-1 text-muted-foreground">
              {activeJob.progress}/{activeJob.total_cost} production
              &middot; {productionRate}/turn
            </div>
          </div>
        )}
        {queue.length > 1 && (
          <div
            data-testid="city-queue-list"
            className="mb-3 space-y-1 text-xs"
          >
            <div className="text-muted-foreground font-medium">
              Queued ({queue.length - 1})
            </div>
            {queue.slice(1).map((job, i) => {
              const idx = i + 1
              return (
                <div
                  key={idx}
                  className="flex items-center justify-between rounded-md border bg-muted/20 px-2 py-1"
                >
                  <span className="capitalize">{job.target}</span>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      disabled={idx <= 1}
                      onClick={() => swapEntries(idx, idx - 1)}
                      title="Move up"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      disabled={idx >= queue.length - 1}
                      onClick={() => swapEntries(idx, idx + 1)}
                      title="Move down"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => onCancelQueueEntry(idx)}
                      title={`Cancel ${job.target} — refunds cost (not yet started)`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
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
                  disabled={!u.affordable || u.locked}
                  onClick={() => onTrainUnit(u.unit_type)}
                  title={
                    u.locked
                      ? `Requires: ${u.required_tech_name ?? u.required_tech}`
                      : !u.affordable
                        ? `Cannot afford (${formatCost(u.cost)})`
                        : activeJob
                          ? `Queues behind ${activeJob.target}`
                          : undefined
                  }
                >
                  <span className="capitalize flex items-center gap-1">
                    <Swords className="h-3 w-3" />
                    {u.unit_type}
                    {u.locked && (
                      <Lock
                        aria-label={`Requires ${u.required_tech_name ?? u.required_tech}`}
                        className="h-3 w-3 text-muted-foreground"
                      />
                    )}
                  </span>
                  <span className="text-muted-foreground">
                    {u.locked
                      ? `Requires ${u.required_tech_name ?? u.required_tech}`
                      : formatCost(u.cost)}
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
                  const queued = queuedBuildingsCombined.has(b.building_type)
                  return (
                    <Button
                      key={b.building_type}
                      variant="outline"
                      size="sm"
                      className="w-full justify-between text-xs"
                      disabled={!b.affordable || queued || b.locked}
                      onClick={() => onBuildBuilding(b.building_type)}
                      title={
                        b.locked
                          ? `Requires: ${b.required_tech_name ?? b.required_tech}`
                          : queued
                            ? `${b.building_type} already in queue`
                            : activeJob
                              ? `Queues behind ${activeJob.target}`
                              : b.effect
                      }
                    >
                      <span className="capitalize flex items-center gap-1">
                        {b.building_type}
                        {b.locked && (
                          <Lock
                            aria-label={`Requires ${b.required_tech_name ?? b.required_tech}`}
                            className="h-3 w-3 text-muted-foreground"
                          />
                        )}
                        {queued && ' — queued'}
                      </span>
                      <span className="text-muted-foreground">
                        {b.locked
                          ? `Requires ${b.required_tech_name ?? b.required_tech}`
                          : formatCost(b.cost)}
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

/** Phase 6 — tech tree panel. One card with every tech grouped by state
 * (researched / in-progress / available / locked). Clicking an entry in
 * the available group queues ``SET_ACTIVE_RESEARCH``; the queued pick
 * is shown as the active selection pre-submit so the interaction feels
 * immediate. Parallels the diplomacy panel in layout and styling. */
interface TechTreePanelProps {
  techTree: Record<TechId, Tech> | null
  research: ResearchState | null
  sciencePerTurn: number
  /** If the queue already holds a SET_ACTIVE_RESEARCH, this is its
   * ``tech_id`` (or null for a clear action). ``undefined`` means no
   * queued change — fall back to ``research.active``. */
  queuedResearchTechId: TechId | null | undefined
  onSelectActive: (techId: TechId | null) => void
}

type TechState = 'researched' | 'in_progress' | 'available' | 'locked'

function techState(
  tech: Tech,
  completed: Set<TechId>,
  active: TechId | null,
): TechState {
  if (completed.has(tech.id)) return 'researched'
  if (active === tech.id) return 'in_progress'
  const unlocked = tech.requires.every((r) => completed.has(r))
  return unlocked ? 'available' : 'locked'
}

function TechTreePanel({
  techTree,
  research,
  sciencePerTurn,
  queuedResearchTechId,
  onSelectActive,
}: TechTreePanelProps) {
  const completed = useMemo<Set<TechId>>(
    () => new Set(research?.completed ?? []),
    [research?.completed],
  )
  // Queued pick wins over the server's active value: the player's just-
  // clicked selection is the intent; it'll land next turn.
  const effectiveActive =
    queuedResearchTechId === undefined
      ? research?.active ?? null
      : queuedResearchTechId
  const progress = research?.progress ?? 0

  const techs = useMemo(() => {
    if (!techTree) return [] as Tech[]
    return Object.values(techTree).sort(
      (a, b) => a.cost_science - b.cost_science || a.name.localeCompare(b.name),
    )
  }, [techTree])

  const groups = useMemo(() => {
    const g: Record<TechState, Tech[]> = {
      researched: [],
      in_progress: [],
      available: [],
      locked: [],
    }
    for (const tech of techs) {
      g[techState(tech, completed, effectiveActive)].push(tech)
    }
    return g
  }, [techs, completed, effectiveActive])

  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center justify-between">
          <span className="flex items-center gap-1">
            <span aria-hidden="true">🔬</span>
            Tech tree
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            +{sciencePerTurn}/turn
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-3 text-xs">
        {!techTree || !research ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : (
          <>
            {groups.in_progress.length > 0 && (
              <TechGroup
                title="Researching"
                techs={groups.in_progress}
                renderRow={(tech) => {
                  const remaining = Math.max(0, tech.cost_science - progress)
                  const eta =
                    sciencePerTurn > 0
                      ? Math.max(1, Math.ceil(remaining / sciencePerTurn))
                      : null
                  return (
                    <div
                      key={tech.id}
                      className="rounded-md border bg-primary/10 px-2 py-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{tech.name}</span>
                        <span className="text-muted-foreground tabular-nums">
                          {progress}/{tech.cost_science}
                          {eta != null && ` · ${eta}t`}
                        </span>
                      </div>
                      <div className="mt-1 h-1 rounded bg-background">
                        <div
                          className="h-1 rounded bg-primary"
                          style={{
                            width: `${Math.min(
                              100,
                              Math.round(
                                (progress / tech.cost_science) * 100,
                              ),
                            )}%`,
                          }}
                        />
                      </div>
                    </div>
                  )
                }}
              />
            )}

            {groups.available.length > 0 && (
              <TechGroup
                title="Available"
                techs={groups.available}
                renderRow={(tech) => {
                  const eta =
                    sciencePerTurn > 0
                      ? Math.max(1, Math.ceil(tech.cost_science / sciencePerTurn))
                      : null
                  return (
                    <Button
                      key={tech.id}
                      variant="outline"
                      size="sm"
                      className="w-full justify-between text-xs"
                      onClick={() => onSelectActive(tech.id)}
                      title={describeTechUnlocks(tech)}
                    >
                      <span>{tech.name}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {tech.cost_science}🔬
                        {eta != null && ` · ${eta}t`}
                      </span>
                    </Button>
                  )
                }}
              />
            )}

            {groups.locked.length > 0 && (
              <TechGroup
                title="Locked"
                techs={groups.locked}
                renderRow={(tech) => (
                  <div
                    key={tech.id}
                    className="flex items-center justify-between rounded-md border bg-muted/20 px-2 py-1 text-muted-foreground"
                    title={`Requires: ${tech.requires.join(', ')}`}
                  >
                    <span className="flex items-center gap-1">
                      <Lock className="h-3 w-3" />
                      {tech.name}
                    </span>
                    <span className="tabular-nums">
                      {tech.cost_science}🔬
                    </span>
                  </div>
                )}
              />
            )}

            {groups.researched.length > 0 && (
              <TechGroup
                title="Researched"
                techs={groups.researched}
                renderRow={(tech) => (
                  <div
                    key={tech.id}
                    className="flex items-center justify-between rounded-md border bg-muted/40 px-2 py-1"
                    title={describeTechUnlocks(tech)}
                  >
                    <span className="flex items-center gap-1">
                      <Check className="h-3 w-3" />
                      {tech.name}
                    </span>
                  </div>
                )}
              />
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function describeTechUnlocks(tech: Tech): string {
  const parts: string[] = []
  if (tech.unlocks_units.length > 0) {
    parts.push(`Units: ${tech.unlocks_units.join(', ')}`)
  }
  if (tech.unlocks_buildings.length > 0) {
    parts.push(`Buildings: ${tech.unlocks_buildings.join(', ')}`)
  }
  return parts.length > 0 ? parts.join('\n') : 'No direct unlocks'
}

function TechGroup({
  title,
  techs,
  renderRow,
}: {
  title: string
  techs: Tech[]
  renderRow: (tech: Tech) => React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <div className="text-muted-foreground font-medium">{title}</div>
      {techs.map(renderRow)}
    </div>
  )
}

interface DiplomacyPanelProps {
  currentPlayer: PlayerId
  diplomacy: DiplomacyStateResponse | null
  selectedOpponent: PlayerId | null
  onSelectOpponent: (opponent: PlayerId | null) => void
  lastSeenMessageIds: Record<PlayerId, number>
  queuedActions: GameAction[]
  onQueueMessage: (recipient: PlayerId, body: string) => void
  onQueueProposeTreaty: (recipient: PlayerId, clauses: TreatyClause[]) => void
  onQueueRespondToTreaty: (proposalId: number, accept: boolean) => void
  onQueueWithdrawTreaty: (proposalId: number) => void
  onQueueCancelTreaty: (treatyId: number) => void
  onQueueDeclareWar: (target: PlayerId) => void
}

interface DiplomacyThreadViewProps {
  currentPlayer: PlayerId
  diplomacy: DiplomacyStateResponse
  opponent: PlayerId
  queuedActions: GameAction[]
  onSelectOpponent: (opponent: PlayerId | null) => void
  onQueueMessage: (recipient: PlayerId, body: string) => void
  onQueueProposeTreaty: (recipient: PlayerId, clauses: TreatyClause[]) => void
  onQueueRespondToTreaty: (proposalId: number, accept: boolean) => void
  onQueueWithdrawTreaty: (proposalId: number) => void
  onQueueCancelTreaty: (treatyId: number) => void
  onQueueDeclareWar: (target: PlayerId) => void
}

function describeClause(clause: TreatyClause): string {
  switch (clause.clause_type) {
    case 'peace':
      return `peace · ${clause.duration_turns ?? '?'}t`
    case 'free_text':
      return `free text · "${(clause.text ?? '').slice(0, 30)}${(clause.text ?? '').length > 30 ? '…' : ''}"`
    case 'resource_swap':
      return `swap · ${formatCost(clause.proposer_gives ?? ({} as ResourceBag))} ↔ ${formatCost(clause.recipient_gives ?? ({} as ResourceBag))}`
    case 'recurring_tribute':
      return `tribute · ${clause.payer} pays ${formatCost(clause.amount ?? ({} as ResourceBag))}/turn × ${clause.duration_turns ?? '?'}`
  }
}

function DiplomacyThreadView({
  currentPlayer,
  diplomacy,
  opponent,
  queuedActions,
  onSelectOpponent,
  onQueueMessage,
  onQueueProposeTreaty,
  onQueueRespondToTreaty,
  onQueueWithdrawTreaty,
  onQueueCancelTreaty,
  onQueueDeclareWar,
}: DiplomacyThreadViewProps) {
  const [confirmingWar, setConfirmingWar] = useState(false)
  const [draft, setDraft] = useState('')
  const thread: DiplomacyMessage[] = diplomacy.messages
    .filter(
      (m) =>
        (m.sender === currentPlayer && m.recipient === opponent) ||
        (m.sender === opponent && m.recipient === currentPlayer),
    )
    .sort((a, b) => a.id - b.id)
  const queuedOutboundMessages = queuedActions.filter(
    (a): a is Extract<GameAction, { type: 'SEND_MESSAGE' }> =>
      a.type === 'SEND_MESSAGE' && a.recipient === opponent,
  )
  const relation = findRelation(diplomacy.relations, currentPlayer, opponent)
  const rel = relationLabel(relation)
  const overLimit = draft.length > MESSAGE_BODY_MAX_LENGTH
  const canSend = draft.trim().length > 0 && !overLimit

  const bilateralProposals = diplomacy.pending_proposals.filter(
    (p) =>
      (p.proposer === currentPlayer && p.recipient === opponent) ||
      (p.proposer === opponent && p.recipient === currentPlayer),
  )
  const inbound = bilateralProposals.filter((p) => p.recipient === currentPlayer)
  const outbound = bilateralProposals.filter((p) => p.proposer === currentPlayer)
  const activeTreaties = treatiesFor(
    diplomacy.active_treaties,
    currentPlayer,
    opponent,
  )

  // Has the player already queued a terminal action against a specific
  // proposal/treaty id? Used to disable duplicate queue entries.
  const queuedProposalResponses = new Set(
    queuedActions
      .filter(
        (a): a is Extract<GameAction, { type: 'RESPOND_TO_TREATY' }> =>
          a.type === 'RESPOND_TO_TREATY',
      )
      .map((a) => a.proposal_id),
  )
  const queuedProposalWithdrawals = new Set(
    queuedActions
      .filter(
        (a): a is Extract<GameAction, { type: 'WITHDRAW_TREATY' }> =>
          a.type === 'WITHDRAW_TREATY',
      )
      .map((a) => a.proposal_id),
  )
  const queuedTreatyCancellations = new Set(
    queuedActions
      .filter(
        (a): a is Extract<GameAction, { type: 'CANCEL_TREATY' }> =>
          a.type === 'CANCEL_TREATY',
      )
      .map((a) => a.treaty_id),
  )
  const queuedProposalsForOpponent = queuedActions.filter(
    (a): a is Extract<GameAction, { type: 'PROPOSE_TREATY' }> =>
      a.type === 'PROPOSE_TREATY' && a.recipient === opponent,
  )

  // Phase 9: a queued DECLARE_WAR against this opponent disables the
  // button so the user can't double-queue the same declaration.
  const warAlreadyQueued = queuedActions.some(
    (a) => a.type === 'DECLARE_WAR' && a.target_player === opponent,
  )
  const canDeclareWar = relation === 'peace' && !warAlreadyQueued
  const affectedTreatyCount = activeTreaties.length

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
          {thread.length === 0 && queuedOutboundMessages.length === 0 ? (
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
              {queuedOutboundMessages.map((q, idx) => (
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

        {/* Phase 8: treaty lifecycle --------------------------------- */}
        {inbound.length > 0 && (
          <div
            className="space-y-1 rounded border bg-muted/20 p-2"
            data-testid="diplomacy-inbound-proposals"
          >
            <p className="text-[10px] font-medium uppercase text-muted-foreground">
              Inbound proposals
            </p>
            {inbound.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                variant="inbound"
                disabled={queuedProposalResponses.has(p.id)}
                onAccept={() => onQueueRespondToTreaty(p.id, true)}
                onReject={() => onQueueRespondToTreaty(p.id, false)}
              />
            ))}
          </div>
        )}

        {outbound.length > 0 && (
          <div
            className="space-y-1 rounded border bg-muted/20 p-2"
            data-testid="diplomacy-outbound-proposals"
          >
            <p className="text-[10px] font-medium uppercase text-muted-foreground">
              Outbound proposals
            </p>
            {outbound.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                variant="outbound"
                disabled={queuedProposalWithdrawals.has(p.id)}
                onWithdraw={() => onQueueWithdrawTreaty(p.id)}
              />
            ))}
          </div>
        )}

        {activeTreaties.length > 0 && (
          <div
            className="space-y-1 rounded border bg-muted/20 p-2"
            data-testid="diplomacy-active-treaties"
          >
            <p className="text-[10px] font-medium uppercase text-muted-foreground">
              Active treaties
            </p>
            {activeTreaties.map((t) => (
              <div
                key={t.id}
                className="flex items-start justify-between gap-2 text-xs"
                data-testid={`diplomacy-treaty-${t.id}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    Treaty #{t.id}
                    <span className="ml-1 text-muted-foreground">
                      · ratified t{t.turn_ratified}
                    </span>
                  </p>
                  <ul className="list-disc pl-4 text-[11px] text-muted-foreground">
                    {t.clauses.map((c, i) => (
                      <li key={i}>{describeClause(c)}</li>
                    ))}
                  </ul>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={queuedTreatyCancellations.has(t.id)}
                  onClick={() => onQueueCancelTreaty(t.id)}
                  data-testid={`diplomacy-cancel-treaty-${t.id}`}
                  className="shrink-0 text-xs"
                >
                  <X className="h-3.5 w-3.5 mr-1" />
                  {queuedTreatyCancellations.has(t.id) ? 'Queued' : 'Cancel'}
                </Button>
              </div>
            ))}
          </div>
        )}

        <ProposeTreatyForm
          currentPlayer={currentPlayer}
          opponent={opponent}
          queuedProposalsCount={queuedProposalsForOpponent.length}
          onQueueProposeTreaty={onQueueProposeTreaty}
        />

        {/* Phase 9: Declare War affordance. Only visible while the
            relation is peace; the two-step confirm spells out the
            consequences (treaties cancelled, relation flips to war)
            before anything lands on the queue. */}
        {relation === 'peace' && (
          <div
            className="rounded border border-destructive/40 bg-destructive/5 p-2"
            data-testid="diplomacy-declare-war-root"
          >
            {!confirmingWar ? (
              <Button
                size="sm"
                variant="destructive"
                className="w-full text-xs"
                disabled={!canDeclareWar}
                onClick={() => setConfirmingWar(true)}
                data-testid="diplomacy-declare-war-open"
              >
                <Swords className="h-3.5 w-3.5 mr-1" />
                {warAlreadyQueued ? 'War queued' : 'Declare war'}
              </Button>
            ) : (
              <div className="space-y-2 text-xs">
                <p className="font-medium text-destructive">
                  Declare war on {opponent}?
                </p>
                <p className="text-[11px] text-muted-foreground">
                  Relation flips to war on End Turn.
                  {affectedTreatyCount > 0 &&
                    ` ${affectedTreatyCount} active treat${
                      affectedTreatyCount === 1 ? 'y' : 'ies'
                    } will be cancelled.`}
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    className="flex-1 text-xs"
                    onClick={() => {
                      onQueueDeclareWar(opponent)
                      setConfirmingWar(false)
                    }}
                    data-testid="diplomacy-declare-war-confirm"
                  >
                    <Swords className="h-3.5 w-3.5 mr-1" />
                    Confirm
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    onClick={() => setConfirmingWar(false)}
                    data-testid="diplomacy-declare-war-cancel"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface ProposalCardProps {
  proposal: TreatyProposalRecord
  variant: 'inbound' | 'outbound'
  disabled: boolean
  onAccept?: () => void
  onReject?: () => void
  onWithdraw?: () => void
}

function ProposalCard({
  proposal,
  variant,
  disabled,
  onAccept,
  onReject,
  onWithdraw,
}: ProposalCardProps) {
  return (
    <div
      className="flex items-start justify-between gap-2 text-xs"
      data-testid={`diplomacy-proposal-${proposal.id}`}
    >
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          Proposal #{proposal.id}
          <span className="ml-1 text-muted-foreground">
            · expires t{proposal.expires_on_turn}
          </span>
        </p>
        <ul className="list-disc pl-4 text-[11px] text-muted-foreground">
          {proposal.clauses.map((c, i) => (
            <li key={i}>{describeClause(c)}</li>
          ))}
        </ul>
      </div>
      <div className="flex shrink-0 flex-col gap-1">
        {variant === 'inbound' ? (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={onAccept}
              data-testid={`diplomacy-accept-${proposal.id}`}
              className="text-xs"
            >
              <Check className="h-3.5 w-3.5 mr-1" />
              {disabled ? 'Queued' : 'Accept'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={onReject}
              data-testid={`diplomacy-reject-${proposal.id}`}
              className="text-xs"
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Reject
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={onWithdraw}
            data-testid={`diplomacy-withdraw-${proposal.id}`}
            className="text-xs"
          >
            <X className="h-3.5 w-3.5 mr-1" />
            {disabled ? 'Queued' : 'Withdraw'}
          </Button>
        )}
      </div>
    </div>
  )
}

type ClauseKind = TreatyClause['clause_type']

interface ProposeTreatyFormProps {
  currentPlayer: PlayerId
  opponent: PlayerId
  queuedProposalsCount: number
  onQueueProposeTreaty: (recipient: PlayerId, clauses: TreatyClause[]) => void
}

function ProposeTreatyForm({
  currentPlayer,
  opponent,
  queuedProposalsCount,
  onQueueProposeTreaty,
}: ProposeTreatyFormProps) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<ClauseKind>('peace')

  // One state bag shared across kinds — only the subset relevant to the
  // currently-selected kind is read when building the clause, so mixing
  // is harmless and keeping it in one place avoids four sets of handlers.
  const [duration, setDuration] = useState<number>(10)
  const [freeText, setFreeText] = useState<string>('')
  const [proposerFood, setProposerFood] = useState<number>(0)
  const [proposerWood, setProposerWood] = useState<number>(0)
  const [proposerOre, setProposerOre] = useState<number>(0)
  const [proposerCrystal, setProposerCrystal] = useState<number>(0)
  const [recipientFood, setRecipientFood] = useState<number>(0)
  const [recipientWood, setRecipientWood] = useState<number>(0)
  const [recipientOre, setRecipientOre] = useState<number>(0)
  const [recipientCrystal, setRecipientCrystal] = useState<number>(0)
  const [tributePayer, setTributePayer] = useState<PlayerId>(currentPlayer)

  const clampedDuration = Math.min(
    Math.max(1, Math.floor(duration || 0)),
    PEACE_CLAUSE_MAX_DURATION,
  )

  const buildClause = (): TreatyClause | null => {
    switch (kind) {
      case 'peace':
        return {
          clause_type: 'peace',
          duration_turns: clampedDuration,
          turns_remaining: clampedDuration,
        }
      case 'free_text': {
        const text = freeText.trim()
        if (!text) return null
        if (text.length > FREE_TEXT_CLAUSE_MAX_LENGTH) return null
        return { clause_type: 'free_text', text }
      }
      case 'resource_swap':
        return {
          clause_type: 'resource_swap',
          proposer_gives: {
            food: Math.max(0, Math.floor(proposerFood)),
            wood: Math.max(0, Math.floor(proposerWood)),
            ore: Math.max(0, Math.floor(proposerOre)),
            crystal: Math.max(0, Math.floor(proposerCrystal)),
            science: 0,
          },
          recipient_gives: {
            food: Math.max(0, Math.floor(recipientFood)),
            wood: Math.max(0, Math.floor(recipientWood)),
            ore: Math.max(0, Math.floor(recipientOre)),
            crystal: Math.max(0, Math.floor(recipientCrystal)),
            science: 0,
          },
        }
      case 'recurring_tribute':
        return {
          clause_type: 'recurring_tribute',
          payer: tributePayer,
          amount: {
            food: Math.max(0, Math.floor(proposerFood)),
            wood: Math.max(0, Math.floor(proposerWood)),
            ore: Math.max(0, Math.floor(proposerOre)),
            crystal: Math.max(0, Math.floor(proposerCrystal)),
            science: 0,
          },
          duration_turns: clampedDuration,
          turns_remaining: clampedDuration,
        }
    }
  }

  const clause = buildClause()
  const canQueue = clause !== null

  return (
    <div className="rounded border bg-muted/20 p-2" data-testid="diplomacy-propose-root">
      <button
        className="flex w-full items-center justify-between text-xs font-medium"
        onClick={() => setOpen((v) => !v)}
        data-testid="diplomacy-propose-toggle"
      >
        <span className="flex items-center gap-1">
          <FileSignature className="h-3.5 w-3.5" />
          Propose treaty
          {queuedProposalsCount > 0 && (
            <span className="ml-1 text-muted-foreground">
              · {queuedProposalsCount} queued
            </span>
          )}
        </span>
        <span className="text-muted-foreground">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap gap-1">
            {(
              [
                'peace',
                'free_text',
                'resource_swap',
                'recurring_tribute',
              ] as ClauseKind[]
            ).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={`rounded border px-2 py-0.5 text-[11px] ${
                  kind === k ? 'bg-primary/10' : ''
                }`}
                data-testid={`diplomacy-propose-kind-${k}`}
              >
                {k.replace(/_/g, ' ')}
              </button>
            ))}
          </div>

          {kind === 'peace' && (
            <label className="flex items-center gap-2 text-[11px]">
              Duration (turns)
              <input
                type="number"
                min={1}
                max={PEACE_CLAUSE_MAX_DURATION}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-20 rounded border bg-background px-1 py-0.5"
                data-testid="diplomacy-propose-duration"
              />
            </label>
          )}

          {kind === 'free_text' && (
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              maxLength={FREE_TEXT_CLAUSE_MAX_LENGTH + 1}
              className="min-h-14 w-full resize-none rounded border bg-background px-2 py-1 text-[11px]"
              placeholder={`Clause text (max ${FREE_TEXT_CLAUSE_MAX_LENGTH} chars)`}
              data-testid="diplomacy-propose-free-text"
            />
          )}

          {kind === 'resource_swap' && (
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <fieldset className="space-y-1 rounded border p-1">
                <legend className="px-1">you give</legend>
                <ResourceInputs
                  food={proposerFood}
                  wood={proposerWood}
                  ore={proposerOre}
                  crystal={proposerCrystal}
                  onChange={{
                    food: setProposerFood,
                    wood: setProposerWood,
                    ore: setProposerOre,
                    crystal: setProposerCrystal,
                  }}
                  testPrefix="diplomacy-propose-swap-give"
                />
              </fieldset>
              <fieldset className="space-y-1 rounded border p-1">
                <legend className="px-1">{opponent} gives</legend>
                <ResourceInputs
                  food={recipientFood}
                  wood={recipientWood}
                  ore={recipientOre}
                  crystal={recipientCrystal}
                  onChange={{
                    food: setRecipientFood,
                    wood: setRecipientWood,
                    ore: setRecipientOre,
                    crystal: setRecipientCrystal,
                  }}
                  testPrefix="diplomacy-propose-swap-receive"
                />
              </fieldset>
            </div>
          )}

          {kind === 'recurring_tribute' && (
            <div className="space-y-2 text-[11px]">
              <label className="flex items-center gap-2">
                Payer
                <select
                  value={tributePayer}
                  onChange={(e) => setTributePayer(e.target.value)}
                  className="rounded border bg-background px-1 py-0.5"
                  data-testid="diplomacy-propose-tribute-payer"
                >
                  <option value={currentPlayer}>{currentPlayer} (you)</option>
                  <option value={opponent}>{opponent}</option>
                </select>
              </label>
              <fieldset className="space-y-1 rounded border p-1">
                <legend className="px-1">per-turn amount</legend>
                <ResourceInputs
                  food={proposerFood}
                  wood={proposerWood}
                  ore={proposerOre}
                  crystal={proposerCrystal}
                  onChange={{
                    food: setProposerFood,
                    wood: setProposerWood,
                    ore: setProposerOre,
                    crystal: setProposerCrystal,
                  }}
                  testPrefix="diplomacy-propose-tribute-amount"
                />
              </fieldset>
              <label className="flex items-center gap-2">
                Duration (turns)
                <input
                  type="number"
                  min={1}
                  max={PEACE_CLAUSE_MAX_DURATION}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                  className="w-20 rounded border bg-background px-1 py-0.5"
                  data-testid="diplomacy-propose-duration"
                />
              </label>
            </div>
          )}

          <Button
            size="sm"
            variant="outline"
            disabled={!canQueue}
            onClick={() => {
              if (!clause) return
              onQueueProposeTreaty(opponent, [clause])
            }}
            data-testid="diplomacy-propose-submit"
            className="w-full text-xs"
          >
            <Send className="h-3.5 w-3.5 mr-1" />
            Queue proposal
          </Button>
        </div>
      )}
    </div>
  )
}

interface ResourceInputsProps {
  food: number
  wood: number
  ore: number
  crystal: number
  onChange: {
    food: (n: number) => void
    wood: (n: number) => void
    ore: (n: number) => void
    crystal: (n: number) => void
  }
  testPrefix: string
}

function ResourceInputs({
  food,
  wood,
  ore,
  crystal,
  onChange,
  testPrefix,
}: ResourceInputsProps) {
  const rows: Array<{
    key: keyof ResourceBag
    value: number
    setter: (n: number) => void
  }> = [
    { key: 'food', value: food, setter: onChange.food },
    { key: 'wood', value: wood, setter: onChange.wood },
    { key: 'ore', value: ore, setter: onChange.ore },
    { key: 'crystal', value: crystal, setter: onChange.crystal },
  ]
  return (
    <div className="grid grid-cols-2 gap-1">
      {rows.map(({ key, value, setter }) => (
        <label key={key} className="flex items-center gap-1 text-[11px]">
          <span className="capitalize">{key}</span>
          <input
            type="number"
            min={0}
            value={value}
            onChange={(e) => setter(Number(e.target.value))}
            className="w-full rounded border bg-background px-1 py-0.5"
            data-testid={`${testPrefix}-${key}`}
          />
        </label>
      ))}
    </div>
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
  queuedActions,
  onQueueMessage,
  onQueueProposeTreaty,
  onQueueRespondToTreaty,
  onQueueWithdrawTreaty,
  onQueueCancelTreaty,
  onQueueDeclareWar,
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
        queuedActions={queuedActions}
        onSelectOpponent={onSelectOpponent}
        onQueueMessage={onQueueMessage}
        onQueueProposeTreaty={onQueueProposeTreaty}
        onQueueRespondToTreaty={onQueueRespondToTreaty}
        onQueueWithdrawTreaty={onQueueWithdrawTreaty}
        onQueueCancelTreaty={onQueueCancelTreaty}
        onQueueDeclareWar={onQueueDeclareWar}
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
