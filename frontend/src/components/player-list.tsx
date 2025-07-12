'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import type { PlayerListProps } from '@/types/game'
import { PLAYER_COLORS } from '@/types/game'
import { Eye, EyeOff } from 'lucide-react'

export function PlayerList({
  players,
  gameState,
  selectedPlayer,
  onPlayerSelect,
  onFogToggle
}: PlayerListProps) {
  return (
    <div className="p-4 space-y-4">
      {/* Fog of War Toggle */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Visibility</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center space-x-2">
            <Switch
              id="fog-of-war"
              onCheckedChange={onFogToggle}
            />
            <Label htmlFor="fog-of-war" className="text-sm">
              Fog of War
            </Label>
          </div>
        </CardContent>
      </Card>

      {/* Player List */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Players</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {players.map((player, index) => {
            const isSelected = selectedPlayer === player
            const playerResources = gameState.stockpiles[player]
            const playerUnits = Object.values(gameState.units).filter(u => u.owner === player)
            const playerCities = Object.values(gameState.cities).filter(c => c.owner === player)
            
            return (
              <div key={player} className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div 
                      className="w-3 h-3 rounded"
                      style={{ backgroundColor: PLAYER_COLORS[index] }}
                    />
                    <span className="font-medium text-sm">{player}</span>
                  </div>
                  <Button
                    variant={isSelected ? "default" : "outline"}
                    size="sm"
                    onClick={() => onPlayerSelect(isSelected ? null : player)}
                  >
                    {isSelected ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                  </Button>
                </div>
                
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-muted-foreground">Units:</span>
                    <span className="ml-1">{playerUnits.length}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Cities:</span>
                    <span className="ml-1">{playerCities.length}</span>
                  </div>
                </div>
                
                {playerResources && (
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Resources:</div>
                    <div className="grid grid-cols-2 gap-1 text-xs">
                      <div className="flex justify-between">
                        <span>Food:</span>
                        <span>{playerResources.food}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Wood:</span>
                        <span>{playerResources.wood}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Ore:</span>
                        <span>{playerResources.ore}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Crystal:</span>
                        <span>{playerResources.crystal}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Diplomatic Status */}
                <div className="flex flex-wrap gap-1">
                  {players.filter(p => p !== player).map(otherPlayer => {
                    const dipKey = `${player},${otherPlayer}`
                    const reverseDipKey = `${otherPlayer},${player}`
                    const diplomacy = gameState.diplomacy[dipKey] || gameState.diplomacy[reverseDipKey] || 'peace'
                    
                    return (
                      <Badge 
                        key={otherPlayer}
                        variant={diplomacy === 'alliance' ? 'default' : diplomacy === 'war' ? 'destructive' : 'secondary'}
                        className="text-xs"
                      >
                        {otherPlayer}: {diplomacy}
                      </Badge>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}