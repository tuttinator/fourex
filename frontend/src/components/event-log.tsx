'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { formatRelativeTime } from '@/lib/utils'

interface GameEvent {
  id: string
  type: 'turn_start' | 'turn_end' | 'combat' | 'diplomacy' | 'city_founded' | 'unit_trained'
  timestamp: Date
  message: string
  severity: 'info' | 'warning' | 'error'
  playerId?: string
}

export function EventLog() {
  const [events, setEvents] = useState<GameEvent[]>([
    {
      id: '1',
      type: 'turn_start',
      timestamp: new Date(Date.now() - 30000),
      message: 'Turn 5 started',
      severity: 'info'
    },
    {
      id: '2',
      type: 'combat',
      timestamp: new Date(Date.now() - 25000),
      message: 'Agent_1 soldier attacks Agent_2 scout for 2 damage',
      severity: 'warning',
      playerId: 'Agent_1'
    },
    {
      id: '3',
      type: 'unit_trained',
      timestamp: new Date(Date.now() - 20000),
      message: 'Agent_2 trained archer in city 1',
      severity: 'info',
      playerId: 'Agent_2'
    },
    {
      id: '4',
      type: 'diplomacy',
      timestamp: new Date(Date.now() - 15000),
      message: 'Agent_1 declared war on Agent_3',
      severity: 'error',
      playerId: 'Agent_1'
    },
    {
      id: '5',
      type: 'turn_end',
      timestamp: new Date(Date.now() - 10000),
      message: 'Turn 5 ended',
      severity: 'info'
    },
  ])

  const getSeverityColor = (severity: GameEvent['severity']) => {
    switch (severity) {
      case 'info': return 'default'
      case 'warning': return 'secondary'
      case 'error': return 'destructive'
      default: return 'default'
    }
  }

  const getTypeIcon = (type: GameEvent['type']) => {
    switch (type) {
      case 'turn_start': return '▶️'
      case 'turn_end': return '⏹️'
      case 'combat': return '⚔️'
      case 'diplomacy': return '🤝'
      case 'city_founded': return '🏛️'
      case 'unit_trained': return '👥'
      default: return 'ℹ️'
    }
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Event Log</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-0">
        <ScrollArea className="h-full px-4 pb-4">
          <div className="space-y-3">
            {events.map((event) => (
              <div
                key={event.id}
                className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 hover:bg-muted/80 transition-colors"
              >
                <span className="text-sm">{getTypeIcon(event.type)}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge 
                      variant={getSeverityColor(event.severity)}
                      className="text-xs"
                    >
                      {event.type.replace('_', ' ')}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeTime(event.timestamp)}
                    </span>
                  </div>
                  <p className="text-sm text-foreground break-words">
                    {event.message}
                  </p>
                  {event.playerId && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Player: {event.playerId}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}