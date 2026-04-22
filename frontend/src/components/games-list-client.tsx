'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { api, queryKeys } from '@/lib/api'
import {
  Archive,
  ArchiveRestore,
  Eye,
  Plus,
  Loader2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Users,
  Swords,
  Bot,
} from 'lucide-react'
import { CreateGameDialog } from '@/components/create-game-dialog'
import type { GamesListParams, GameSummary, SeatSummary } from '@/types/game'

type StatusFilterValue = GamesListParams['status'] | 'in_progress' | 'archived'

interface StatusOption {
  value: StatusFilterValue | undefined
  label: string
}

const STATUS_OPTIONS: StatusOption[] = [
  { value: 'in_progress', label: 'In progress' },
  { value: 'waiting', label: 'Waiting' },
  { value: 'ended', label: 'Ended' },
  { value: 'archived', label: 'Archived' },
  { value: undefined, label: 'All' },
]

const SORT_OPTIONS = [
  { value: 'created_at', label: 'Created' },
  { value: 'turn', label: 'Turn' },
  { value: 'status', label: 'Status' },
] as const

const PAGE_SIZE = 12

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

function isAgentVsAgent(seats: SeatSummary[], playerSlots: number): boolean {
  // All filled seats are MCP-keyed (no Auth.js identity) AND every slot is taken.
  // The second clause stops the badge from flickering onto a half-joined lobby.
  if (seats.length < playerSlots) return false
  if (seats.length < 2) return false
  return seats.every((s) => s.user_identity_id === null)
}

function viewerIsSeated(seats: SeatSummary[], userIdentityId: string | null): boolean {
  if (!userIdentityId) return false
  return seats.some((s) => s.user_identity_id !== null && String(s.user_identity_id) === userIdentityId)
}

function viewerIsCreator(
  game: GameSummary,
  userIdentityId: string | null,
): boolean {
  // Creator check maps the signed-in user onto the slot-0 player_id by
  // finding their seat's identity. Matches the backend rule enforced by
  // PersistentGameController._user_is_creator.
  if (!userIdentityId) return false
  if (!game.creator) return false
  const seats = game.seats ?? []
  const mySeat = seats.find(
    (s) => s.user_identity_id !== null && String(s.user_identity_id) === userIdentityId,
  )
  return mySeat !== undefined && mySeat.player_id === game.creator
}

interface CardActionProps {
  game: GameSummary
  userIdentityId: string | null
  seated: boolean
}

function CardAction({ game, userIdentityId, seated }: CardActionProps) {
  const isActive = game.status === 'active'
  const isWaiting = game.status === 'waiting'
  const isArchived = Boolean(game.archived_at)

  // Archived games behave like "View" regardless of prior status — the
  // default-list exclusion already keeps them off the main view, so when a
  // viewer does surface one (Archived filter) we don't pretend they can
  // Resume or Observe a hidden game.
  if (isArchived) {
    return (
      <Button asChild size="sm" variant="outline" className="w-full">
        <Link href={`/games/${game.game_id}`}>
          <Eye className="h-4 w-4 mr-2" />
          View
        </Link>
      </Button>
    )
  }

  if (!userIdentityId) {
    if (isActive) {
      return (
        <Button asChild size="sm" variant="outline" className="w-full">
          <Link href="/signin">Sign in to observe</Link>
        </Button>
      )
    }
    return (
      <Button asChild size="sm" className="w-full">
        <Link href={`/games/${game.game_id}`}>
          <Eye className="h-4 w-4 mr-2" />
          {isWaiting ? 'View Lobby' : 'View Game'}
        </Link>
      </Button>
    )
  }

  if (seated && isActive) {
    return (
      <Button asChild size="sm" className="w-full">
        <Link href={`/games/${game.game_id}`}>Resume</Link>
      </Button>
    )
  }

  if (!seated && isActive) {
    return (
      <Button asChild size="sm" className="w-full">
        <Link href={`/games/${game.game_id}/observe`}>
          <Eye className="h-4 w-4 mr-2" />
          Observe
        </Link>
      </Button>
    )
  }

  if (isWaiting) {
    return (
      <Button asChild size="sm" className="w-full" variant={seated ? 'default' : 'outline'}>
        <Link href={`/games/${game.game_id}`}>View Lobby</Link>
      </Button>
    )
  }

  return (
    <Button asChild size="sm" variant="outline" className="w-full">
      <Link href={`/games/${game.game_id}`}>
        <Eye className="h-4 w-4 mr-2" />
        View
      </Link>
    </Button>
  )
}

interface ArchiveToggleButtonProps {
  game: GameSummary
}

function ArchiveToggleButton({ game }: ArchiveToggleButtonProps) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const isArchived = Boolean(game.archived_at)

  const mutation = useMutation({
    mutationFn: () =>
      isArchived ? api.unarchiveGame(game.game_id) : api.archiveGame(game.game_id),
    onSuccess: () => {
      setOpen(false)
      // The games-list response is keyed on (status, sort_by, sort_order,
      // offset, limit, include_archived) so invalidate the whole namespace
      // rather than trying to patch an individual page.
      queryClient.invalidateQueries({ queryKey: ['games'] })
    },
  })

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={isArchived ? 'Unarchive game' : 'Archive game'}
        title={isArchived ? 'Unarchive game' : 'Archive game'}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setOpen(true)
        }}
      >
        {isArchived ? (
          <ArchiveRestore className="h-4 w-4" />
        ) : (
          <Archive className="h-4 w-4" />
        )}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isArchived ? 'Restore this game?' : 'Archive this game?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isArchived
                ? 'Restoring moves the game back into the default list. Its snapshots and history are unchanged.'
                : 'Archiving hides the game from your default list. Turn snapshots are preserved and you can restore it later.'}
              {mutation.isError && (
                <span className="block mt-2 text-destructive">
                  {mutation.error instanceof Error
                    ? mutation.error.message
                    : 'Action failed. Try again.'}
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={mutation.isPending}
              onClick={(e) => {
                e.preventDefault()
                mutation.mutate()
              }}
            >
              {mutation.isPending
                ? isArchived
                  ? 'Restoring…'
                  : 'Archiving…'
                : isArchived
                  ? 'Unarchive'
                  : 'Archive'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function GameCard({ game, userIdentityId }: { game: GameSummary; userIdentityId: string | null }) {
  const seats = game.seats ?? []
  const seated = viewerIsSeated(seats, userIdentityId)
  const agentVsAgent = isAgentVsAgent(seats, game.player_slots)
  const ownsGame = viewerIsCreator(game, userIdentityId)
  const isArchived = Boolean(game.archived_at)

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-lg truncate">{game.game_id}</CardTitle>
          <div className="flex items-center gap-1">
            {agentVsAgent && (
              <Badge variant="secondary" className="flex items-center gap-1">
                <Bot className="h-3 w-3" />
                Agent vs Agent
              </Badge>
            )}
            {isArchived && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Archive className="h-3 w-3" />
                Archived
              </Badge>
            )}
            <Badge variant={statusVariant(game.status)}>{game.status}</Badge>
            {ownsGame && <ArchiveToggleButton game={game} />}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <Users className="h-3.5 w-3.5" />
            <span>{game.players.length}/{game.player_slots} player{game.player_slots !== 1 ? 's' : ''}</span>
          </div>
          <div className="flex items-center gap-1">
            <Swords className="h-3.5 w-3.5" />
            <span>Turn {game.turn}/{game.max_turns}</span>
          </div>
        </div>

        {game.winner && (
          <p className="text-sm">
            Winner: <span className="font-medium">{game.winner}</span>
            {game.victory_type && <span className="text-muted-foreground"> ({game.victory_type})</span>}
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          Created {formatDate(game.created_at)}
        </p>

        <CardAction game={game} userIdentityId={userIdentityId} seated={seated} />
      </CardContent>
    </Card>
  )
}

export function GamesListClient({ userIdentityId }: { userIdentityId: string | null }) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  // Default to "In progress" per Phase 2 — researchers land on games they could
  // observe right now. Switching to "All" still supported via the filter chips.
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue | undefined>('in_progress')
  const [sortBy, setSortBy] = useState<GamesListParams['sort_by']>('created_at')
  const [sortOrder, setSortOrder] = useState<GamesListParams['sort_order']>('desc')
  const [page, setPage] = useState(0)

  // Map the UI synonyms onto the backend shape:
  //  - "in_progress" ⇒ status=active
  //  - "archived"    ⇒ status cleared, include_archived=true (any status is fine)
  const isArchivedFilter = statusFilter === 'archived'
  const backendStatus: GamesListParams['status'] = isArchivedFilter
    ? undefined
    : statusFilter === 'in_progress'
      ? 'active'
      : statusFilter

  const params: GamesListParams = {
    status: backendStatus,
    sort_by: sortBy,
    sort_order: sortOrder,
    offset: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    include_archived: isArchivedFilter,
  }

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.games(params),
    queryFn: () => api.listGames(params),
    refetchInterval: 10000,
  })

  // When viewing archived games, the backend returns a mix of all prior
  // statuses — client-side filter to archived-only so the chip label
  // matches the content.
  const games = (data?.games ?? []).filter((g) =>
    isArchivedFilter ? Boolean(g.archived_at) : true,
  )
  const totalDisplay = isArchivedFilter ? games.length : data?.total ?? 0
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin" />
          <span className="ml-2">Loading games...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-4">Failed to load games: {error.message}</p>
          <Button variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold">Games</h1>
          <p className="text-muted-foreground mt-1">
            Observe live matches or replay historical games
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Create Game
        </Button>
      </div>

      {/* Filters and sorting */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Status:</span>
          <div className="flex gap-1">
            {STATUS_OPTIONS.map((opt) => (
              <Button
                key={opt.label}
                variant={statusFilter === opt.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => { setStatusFilter(opt.value); setPage(0) }}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Sort:</span>
          <select
            className="text-sm border rounded px-2 py-1 bg-background"
            value={sortBy}
            onChange={(e) => { setSortBy(e.target.value as GamesListParams['sort_by']); setPage(0) }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')}
          >
            {sortOrder === 'desc' ? '↓' : '↑'}
          </Button>
        </div>

        {data && (
          <span className="text-sm text-muted-foreground ml-auto">
            {totalDisplay} game{totalDisplay !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {games.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center h-48">
            <p className="text-muted-foreground mb-4">
              {statusFilter === 'in_progress'
                ? 'No games in progress'
                : statusFilter === 'archived'
                  ? 'No archived games'
                  : statusFilter
                    ? `No ${statusFilter} games`
                    : 'No games yet'}
            </p>
            <Button variant="outline" onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Create your first game
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {games.map((game) => (
              <GameCard key={game.game_id} game={game} userIdentityId={userIdentityId} />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-4 mt-6">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {page + 1} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages - 1}
                onClick={() => setPage(page + 1)}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}
        </>
      )}

      <CreateGameDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </div>
  )
}
