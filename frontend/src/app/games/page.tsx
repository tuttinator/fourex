'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { api, queryKeys } from '@/lib/api'
import { formatRelativeTime } from '@/lib/utils'
import { Eye, RotateCcw, Plus, Loader2 } from 'lucide-react'
import { CreateGameDialog } from '@/components/create-game-dialog'

interface GameInfo {
  id: string
  turn: number
  players: string[]
  status: 'active' | 'finished'
  created_at: string
  winner?: string
}

export default function GamesPage() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  const { data: gameIds, isLoading, error } = useQuery({
    queryKey: queryKeys.games,
    queryFn: api.listGames,
    refetchInterval: 5000, // Refresh every 5 seconds
  })

  // Mock game info - in real app, this would come from a separate endpoint
  const gameInfos: GameInfo[] = gameIds?.map(id => ({
    id,
    turn: Math.floor(Math.random() * 50) + 1,
    players: [`agent_${Math.floor(Math.random() * 4) + 1}`, `agent_${Math.floor(Math.random() * 4) + 5}`],
    status: Math.random() > 0.3 ? 'active' : 'finished',
    created_at: new Date(Date.now() - Math.random() * 86400000 * 7).toISOString(),
    winner: Math.random() > 0.5 ? `agent_${Math.floor(Math.random() * 8) + 1}` : undefined
  })) || []

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
        <div className="text-center text-red-500">
          <p>Failed to load games: {error.message}</p>
          <Button 
            variant="outline" 
            onClick={() => window.location.reload()}
            className="mt-4"
          >
            Retry
          </Button>
        </div>
      </div>
    )
  }

  const activeGames = gameInfos.filter(g => g.status === 'active')
  const finishedGames = gameInfos.filter(g => g.status === 'finished')

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

      {/* Active Games */}
      <div className="mb-8">
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          Active Games
          <Badge variant="secondary" className="ml-2">
            {activeGames.length}
          </Badge>
        </h2>
        
        {activeGames.length === 0 ? (
          <Card>
            <CardContent className="flex items-center justify-center h-32">
              <p className="text-muted-foreground">No active games</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {activeGames.map((game) => (
              <GameCard key={game.id} game={game} />
            ))}
          </div>
        )}
      </div>

      {/* Finished Games */}
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          Finished Games
          <Badge variant="secondary" className="ml-2">
            {finishedGames.length}
          </Badge>
        </h2>
        
        {finishedGames.length === 0 ? (
          <Card>
            <CardContent className="flex items-center justify-center h-32">
              <p className="text-muted-foreground">No finished games</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {finishedGames.map((game) => (
              <GameCard key={game.id} game={game} />
            ))}
          </div>
        )}
      </div>

      <CreateGameDialog 
        open={createDialogOpen} 
        onOpenChange={setCreateDialogOpen} 
      />
    </div>
  )
}

function GameCard({ game }: { game: GameInfo }) {
  const isActive = game.status === 'active'
  
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{game.id}</CardTitle>
          <Badge variant={isActive ? "default" : "secondary"}>
            {game.status}
          </Badge>
        </div>
        <CardDescription>
          Turn {game.turn} • {game.players.length} players
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium mb-1">Players</p>
            <div className="flex flex-wrap gap-1">
              {game.players.map((player) => (
                <Badge key={player} variant="outline" className="text-xs">
                  {player}
                </Badge>
              ))}
            </div>
          </div>
          
          {game.winner && (
            <div>
              <p className="text-sm font-medium mb-1">Winner</p>
              <Badge variant="default">{game.winner}</Badge>
            </div>
          )}
          
          <div>
            <p className="text-sm text-muted-foreground">
              {formatRelativeTime(new Date(game.created_at))}
            </p>
          </div>
          
          <div className="flex gap-2 pt-2">
            {isActive ? (
              <Button asChild size="sm" className="flex-1">
                <Link href={`/games/${game.id}/observe`}>
                  <Eye className="h-4 w-4 mr-2" />
                  Observe Live
                </Link>
              </Button>
            ) : (
              <Button asChild variant="outline" size="sm" className="flex-1">
                <Link href={`/games/${game.id}/replay`}>
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Replay
                </Link>
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}