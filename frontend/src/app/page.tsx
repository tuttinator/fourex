import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Activity, Brain, Clock, Users } from 'lucide-react'

export default function HomePage() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="text-center mb-16">
        <h1 className="text-4xl font-bold tracking-tight mb-4">
          4X Arena
        </h1>
        <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
          Real-time observation and analysis dashboard for AI agents playing 
          turn-based 4X strategy games
        </p>
        <div className="flex gap-4 justify-center">
          <Button asChild size="lg">
            <Link href="/games">
              View Active Games
            </Link>
          </Button>
          <Button variant="outline" size="lg" asChild>
            <Link href="/admin">
              Admin Panel
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-16">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Research Focus
            </CardTitle>
            <Brain className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">AI Behavior</div>
            <p className="text-xs text-muted-foreground">
              Study agent decision-making patterns
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Real-time Analysis
            </CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">Live Updates</div>
            <p className="text-xs text-muted-foreground">
              WebSocket-powered live game observation
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Multi-Agent
            </CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">2-8 Players</div>
            <p className="text-xs text-muted-foreground">
              Support for multiple AI agents per game
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Deterministic
            </CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">Reproducible</div>
            <p className="text-xs text-muted-foreground">
              Exact replay capability for analysis
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <Card>
          <CardHeader>
            <CardTitle>Live Match Observation</CardTitle>
            <CardDescription>
              Watch AI agents compete in real-time with fog-of-war toggles, 
              combat visualization, and diplomatic event tracking.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li>• Real-time map updates via WebSocket</li>
              <li>• Per-player fog-of-war visualization</li>
              <li>• Combat and diplomacy event streams</li>
              <li>• Resource and unit tracking</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Historical Analysis</CardTitle>
            <CardDescription>
              Replay any game turn-by-turn with LLM prompt inspection, 
              token usage analytics, and decision timeline analysis.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li>• Complete turn-by-turn replay</li>
              <li>• LLM prompt and response inspection</li>
              <li>• Token usage and latency metrics</li>
              <li>• State diff visualization</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}