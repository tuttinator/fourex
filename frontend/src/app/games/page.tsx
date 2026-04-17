'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { api, queryKeys } from '@/lib/api'
import { Eye, Plus, Loader2, AlertCircle, ChevronLeft, ChevronRight, Users, Swords } from 'lucide-react'
import { CreateGameDialog } from '@/components/create-game-dialog'
import type { GamesListParams, GameSummary } from '@/types/game'

const STATUS_OPTIONS = [
  { value: undefined, label: 'All' },
  { value: 'waiting' as const, label: 'Waiting' },
  { value: 'active' as const, label: 'Active' },
  { value: 'ended' as const, label: 'Ended' },
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

function GameCard({ game }: { game: GameSummary }) {
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg truncate">{game.game_id}</CardTitle>
          <Badge variant={statusVariant(game.status)}>{game.status}</Badge>
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

        <Button asChild size="sm" className="w-full">
          <Link href={`/games/${game.game_id}`}>
            <Eye className="h-4 w-4 mr-2" />
            {game.status === 'waiting' ? 'View Lobby' : 'View Game'}
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}

export default function GamesPage() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<GamesListParams['status']>(undefined)
  const [sortBy, setSortBy] = useState<GamesListParams['sort_by']>('created_at')
  const [sortOrder, setSortOrder] = useState<GamesListParams['sort_order']>('desc')
  const [page, setPage] = useState(0)

  const params: GamesListParams = {
    status: statusFilter,
    sort_by: sortBy,
    sort_order: sortOrder,
    offset: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  }

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.games(params),
    queryFn: () => api.listGames(params),
    refetchInterval: 10000,
  })

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

  const games = data?.games ?? []

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
            {data.total} game{data.total !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {games.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center h-48">
            <p className="text-muted-foreground mb-4">
              {statusFilter ? `No ${statusFilter} games` : 'No games yet'}
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
              <GameCard key={game.game_id} game={game} />
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
