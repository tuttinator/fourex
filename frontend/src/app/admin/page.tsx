'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { 
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog'
import { useToast } from '@/hooks/use-toast'
import { Toaster } from '@/components/ui/toaster'
import {
  Activity,
  Users,
  GamepadIcon,
  Server,
  Clock,
  Zap,
  PlayCircle,
  PauseCircle,
  StopCircle,
  UserX,
  RefreshCw,
  Settings,
  Database,
  TrendingUp
} from 'lucide-react'
import type { GameListItem, SystemMetrics, PlayerStats } from '@/types/game'
import { api } from '@/lib/api'

export default function AdminPage() {
  const [games, setGames] = useState<GameListItem[]>([])
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null)
  const [playerStats, setPlayerStats] = useState<PlayerStats[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const { toast } = useToast()

  const fetchData = async () => {
    try {
      const [gamesData, metricsData, playersData] = await Promise.all([
        api.getGames(),
        api.getSystemMetrics(),
        api.getPlayerStats()
      ])
      
      setGames(gamesData)
      setMetrics(metricsData)
      setPlayerStats(playersData)
    } catch (error) {
      console.error('Failed to fetch admin data:', error)
      toast({
        title: "Error",
        description: "Failed to load admin data",
        variant: "destructive"
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const handleGameAction = async (gameId: string, action: 'pause' | 'resume' | 'stop') => {
    setActionLoading(`${gameId}-${action}`)
    try {
      await api.gameAction(gameId, action)
      await fetchData()
      toast({
        title: "Success",
        description: `Game ${action}d successfully`
      })
    } catch (error) {
      console.error(`Failed to ${action} game:`, error)
      toast({
        title: "Error",
        description: `Failed to ${action} game`,
        variant: "destructive"
      })
    } finally {
      setActionLoading(null)
    }
  }

  const handlePlayerAction = async (gameId: string, playerId: string, action: 'kick' | 'pause' | 'resume') => {
    setActionLoading(`${gameId}-${playerId}-${action}`)
    try {
      await api.playerAction(gameId, playerId, action)
      await fetchData()
      toast({
        title: "Success",
        description: `Player ${action}d successfully`
      })
    } catch (error) {
      console.error(`Failed to ${action} player:`, error)
      toast({
        title: "Error",
        description: `Failed to ${action} player`,
        variant: "destructive"
      })
    } finally {
      setActionLoading(null)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-500'
      case 'paused': return 'bg-yellow-500'
      case 'finished': return 'bg-gray-500'
      default: return 'bg-blue-500'
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active': return <Badge className="bg-green-500">Active</Badge>
      case 'paused': return <Badge className="bg-yellow-500">Paused</Badge>
      case 'finished': return <Badge variant="secondary">Finished</Badge>
      default: return <Badge variant="outline">{status}</Badge>
    }
  }

  if (loading) {
    return (
      <div className="container mx-auto py-8">
        <div className="flex items-center justify-center h-64">
          <RefreshCw className="h-8 w-8 animate-spin" />
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Admin Dashboard</h1>
          <p className="text-muted-foreground">Manage games, players, and monitor system health</p>
        </div>
        <Button onClick={fetchData} variant="outline">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* System Overview */}
      {metrics && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center">
                <GamepadIcon className="h-8 w-8 text-blue-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-muted-foreground">Active Games</p>
                  <p className="text-2xl font-bold">{metrics.activeGames}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center">
                <Users className="h-8 w-8 text-green-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-muted-foreground">Active Players</p>
                  <p className="text-2xl font-bold">{metrics.activePlayers}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center">
                <Server className="h-8 w-8 text-purple-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-muted-foreground">CPU Usage</p>
                  <p className="text-2xl font-bold">{metrics.cpuUsage}%</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center">
                <Database className="h-8 w-8 text-orange-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-muted-foreground">Memory Usage</p>
                  <p className="text-2xl font-bold">{metrics.memoryUsage}%</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <Tabs defaultValue="games" className="space-y-4">
        <TabsList>
          <TabsTrigger value="games">Game Management</TabsTrigger>
          <TabsTrigger value="players">Player Analytics</TabsTrigger>
          <TabsTrigger value="system">System Metrics</TabsTrigger>
        </TabsList>

        <TabsContent value="games" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Active Games</CardTitle>
            </CardHeader>
            <CardContent>
              {games.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <GamepadIcon className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No games currently running</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {games.map((game) => (
                    <div key={game.id} className="border rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div className="space-y-2">
                          <div className="flex items-center gap-3">
                            <h3 className="font-semibold">Game {game.id}</h3>
                            {getStatusBadge(game.status)}
                            <Badge variant="outline">Turn {game.turn}</Badge>
                          </div>
                          <div className="flex items-center gap-4 text-sm text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Users className="h-3 w-3" />
                              {game.players.length} players
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {new Date(game.createdAt).toLocaleString()}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          {game.status === 'active' && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  disabled={actionLoading?.startsWith(game.id)}
                                >
                                  <PauseCircle className="h-3 w-3 mr-1" />
                                  Pause
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>Pause Game</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    This will pause the game for all players. Are you sure?
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => handleGameAction(game.id, 'pause')}>
                                    Pause Game
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}

                          {game.status === 'paused' && (
                            <Button 
                              variant="outline" 
                              size="sm"
                              onClick={() => handleGameAction(game.id, 'resume')}
                              disabled={actionLoading?.startsWith(game.id)}
                            >
                              <PlayCircle className="h-3 w-3 mr-1" />
                              Resume
                            </Button>
                          )}

                          {game.status !== 'finished' && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button 
                                  variant="destructive" 
                                  size="sm"
                                  disabled={actionLoading?.startsWith(game.id)}
                                >
                                  <StopCircle className="h-3 w-3 mr-1" />
                                  Stop
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>Stop Game</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    This will permanently end the game. This action cannot be undone.
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                                  <AlertDialogAction 
                                    onClick={() => handleGameAction(game.id, 'stop')}
                                    className="bg-destructive text-destructive-foreground"
                                  >
                                    Stop Game
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}
                        </div>
                      </div>

                      {/* Player Management */}
                      <div className="mt-4 pt-4 border-t">
                        <h4 className="text-sm font-medium mb-2">Players</h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                          {game.players.map((player) => (
                            <div key={player.id} className="flex items-center justify-between bg-muted rounded p-2">
                              <div className="flex items-center gap-2">
                                <div className={`w-2 h-2 rounded-full ${getStatusColor(player.status)}`} />
                                <span className="text-sm font-medium">{player.name}</span>
                                <Badge variant="outline" className="text-xs">
                                  {player.status}
                                </Badge>
                              </div>
                              <div className="flex items-center gap-1">
                                {player.status === 'active' && game.status === 'active' && (
                                  <AlertDialog>
                                    <AlertDialogTrigger asChild>
                                      <Button 
                                        variant="ghost" 
                                        size="sm"
                                        disabled={actionLoading?.includes(player.id)}
                                      >
                                        <UserX className="h-3 w-3" />
                                      </Button>
                                    </AlertDialogTrigger>
                                    <AlertDialogContent>
                                      <AlertDialogHeader>
                                        <AlertDialogTitle>Kick Player</AlertDialogTitle>
                                        <AlertDialogDescription>
                                          Remove {player.name} from the game? They will not be able to rejoin.
                                        </AlertDialogDescription>
                                      </AlertDialogHeader>
                                      <AlertDialogFooter>
                                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                                        <AlertDialogAction 
                                          onClick={() => handlePlayerAction(game.id, player.id, 'kick')}
                                          className="bg-destructive text-destructive-foreground"
                                        >
                                          Kick Player
                                        </AlertDialogAction>
                                      </AlertDialogFooter>
                                    </AlertDialogContent>
                                  </AlertDialog>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="players" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Player Analytics</CardTitle>
            </CardHeader>
            <CardContent>
              {playerStats.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <TrendingUp className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No player statistics available</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {playerStats.map((player) => (
                    <div key={player.id} className="border rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="font-semibold">{player.name}</h3>
                        <Badge variant="outline">{player.gamesPlayed} games</Badge>
                      </div>
                      
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                        <div>
                          <p className="text-muted-foreground">Win Rate</p>
                          <p className="font-mono text-lg">{player.winRate}%</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Avg Turns</p>
                          <p className="font-mono text-lg">{player.avgTurns}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Total Tokens</p>
                          <p className="font-mono text-lg">{player.totalTokens.toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Avg Latency</p>
                          <p className="font-mono text-lg">{player.avgLatency}ms</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="system" className="space-y-4">
          {metrics && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Activity className="h-5 w-5" />
                    System Performance
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">CPU Usage</span>
                    <span className="font-mono">{metrics.cpuUsage}%</span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-2">
                    <div 
                      className="bg-blue-500 h-2 rounded-full transition-all"
                      style={{ width: `${metrics.cpuUsage}%` }}
                    />
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Memory Usage</span>
                    <span className="font-mono">{metrics.memoryUsage}%</span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-2">
                    <div 
                      className="bg-green-500 h-2 rounded-full transition-all"
                      style={{ width: `${metrics.memoryUsage}%` }}
                    />
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Disk Usage</span>
                    <span className="font-mono">{metrics.diskUsage}%</span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-2">
                    <div 
                      className="bg-orange-500 h-2 rounded-full transition-all"
                      style={{ width: `${metrics.diskUsage}%` }}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Zap className="h-5 w-5" />
                    API Metrics
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Requests/min</span>
                    <span className="font-mono">{metrics.requestsPerMinute}</span>
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Avg Response Time</span>
                    <span className="font-mono">{metrics.avgResponseTime}ms</span>
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Error Rate</span>
                    <span className="font-mono">{metrics.errorRate}%</span>
                  </div>
                  
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Active Connections</span>
                    <span className="font-mono">{metrics.activeConnections}</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Toaster />
    </div>
  )
}