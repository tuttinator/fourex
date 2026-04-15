'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { api, queryKeys } from '@/lib/api'
import { Eye, Plus, Loader2, AlertCircle } from 'lucide-react'
import { CreateGameDialog } from '@/components/create-game-dialog'

export default function GamesPage() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  const { data: gameIds, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.games,
    queryFn: api.listGames,
    refetchInterval: 5000,
  })

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

  const games = gameIds ?? []

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold">Games</h1>
          <p className="text-muted-foreground mt-2">
            Observe live matches or replay historical games
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Create Game
        </Button>
      </div>

      {games.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center h-48">
            <p className="text-muted-foreground mb-4">No games yet</p>
            <Button variant="outline" onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Create your first game
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div>
          <h2 className="text-xl font-semibold mb-4 flex items-center">
            All Games
            <Badge variant="secondary" className="ml-2">
              {games.length}
            </Badge>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {games.map((gameId) => (
              <Card key={gameId} className="hover:shadow-md transition-shadow">
                <CardHeader className="pb-3">
                  <CardTitle className="text-lg">{gameId}</CardTitle>
                  <CardDescription>Game ID</CardDescription>
                </CardHeader>
                <CardContent>
                  <Button asChild size="sm" className="w-full">
                    <Link href={`/games/${gameId}/observe`}>
                      <Eye className="h-4 w-4 mr-2" />
                      Observe
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      <CreateGameDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </div>
  )
}
