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
  Flag,
  Landmark,
  Loader2,
  Lock,
  RefreshCw,
  Send,
  Sparkles,
  Swords,
  Trash2,
  X,
} from 'lucide-react'
import { api, ApiError, queryKeys } from '@/lib/api'
import { PixiMap } from '@/components/pixi-map'
import { MiniMap } from '@/components/mini-map'
import { RulesReferencePanel } from '@/components/rules-reference-panel'
import { Identity } from '@/components/brand/identity'
import { PLAYER_COLORS } from '@/types/game'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { StatPair } from '@/components/ui/stat'
import { Tag } from '@/components/ui/tag'
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
  ViewportRect,
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
    case 'RESIGN':
      return 'Resign'
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
    <div className="flex items-center gap-3.5 text-[13px]">
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
            className="inline-flex items-center gap-1.5"
          >
            <span aria-hidden="true" className="text-base leading-none">{emoji}</span>
            <span
              className="font-display text-ink tabular-nums leading-none"
              style={{ fontSize: 17, letterSpacing: '-0.01em' }}
            >
              {amount}
            </span>
            {delta > 0 && (
              <span
                className="font-mono text-success tabular-nums"
                style={{ fontSize: 11 }}
              >
                +{delta}
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

  // Total unread inbound messages across all opponents — surfaces a
  // badge on the Diplomacy tab so the user notices new traffic without
  // opening the panel.
  const totalUnreadMessages = useMemo(() => {
    if (!diplomacyState) return 0
    return diplomacyState.messages.filter(
      (m) =>
        m.recipient === currentPlayer &&
        m.id > (lastSeenMessageIds[m.sender] ?? 0),
    ).length
  }, [diplomacyState, lastSeenMessageIds, currentPlayer])

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

  // Phase 7: idle unit & city cycling. "Idle" is defined by the PRD as
  // owner == currentPlayer, moves_left > 0, no queued orders, no
  // automation (units), and empty build queue (cities). We also treat
  // any pending local action targeting the entity as "addressed" — the
  // user has given it something to do this turn even if End Turn hasn't
  // fired yet — so the counters tick down as the player works.
  const busyUnitIds = useMemo(() => {
    const set = new Set<number>()
    for (const { action } of queue) {
      switch (action.type) {
        case 'MOVE':
          set.add(action.unit_id)
          break
        case 'ATTACK':
          set.add(action.attacker_id)
          break
        case 'FOUND_CITY':
        case 'BUILD_IMPROVEMENT':
          set.add(action.worker_id)
          break
        case 'QUEUE_ORDER':
        case 'CANCEL_ORDER':
        case 'SET_AUTOMATION':
        case 'CLEAR_AUTOMATION':
          set.add(action.unit_id)
          break
      }
    }
    return set
  }, [queue])

  const busyCityIds = useMemo(() => {
    const set = new Set<number>()
    for (const { action } of queue) {
      switch (action.type) {
        case 'TRAIN_UNIT':
        case 'BUILD_BUILDING':
        case 'SET_CITY_PRODUCTION':
        case 'CANCEL_CITY_PRODUCTION':
        case 'REORDER_CITY_QUEUE':
          set.add(action.city_id)
          break
      }
    }
    return set
  }, [queue])

  const idleUnitIds = useMemo<number[]>(() => {
    if (!gameState) return []
    const out: number[] = []
    for (const unit of Object.values(gameState.units)) {
      if (unit.owner !== currentPlayer) continue
      if (unit.moves_left <= 0) continue
      if ((unit.orders_queue?.length ?? 0) > 0) continue
      if (unit.automation != null) continue
      if (busyUnitIds.has(unit.id)) continue
      out.push(unit.id)
    }
    out.sort((a, b) => a - b)
    return out
  }, [gameState, currentPlayer, busyUnitIds])

  const idleCityIds = useMemo<number[]>(() => {
    if (!gameState) return []
    const out: number[] = []
    for (const city of Object.values(gameState.cities)) {
      if (city.owner !== currentPlayer) continue
      if ((city.build_queue?.length ?? 0) > 0) continue
      if (busyCityIds.has(city.id)) continue
      out.push(city.id)
    }
    out.sort((a, b) => a - b)
    return out
  }, [gameState, currentPlayer, busyCityIds])

  // Wrapped in a fresh object each cycle so PixiMap's focusTile effect
  // retriggers even when the player cycles back to the same tile.
  const [focusTile, setFocusTile] = useState<Coord | null>(null)

  // Phase 4 prototype-rollout: docked mini-map state. PixiMap reports its
  // current viewport rect on every pan/zoom; the MiniMap overlays a
  // rectangle for that area. Click-to-pan dispatches a fresh ``panToTile``
  // wrapper so the same tile can be re-clicked.
  const [viewportRect, setViewportRect] = useState<ViewportRect | null>(null)
  const [panToTile, setPanToTile] = useState<Coord | null>(null)

  const cycleIdleUnit = useCallback(() => {
    if (!gameState || idleUnitIds.length === 0) return
    const currentIdx = idleUnitIds.indexOf(selectedUnitId ?? -1)
    const nextIdx = (currentIdx + 1) % idleUnitIds.length
    const nextId = idleUnitIds[nextIdx]
    const unit = gameState.units[nextId]
    if (!unit) return
    setSelectedCityId(null)
    setSelectedUnitId(nextId)
    setStackSelector(null)
    setFocusTile({ x: unit.loc.x, y: unit.loc.y })
  }, [gameState, idleUnitIds, selectedUnitId])

  const cycleIdleCity = useCallback(() => {
    if (!gameState || idleCityIds.length === 0) return
    const currentIdx = idleCityIds.indexOf(selectedCityId ?? -1)
    const nextIdx = (currentIdx + 1) % idleCityIds.length
    const nextId = idleCityIds[nextIdx]
    const city = gameState.cities[nextId]
    if (!city) return
    setSelectedUnitId(null)
    setSelectedCityId(nextId)
    setStackSelector(null)
    setFocusTile({ x: city.loc.x, y: city.loc.y })
  }, [gameState, idleCityIds, selectedCityId])

  // N cycles idle units, B cycles idle cities. Suppressed when focus is
  // inside a form control so typing in the diplomacy composer isn't
  // hijacked, and while any modifier key is held so browser shortcuts
  // like ⌘N keep working.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (key !== 'n' && key !== 'b') return
      const target = e.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
        if (target.isContentEditable) return
      }
      e.preventDefault()
      if (key === 'n') cycleIdleUnit()
      else cycleIdleCity()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [cycleIdleUnit, cycleIdleCity])

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

  // Phase 3 (spectated-agents): resignation. Applied immediately by the
  // backend — this mutation does not queue onto the turn submission
  // buffer. In a 2-player game the remaining seat wins on return; in a
  // 3+ game the resigner is eliminated and play continues for the
  // others. Only visible to seated players.
  const [confirmingResign, setConfirmingResign] = useState(false)
  const resignMutation = useMutation({
    mutationFn: async () => api.resignGame(gameId),
    onSuccess: () => {
      setConfirmingResign(false)
      toast({
        title: 'Resigned',
        description: 'You have conceded the game.',
      })
      queryClient.invalidateQueries({ queryKey: stateQueryKey })
      queryClient.invalidateQueries({
        queryKey: queryKeys.gameDetail(gameId),
      })
    },
    onError: (err) => {
      const message =
        err instanceof ApiError ? err.message : (err as Error).message
      toast({
        title: 'Resignation failed',
        description: message,
        variant: 'destructive',
      })
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
    <div className="flex flex-col h-full bg-bg text-ink font-ui">
      {/* Status bar */}
      <div className="border-b border-border bg-bg-subtle px-5 py-2.5 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2.5 text-sm">
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2 py-0.5 font-mono text-accent"
            style={{ fontSize: 11, letterSpacing: "0.02em" }}
          >
            your turn
          </span>
          <span
            className="font-mono text-ink-muted"
            style={{ fontSize: 12 }}
          >
            playing as {currentPlayer} · turn {gameState.turn} / {gameState.max_turns}
          </span>
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
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono"
                style={{
                  background: "oklch(from var(--warning) l c h / 0.14)",
                  color: "oklch(from var(--warning) calc(l - 0.10) c h)",
                  boxShadow: "inset 0 0 0 1px oklch(from var(--warning) l c h / 0.30)",
                  fontSize: 11,
                  letterSpacing: "0.02em",
                }}
              >
                <Loader2 className="h-3 w-3 animate-spin" />
                waiting for {outstanding.length} player
                {outstanding.length === 1 ? '' : 's'}
              </span>
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
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs"
              data-testid="idle-unit-button"
              aria-label="Cycle to next idle unit (N)"
              title="Cycle to next idle unit (N)"
              onClick={cycleIdleUnit}
              disabled={idleUnitIds.length === 0}
            >
              <span>Idle units</span>
              <Badge
                variant={idleUnitIds.length === 0 ? 'secondary' : 'default'}
                className="h-4 px-1.5 text-[10px]"
                data-testid="idle-unit-count"
              >
                {idleUnitIds.length}
              </Badge>
              <span className="text-[10px] text-muted-foreground">N</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs"
              data-testid="idle-city-button"
              aria-label="Cycle to next idle city (B)"
              title="Cycle to next idle city (B)"
              onClick={cycleIdleCity}
              disabled={idleCityIds.length === 0}
            >
              <span>Idle cities</span>
              <Badge
                variant={idleCityIds.length === 0 ? 'secondary' : 'default'}
                className="h-4 px-1.5 text-[10px]"
                data-testid="idle-city-count"
              >
                {idleCityIds.length}
              </Badge>
              <span className="text-[10px] text-muted-foreground">B</span>
            </Button>
          </div>
          <span
            className="font-mono text-ink-muted"
            style={{ fontSize: 11 }}
          >
            {Object.keys(gameState.units).length} units · {Object.keys(gameState.cities).length} cities
          </span>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left rail — docked mini-map. */}
        <aside className="hidden xl:flex w-[220px] shrink-0 flex-col gap-3 border-r border-border bg-bg-subtle p-3">
          <Panel
            title="Mini-map"
            kicker="overview"
            padded={false}
            className="overflow-visible"
          >
            <div className="p-2">
              <MiniMap
                gameState={gameState}
                viewport={viewportRect}
                onPanRequest={(coord) => setPanToTile({ ...coord })}
                width={196}
              />
            </div>
          </Panel>
        </aside>

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
            focusTile={focusTile}
            onViewportRectChange={setViewportRect}
            panToTile={panToTile}
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
        <div className="w-96 border-l border-border bg-bg-subtle flex flex-col h-full min-h-0">
          {/* Selection — always pinned at the top so the contextual
              affordances (Found City, Auto-improve, Train, Build, …) are
              never pushed below the fold by Diplomacy / Research / Rules.
              Caps at 55vh so a fat city queue can't eat the tabs. */}
          <div className="shrink-0 max-h-[55vh] overflow-y-auto flex flex-col">
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
          </div>

          {/* Tabbed sidebar — Orders is default so the queue and
              submission roster are visible on first paint. forceMount
              keeps every TabsContent in the DOM so React Query state
              and message drafts survive tab switches and existing
              testids stay reachable. */}
          <Tabs
            defaultValue="orders"
            className="flex-1 min-h-0 flex flex-col"
          >
            <TabsList className="h-9 shrink-0 grid grid-cols-4 rounded-none border-b border-border bg-bg-subtle p-0 gap-0">
              <TabsTrigger
                value="orders"
                className="rounded-none border-r border-border h-full text-xs data-[state=active]:bg-surface data-[state=active]:shadow-none"
                data-testid="sidebar-tab-orders"
              >
                Orders
                {queue.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="ml-1.5 h-4 px-1.5 text-[10px] leading-none"
                  >
                    {queue.length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger
                value="diplomacy"
                className="rounded-none border-r border-border h-full text-xs data-[state=active]:bg-surface data-[state=active]:shadow-none"
                data-testid="sidebar-tab-diplomacy"
              >
                Diplomacy
                {totalUnreadMessages > 0 && (
                  <Badge
                    variant="destructive"
                    className="ml-1.5 h-4 px-1.5 text-[10px] leading-none"
                    data-testid="sidebar-tab-diplomacy-unread"
                  >
                    {totalUnreadMessages}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger
                value="research"
                className="rounded-none border-r border-border h-full text-xs data-[state=active]:bg-surface data-[state=active]:shadow-none"
                data-testid="sidebar-tab-research"
              >
                Research
              </TabsTrigger>
              <TabsTrigger
                value="rules"
                className="rounded-none h-full text-xs data-[state=active]:bg-surface data-[state=active]:shadow-none"
                data-testid="sidebar-tab-rules"
              >
                Rules
              </TabsTrigger>
            </TabsList>

            <TabsContent
              value="orders"
              forceMount
              className="mt-0 flex-1 min-h-0 overflow-y-auto flex flex-col data-[state=inactive]:hidden"
            >
              {/* Submission roster (Phase 6) */}
              <SubmissionRoster
                players={gameState.players}
                currentPlayer={currentPlayer}
                submittedPlayers={submittedPlayers}
              />

              {/* Queue panel */}
              <Panel
                title={`Queued orders (${queue.length})`}
                className="rounded-none border-x-0 border-t-0 flex-1"
              >
                {queue.length === 0 ? (
                  <p className="text-xs text-ink-muted">
                    No orders queued. Select a unit or city to see what you
                    can do this turn.
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {queue.map((q) => (
                      <div
                        key={q.queue_id}
                        className="flex items-center justify-between rounded-md border border-border bg-bg-subtle px-2 py-1.5"
                        style={{ fontSize: 12 }}
                      >
                        <div className="flex flex-col">
                          <span className="text-ink">
                            {describeAction(q.action)}
                          </span>
                          {q.error && (
                            <span className="text-destructive" style={{ fontSize: 11 }}>
                              {q.error}
                            </span>
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
                    ))}
                  </div>
                )}
              </Panel>
            </TabsContent>

            <TabsContent
              value="diplomacy"
              forceMount
              className="mt-0 flex-1 min-h-0 overflow-y-auto flex flex-col data-[state=inactive]:hidden"
            >
              <DiplomacyPanel
                currentPlayer={currentPlayer}
                players={gameState.players}
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
            </TabsContent>

            <TabsContent
              value="research"
              forceMount
              className="mt-0 flex-1 min-h-0 overflow-y-auto flex flex-col data-[state=inactive]:hidden"
            >
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
            </TabsContent>

            <TabsContent
              value="rules"
              forceMount
              className="mt-0 flex-1 min-h-0 overflow-y-auto flex flex-col data-[state=inactive]:hidden"
            >
              <RulesReferencePanel />
            </TabsContent>
          </Tabs>

          <div className="p-3 border-t border-border bg-bg-subtle shrink-0 space-y-2">
            {/* End Turn — the only `accent`-coloured affordance in the
                gameplay sidebar. Action buttons in UnitPanel / CityPanel
                are flat (variant="outline") so the eye lands here. */}
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
            {/* Phase 3 (spectated-agents): Resign affordance. Only seated
                players see this block — GameplayView is already gated on
                ``currentPlayer`` resolving to the viewer's own seat, so
                spectators never reach this branch. Two-step confirm
                mirrors the Declare War pattern so an errant click can't
                silently concede the game. */}
            {!confirmingResign ? (
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs text-destructive hover:bg-destructive/10"
                disabled={resignMutation.isPending}
                onClick={() => setConfirmingResign(true)}
                data-testid="resign-open"
              >
                <Flag className="h-3.5 w-3.5 mr-1" />
                Resign
              </Button>
            ) : (
              <div
                className="space-y-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs"
                data-testid="resign-confirm-root"
              >
                <p className="font-medium text-destructive">
                  Resign from this game?
                </p>
                <p className="text-[11px] text-ink-muted">
                  Your cities and units will be destroyed. In a 2-player
                  game the other player wins immediately.
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    className="flex-1 text-xs"
                    disabled={resignMutation.isPending}
                    onClick={() => resignMutation.mutate()}
                    data-testid="resign-confirm"
                  >
                    <Flag className="h-3.5 w-3.5 mr-1" />
                    {resignMutation.isPending ? 'Resigning…' : 'Confirm'}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    disabled={resignMutation.isPending}
                    onClick={() => setConfirmingResign(false)}
                    data-testid="resign-cancel"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
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
  if (!unit) {
    return (
      <Panel title="Selection" className="rounded-none border-x-0 border-t-0">
        <p className="text-xs text-ink-muted">
          Click one of your units or cities to see what you can do.
        </p>
      </Panel>
    )
  }
  return (
    <Panel
      title="Selection"
      kicker={`unit · #${unit.id}`}
      className="rounded-none border-x-0 border-t-0"
    >
      <div className="space-y-3">
        <div>
          <div
            className="font-display text-ink capitalize leading-tight"
            style={{ fontSize: 22, letterSpacing: '-0.01em' }}
          >
            {unit.type}
          </div>
          <div
            className="font-mono text-ink-muted mt-0.5"
            style={{ fontSize: 11, letterSpacing: '0.04em' }}
          >
            {unit.type} · ({unit.loc.x}, {unit.loc.y})
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <StatPair label="HP" value={unit.hp} />
          <StatPair label="Moves" value={unit.moves_left} />
          <StatPair label="Legal moves" value={highlightedCount} />
          {attackCount > 0 && (
            <StatPair label="Targets" value={attackCount} accent="warning" />
          )}
          {queueableCount > 0 && (
            <StatPair label="Queueable" value={queueableCount} />
          )}
        </div>

        {queuedOrderDestination && (
          <div
            className="rounded-md border border-border bg-bg-subtle px-2.5 py-2"
            style={{ fontSize: 12 }}
          >
            <div className="flex items-center justify-between gap-2">
              <Tag tone="accent" mono>
                queued → ({queuedOrderDestination.x}, {queuedOrderDestination.y})
              </Tag>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={onCancelQueuedOrder}
              >
                Cancel
              </Button>
            </div>
            <p className="text-ink-muted mt-1.5" style={{ fontSize: 11 }}>
              Cancels automatically on enemy contact, obstruction, or damage.
            </p>
          </div>
        )}

        {isWorker && (
          <div
            className="rounded-md border border-border bg-bg-subtle px-2.5 py-2"
            style={{ fontSize: 12 }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono uppercase text-ink-muted" style={{ fontSize: 10.5, letterSpacing: '0.08em' }}>
                Auto-improve
              </span>
              <div className="flex items-center gap-2">
                <Tag tone={automationActive ? 'warning' : 'neutral'} mono>
                  {automationActive ? 'on' : 'off'}
                </Tag>
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
            </div>
            <p className="text-ink-muted mt-1.5" style={{ fontSize: 11 }}>
              Routes to the nearest unimproved owned tile and builds on arrival.
            </p>
          </div>
        )}

        {(canFoundCity || (validImprovements && validImprovements.length > 0)) && (
          <div className="space-y-1.5">
            <span className="font-mono uppercase text-ink-muted" style={{ fontSize: 10.5, letterSpacing: '0.08em' }}>
              Actions
            </span>
            {canFoundCity && (
              <>
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
                  <p className="text-ink-muted" style={{ fontSize: 11 }}>
                    {canFoundCity.reason}
                  </p>
                )}
              </>
            )}
            {validImprovements && validImprovements.length > 0 && (
              <>
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
                    <span className="capitalize flex items-center gap-1.5">
                      <Hammer className="h-3.5 w-3.5" />
                      {imp.improvement.replace(/_/g, ' ')}
                    </span>
                    <span className="font-mono text-ink-muted" style={{ fontSize: 11 }}>
                      {formatCost(imp.cost)}
                    </span>
                  </Button>
                ))}
                {improvementQueued && (
                  <p className="text-ink-muted" style={{ fontSize: 11 }}>
                    An improvement is already queued for this worker.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </Panel>
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
    <Panel
      title={`City · #${city.id}`}
      kicker="city"
      className="rounded-none border-x-0 border-t-0"
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Building2 className="h-5 w-5 text-ink-soft" />
          <div className="flex items-center gap-3">
            <StatPair label="HP" value={city.hp} />
            <StatPair label="Loc" value={`(${city.loc.x}, ${city.loc.y})`} />
          </div>
        </div>

        {activeJob && (
          <div
            data-testid="city-production-indicator"
            className="rounded-md border border-border bg-bg-subtle px-2.5 py-2"
            style={{ fontSize: 12 }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-ink-soft" />
                <span className="font-mono uppercase text-ink-muted" style={{ fontSize: 10.5, letterSpacing: '0.08em' }}>
                  Producing
                </span>
                <span className="capitalize text-ink">{activeJob.target}</span>
              </span>
              <div className="flex items-center gap-2">
                <Tag tone="neutral" mono>
                  {turnsRemaining}t
                </Tag>
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
            <div className="mt-1.5 h-1 w-full rounded bg-surface-alt">
              <div
                className="h-1 rounded"
                style={{ width: `${progressPct}%`, background: 'var(--accent)' }}
              />
            </div>
            <div className="mt-1 font-mono text-ink-muted tabular-nums" style={{ fontSize: 11 }}>
              {activeJob.progress}/{activeJob.total_cost} · {productionRate}/turn
            </div>
          </div>
        )}

        {queue.length > 1 && (
          <div
            data-testid="city-queue-list"
            className="space-y-1"
            style={{ fontSize: 12 }}
          >
            <span className="font-mono uppercase text-ink-muted" style={{ fontSize: 10.5, letterSpacing: '0.08em' }}>
              Queued · {queue.length - 1}
            </span>
            {queue.slice(1).map((job, i) => {
              const idx = i + 1
              return (
                <div
                  key={idx}
                  className="flex items-center justify-between rounded-md border border-border bg-bg-subtle px-2 py-1"
                >
                  <span className="capitalize text-ink">{job.target}</span>
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
              <p className="text-xs text-ink-muted">Loading…</p>
            ) : trainable.length === 0 ? (
              <p className="text-xs text-ink-muted">
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
                  <span className="capitalize flex items-center gap-1.5">
                    <Swords className="h-3 w-3" />
                    {u.unit_type}
                    {u.locked && (
                      <Lock
                        aria-label={`Requires ${u.required_tech_name ?? u.required_tech}`}
                        className="h-3 w-3 text-ink-muted"
                      />
                    )}
                  </span>
                  <span className="font-mono text-ink-muted" style={{ fontSize: 11 }}>
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
              <p className="text-xs text-ink-muted">Loading…</p>
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
                      <span className="capitalize flex items-center gap-1.5">
                        {b.building_type}
                        {b.locked && (
                          <Lock
                            aria-label={`Requires ${b.required_tech_name ?? b.required_tech}`}
                            className="h-3 w-3 text-ink-muted"
                          />
                        )}
                        {queued && ' — queued'}
                      </span>
                      <span className="font-mono text-ink-muted" style={{ fontSize: 11 }}>
                        {b.locked
                          ? `Requires ${b.required_tech_name ?? b.required_tech}`
                          : formatCost(b.cost)}
                      </span>
                    </Button>
                  )
                })
            )}
            {buildable && buildable.every((b) => b.already_built) && (
              <p className="text-xs text-ink-muted">
                Every building is already constructed.
              </p>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </Panel>
  )
}

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

  const activeTech = groups.in_progress[0] ?? null
  const activeRemaining = activeTech
    ? Math.max(0, activeTech.cost_science - progress)
    : 0
  const activeEta =
    activeTech && sciencePerTurn > 0
      ? Math.max(1, Math.ceil(activeRemaining / sciencePerTurn))
      : null
  const activePct = activeTech
    ? Math.min(
        100,
        Math.round((progress / activeTech.cost_science) * 100),
      )
    : 0

  return (
    <Panel
      title="Research"
      kicker="research"
      action={
        <Tag tone="neutral" mono>
          +{sciencePerTurn}/turn
        </Tag>
      }
      className="rounded-none border-x-0 border-t-0"
    >
      <div className="space-y-3">
        {!techTree || !research ? (
          <p className="text-xs text-ink-muted">Loading…</p>
        ) : (
          <>
            {activeTech && (
              <div
                data-testid="tech-active-progress"
                className="rounded-md border border-border bg-bg-subtle px-2.5 py-2"
                style={{ fontSize: 12 }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex flex-col gap-0.5">
                    <span
                      className="font-mono uppercase text-accent"
                      style={{ fontSize: 10.5, letterSpacing: '0.10em' }}
                    >
                      Researching
                    </span>
                    <span
                      className="font-display text-ink leading-none"
                      style={{ fontSize: 16, letterSpacing: '-0.01em' }}
                    >
                      {activeTech.name}
                    </span>
                  </span>
                  <Tag tone="accent" mono>
                    {activeEta != null ? `${activeEta}t` : '—'}
                  </Tag>
                </div>
                <div className="mt-2 h-1 w-full rounded bg-surface-alt">
                  <div
                    className="h-1 rounded"
                    style={{
                      width: `${activePct}%`,
                      background: 'var(--accent)',
                    }}
                  />
                </div>
                <div
                  className="mt-1 flex items-center justify-between font-mono text-ink-muted tabular-nums"
                  style={{ fontSize: 11 }}
                >
                  <span>
                    {progress}/{activeTech.cost_science}
                  </span>
                  <span>{sciencePerTurn}/turn</span>
                </div>
              </div>
            )}

            {groups.available.length > 0 && (
              <TechGroup kicker="available" count={groups.available.length}>
                {groups.available.map((tech) => {
                  const eta =
                    sciencePerTurn > 0
                      ? Math.max(
                          1,
                          Math.ceil(tech.cost_science / sciencePerTurn),
                        )
                      : null
                  return (
                    <button
                      key={tech.id}
                      type="button"
                      onClick={() => onSelectActive(tech.id)}
                      title={describeTechUnlocks(tech)}
                      className="group flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-left transition-colors hover:bg-bg-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="flex flex-col gap-0">
                        <span
                          className="font-mono uppercase text-ink-muted"
                          style={{
                            fontSize: 10,
                            letterSpacing: '0.08em',
                          }}
                        >
                          {tech.cost_science}🔬
                          {eta != null ? ` · ${eta}t` : ''}
                        </span>
                        <span
                          className="font-display text-ink leading-none"
                          style={{ fontSize: 14, letterSpacing: '-0.01em' }}
                        >
                          {tech.name}
                        </span>
                      </span>
                      <Tag tone="accent" mono>
                        available
                      </Tag>
                    </button>
                  )
                })}
              </TechGroup>
            )}

            {groups.locked.length > 0 && (
              <TechGroup kicker="locked" count={groups.locked.length}>
                {groups.locked.map((tech) => (
                  <div
                    key={tech.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border bg-bg-subtle px-2.5 py-1.5"
                    title={`Requires: ${tech.requires.join(', ')}`}
                  >
                    <span className="flex flex-col gap-0">
                      <span
                        className="font-mono uppercase text-ink-muted"
                        style={{ fontSize: 10, letterSpacing: '0.08em' }}
                      >
                        {tech.cost_science}🔬
                      </span>
                      <span
                        className="flex items-center gap-1.5 font-display text-ink-muted leading-none"
                        style={{ fontSize: 14, letterSpacing: '-0.01em' }}
                      >
                        <Lock className="h-3 w-3 text-ink-muted" />
                        {tech.name}
                      </span>
                    </span>
                    <Tag tone="neutral" mono>
                      locked
                    </Tag>
                  </div>
                ))}
              </TechGroup>
            )}

            {groups.researched.length > 0 && (
              <TechGroup kicker="researched" count={groups.researched.length}>
                {groups.researched.map((tech) => (
                  <div
                    key={tech.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5"
                    title={describeTechUnlocks(tech)}
                  >
                    <span className="flex items-center gap-1.5">
                      <Check className="h-3 w-3 text-success" />
                      <span
                        className="font-display text-ink leading-none"
                        style={{ fontSize: 14, letterSpacing: '-0.01em' }}
                      >
                        {tech.name}
                      </span>
                    </span>
                    <Tag tone="success" mono>
                      done
                    </Tag>
                  </div>
                ))}
              </TechGroup>
            )}
          </>
        )}
      </div>
    </Panel>
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

/** Phase 5 rebuild: each tech group is a sub-Panel with the group name as
 * an accent kicker. A single child Panel gets the kicker treatment without
 * a heavy title bar so the four group headers don't overpower the outer
 * Research panel. */
function TechGroup({
  kicker,
  count,
  children,
}: {
  kicker: string
  count: number
  children: React.ReactNode
}) {
  return (
    <Panel kicker={`${kicker} · ${count}`} padded={false}>
      <div className="space-y-1 p-2">{children}</div>
    </Panel>
  )
}

interface DiplomacyPanelProps {
  currentPlayer: PlayerId
  /** All player IDs in the game, in seat order — used to resolve the
   * heraldic colour for each opponent's Identity treatment. */
  players: PlayerId[]
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
  players: PlayerId[]
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
  players,
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

  const opponentIdx = players.indexOf(opponent)
  const opponentColor = PLAYER_COLORS[opponentIdx >= 0 ? opponentIdx % 8 : 0] ?? '#888'

  return (
    <Panel
      kicker="thread"
      title={
        <button
          className="flex items-center gap-1.5 hover:underline focus:outline-none"
          onClick={() => onSelectOpponent(null)}
          aria-label="Back to diplomacy overview"
          data-testid="diplomacy-back"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          <Identity
            kind="human"
            name={opponent}
            id={opponent}
            color={opponentColor}
            size={18}
          />
        </button>
      }
      action={
        <Tag tone={rel.tone} mono>
          {rel.label}
        </Tag>
      }
      className="rounded-none border-x-0 border-t-0"
    >
      <div className="space-y-3">
        <div
          className="max-h-52 space-y-1.5 overflow-y-auto rounded-md border border-border bg-bg-subtle p-2"
          data-testid="diplomacy-thread"
        >
          {thread.length === 0 && queuedOutboundMessages.length === 0 ? (
            <p className="text-xs text-ink-muted">
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
                      className={`inline-block rounded-md px-2 py-1 ${
                        mine
                          ? 'border border-accent-soft bg-accent-soft text-ink'
                          : 'border border-border bg-surface text-ink'
                      }`}
                    >
                      <span
                        className="block font-mono uppercase text-ink-muted"
                        style={{ fontSize: 10, letterSpacing: '0.08em' }}
                      >
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
                  className="text-xs text-right opacity-70"
                  data-testid="diplomacy-message-queued"
                >
                  <div className="inline-block rounded-md border border-dashed border-border bg-surface px-2 py-1">
                    <span
                      className="block font-mono uppercase text-accent"
                      style={{ fontSize: 10, letterSpacing: '0.10em' }}
                    >
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
            className="w-full min-h-16 resize-none rounded-md border border-border bg-surface px-2 py-1 text-xs"
            placeholder="Compose a private message…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-testid="diplomacy-compose"
            maxLength={MESSAGE_BODY_MAX_LENGTH + 1}
          />
          <div className="flex items-center justify-between">
            <span
              className="font-mono tabular-nums text-ink-muted"
              style={{ fontSize: 10 }}
            >
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
          <Panel
            kicker={`inbound · ${inbound.length}`}
            padded={false}
            data-testid="diplomacy-inbound-proposals"
          >
            <div className="space-y-1.5 p-2">
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
          </Panel>
        )}

        {outbound.length > 0 && (
          <Panel
            kicker={`outbound · ${outbound.length}`}
            padded={false}
            data-testid="diplomacy-outbound-proposals"
          >
            <div className="space-y-1.5 p-2">
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
          </Panel>
        )}

        {activeTreaties.length > 0 && (
          <Panel
            kicker={`active treaties · ${activeTreaties.length}`}
            padded={false}
            data-testid="diplomacy-active-treaties"
          >
            <div className="space-y-1.5 p-2">
              {activeTreaties.map((t) => (
                <div
                  key={t.id}
                  className="flex items-start justify-between gap-2 rounded-md border border-border bg-surface px-2 py-1.5"
                  data-testid={`diplomacy-treaty-${t.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 text-xs">
                      <span
                        className="font-display text-ink leading-none"
                        style={{ fontSize: 13, letterSpacing: '-0.01em' }}
                      >
                        Treaty #{t.id}
                      </span>
                      <Tag tone="success" mono>
                        ratified t{t.turn_ratified}
                      </Tag>
                    </p>
                    <ul
                      className="mt-1 list-disc pl-4 text-ink-muted"
                      style={{ fontSize: 11 }}
                    >
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
          </Panel>
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
            className="rounded-md border border-destructive/40 bg-destructive/5 p-2"
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
                <p className="text-[11px] text-ink-muted">
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
      </div>
    </Panel>
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
      className="flex items-start justify-between gap-2 rounded-md border border-border bg-surface px-2 py-1.5"
      data-testid={`diplomacy-proposal-${proposal.id}`}
    >
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5">
          <span
            className="font-display text-ink leading-none"
            style={{ fontSize: 13, letterSpacing: '-0.01em' }}
          >
            Proposal #{proposal.id}
          </span>
          <Tag tone="warning" mono>
            expires t{proposal.expires_on_turn}
          </Tag>
        </p>
        <ul
          className="mt-1 list-disc pl-4 text-ink-muted"
          style={{ fontSize: 11 }}
        >
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
    <div
      className="rounded-md border border-border bg-bg-subtle p-2"
      data-testid="diplomacy-propose-root"
    >
      <button
        className="flex w-full items-center justify-between text-xs"
        onClick={() => setOpen((v) => !v)}
        data-testid="diplomacy-propose-toggle"
      >
        <span className="flex items-center gap-1.5">
          <FileSignature className="h-3.5 w-3.5 text-accent" />
          <span
            className="font-mono uppercase text-accent"
            style={{ fontSize: 10.5, letterSpacing: '0.10em' }}
          >
            Propose treaty
          </span>
          {queuedProposalsCount > 0 && (
            <Tag tone="accent" mono>
              {queuedProposalsCount} queued
            </Tag>
          )}
        </span>
        <span className="font-mono text-ink-muted" style={{ fontSize: 14 }}>
          {open ? '−' : '+'}
        </span>
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
                className={`rounded-full border px-2 py-0.5 font-mono uppercase transition-colors ${
                  kind === k
                    ? 'border-accent-soft bg-accent-soft text-accent'
                    : 'border-border bg-surface text-ink-muted hover:bg-bg-subtle'
                }`}
                style={{ fontSize: 10, letterSpacing: '0.08em' }}
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
    <div className="grid grid-cols-2 gap-1.5">
      {rows.map(({ key, value, setter }) => {
        const dec = () => setter(Math.max(0, value - 1))
        const inc = () => setter(Math.max(0, value + 1))
        return (
          <div
            key={key}
            className="flex items-center justify-between gap-1 rounded-md border border-border bg-bg-subtle px-1.5 py-0.5"
          >
            <span
              className="font-mono uppercase text-ink-muted"
              style={{ fontSize: 9.5, letterSpacing: '0.08em' }}
            >
              {key}
            </span>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                aria-label={`Decrease ${key}`}
                onClick={dec}
                disabled={value <= 0}
                className="flex h-5 w-5 items-center justify-center rounded-full border border-border bg-surface text-ink-muted transition-colors hover:bg-bg-subtle disabled:opacity-40"
              >
                −
              </button>
              <input
                type="number"
                min={0}
                value={value}
                onChange={(e) => setter(Math.max(0, Number(e.target.value) || 0))}
                aria-label={key}
                className="w-10 rounded border-0 bg-transparent px-0.5 py-0 text-center font-mono tabular-nums text-ink focus:outline-none focus:ring-1 focus:ring-accent"
                style={{ fontSize: 11 }}
                data-testid={`${testPrefix}-${key}`}
              />
              <button
                type="button"
                aria-label={`Increase ${key}`}
                onClick={inc}
                className="flex h-5 w-5 items-center justify-center rounded-full border border-border bg-surface text-ink-muted transition-colors hover:bg-bg-subtle"
              >
                +
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function relationLabel(
  relation: 'peace' | 'alliance' | 'war',
): { label: string; tone: 'destructive' | 'accent' | 'success' } {
  switch (relation) {
    case 'war':
      return { label: 'at war', tone: 'destructive' }
    case 'alliance':
      return { label: 'allied', tone: 'accent' }
    default:
      return { label: 'peace', tone: 'success' }
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
  players,
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
      <Panel
        title="Diplomacy"
        kicker="diplomacy"
        className="rounded-none border-x-0 border-t-0"
      >
        <p className="text-xs text-ink-muted">Loading…</p>
      </Panel>
    )
  }

  const opponents = diplomacy.discovered.filter((p) => p !== currentPlayer)

  if (selectedOpponent) {
    return (
      <DiplomacyThreadView
        key={selectedOpponent}
        currentPlayer={currentPlayer}
        players={players}
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
    <Panel
      title="Diplomacy"
      kicker="diplomacy"
      className="rounded-none border-x-0 border-t-0"
      padded={false}
    >
      <div className="p-2">
        {opponents.length === 0 ? (
          <p className="text-xs text-ink-muted px-1.5 py-1">
            No other players discovered yet.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {opponents.map((opponent) => {
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
              const idx = players.indexOf(opponent)
              const color = PLAYER_COLORS[idx >= 0 ? idx % 8 : 0] ?? '#888'
              return (
                <li key={opponent}>
                  <button
                    onClick={() => onSelectOpponent(opponent)}
                    className="group flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-2 text-left transition-colors hover:bg-bg-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    data-testid={`diplomacy-opponent-${opponent}`}
                    data-unread={unread > 0 ? 'true' : 'false'}
                  >
                    <Identity
                      kind="human"
                      name={opponent}
                      id={opponent}
                      color={color}
                      size={20}
                    />
                    <span className="ml-auto flex items-center gap-1.5">
                      {treaties.length > 0 && (
                        <Tag tone="neutral" mono>
                          {treaties.length}t
                        </Tag>
                      )}
                      <Tag tone={rel.tone} mono>
                        {rel.label}
                      </Tag>
                      {unread > 0 && (
                        <Tag
                          tone="accent"
                          mono
                          data-testid={`diplomacy-unread-${opponent}`}
                        >
                          {unread}
                        </Tag>
                      )}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Panel>
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
    <Panel
      title="Turn submissions"
      kicker={`${submittedPlayers.size}/${players.length} ready`}
      className="rounded-none border-x-0 border-t-0"
      padded={false}
    >
      <ul className="m-0 list-none p-0">
        {players.map((p, idx) => {
          const submitted = submittedPlayers.has(p)
          const isSelf = p === currentPlayer
          const color = PLAYER_COLORS[idx % 8] ?? '#888'
          return (
            <li
              key={p}
              className="flex items-center justify-between gap-2 px-3.5 py-2 [&:not(:last-child)]:border-b [&:not(:last-child)]:border-border"
              data-testid={`submission-row-${p}`}
              data-submitted={submitted ? 'true' : 'false'}
            >
              <Identity
                kind="human"
                name={p}
                id={p}
                color={color}
                size={20}
                showLabel
                label={isSelf ? 'you' : `seat ${idx + 1}`}
              />
              {submitted ? (
                <Tag tone="success" mono>
                  <Check className="h-3 w-3" />
                  submitted
                </Tag>
              ) : (
                <Tag tone="warning" mono>
                  <Clock className="h-3 w-3" />
                  deciding
                </Tag>
              )}
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
