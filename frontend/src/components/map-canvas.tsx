'use client'

import { useRef, useEffect, useState } from 'react'
import type { MapCanvasProps, GameState, Tile, Unit, City } from '@/types/game'
import { TERRAIN_COLORS, UNIT_COLORS, PLAYER_COLORS } from '@/types/game'

export function MapCanvas({ 
  gameState, 
  selectedPlayer, 
  fogOfWarEnabled = false,
  diffMode = false,
  onTileClick,
  onUnitClick,
  onCityClick 
}: MapCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hoveredTile, setHoveredTile] = useState<{ tile: Tile; x: number; y: number } | null>(null)
  
  const tileSize = 24
  const mapWidth = gameState.map_width
  const mapHeight = gameState.map_height

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Set canvas size
    canvas.width = mapWidth * tileSize
    canvas.height = mapHeight * tileSize

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Draw tiles
    gameState.tiles.forEach(tile => {
      const x = tile.loc.x * tileSize
      const y = tile.loc.y * tileSize

      // Base terrain color
      ctx.fillStyle = TERRAIN_COLORS[tile.terrain]
      ctx.fillRect(x, y, tileSize, tileSize)

      // Grid lines
      ctx.strokeStyle = '#333'
      ctx.lineWidth = 0.5
      ctx.strokeRect(x, y, tileSize, tileSize)

      // Resource indicator
      if (tile.resource) {
        ctx.fillStyle = '#ffd700'
        ctx.beginPath()
        ctx.arc(x + tileSize - 4, y + 4, 2, 0, 2 * Math.PI)
        ctx.fill()
      }

      // Owner border
      if (tile.owner) {
        const playerIndex = gameState.players.indexOf(tile.owner)
        ctx.strokeStyle = PLAYER_COLORS[playerIndex] || '#666'
        ctx.lineWidth = 2
        ctx.strokeRect(x + 1, y + 1, tileSize - 2, tileSize - 2)
      }
    })

    // Draw cities
    Object.values(gameState.cities).forEach(city => {
      const x = city.loc.x * tileSize
      const y = city.loc.y * tileSize
      const playerIndex = gameState.players.indexOf(city.owner)

      // City circle
      ctx.fillStyle = PLAYER_COLORS[playerIndex] || '#666'
      ctx.beginPath()
      ctx.arc(x + tileSize/2, y + tileSize/2, 8, 0, 2 * Math.PI)
      ctx.fill()

      // City border
      ctx.strokeStyle = '#000'
      ctx.lineWidth = 1
      ctx.stroke()

      // HP indicator
      ctx.fillStyle = '#fff'
      ctx.font = '8px monospace'
      ctx.textAlign = 'center'
      ctx.fillText(city.hp.toString(), x + tileSize/2, y + tileSize/2 + 2)
    })

    // Draw units
    Object.values(gameState.units).forEach(unit => {
      const x = unit.loc.x * tileSize
      const y = unit.loc.y * tileSize
      const playerIndex = gameState.players.indexOf(unit.owner)

      // Unit square
      ctx.fillStyle = UNIT_COLORS[unit.type]
      ctx.fillRect(x + 4, y + 4, tileSize - 8, tileSize - 8)

      // Player color border
      ctx.strokeStyle = PLAYER_COLORS[playerIndex] || '#666'
      ctx.lineWidth = 2
      ctx.strokeRect(x + 4, y + 4, tileSize - 8, tileSize - 8)

      // Unit type indicator
      ctx.fillStyle = '#fff'
      ctx.font = '8px monospace'
      ctx.textAlign = 'center'
      const typeChar = unit.type.charAt(0).toUpperCase()
      ctx.fillText(typeChar, x + tileSize/2, y + tileSize/2 + 2)
    })

    // Apply fog of war
    if (fogOfWarEnabled && selectedPlayer) {
      // This would require implementing visibility calculation
      // For now, just dim non-visible areas
      ctx.fillStyle = 'rgba(0, 0, 0, 0.5)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
    }

  }, [gameState, selectedPlayer, fogOfWarEnabled, diffMode])

  const handleCanvasClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const x = Math.floor((event.clientX - rect.left) / tileSize)
    const y = Math.floor((event.clientY - rect.top) / tileSize)

    // Find what was clicked
    const tile = gameState.tiles.find(t => t.loc.x === x && t.loc.y === y)
    if (tile) {
      onTileClick?.(tile)

      // Check for unit on tile
      if (tile.unit_id) {
        const unit = gameState.units[tile.unit_id]
        if (unit) {
          onUnitClick?.(unit)
        }
      }

      // Check for city on tile
      if (tile.city_id) {
        const city = gameState.cities[tile.city_id]
        if (city) {
          onCityClick?.(city)
        }
      }
    }
  }

  const handleCanvasMouseMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const x = Math.floor((event.clientX - rect.left) / tileSize)
    const y = Math.floor((event.clientY - rect.top) / tileSize)

    const tile = gameState.tiles.find(t => t.loc.x === x && t.loc.y === y)
    if (tile) {
      setHoveredTile({ 
        tile, 
        x: event.clientX - rect.left, 
        y: event.clientY - rect.top 
      })
    } else {
      setHoveredTile(null)
    }
  }

  const handleCanvasMouseLeave = () => {
    setHoveredTile(null)
  }

  return (
    <div className="relative w-full h-full overflow-auto bg-gray-900">
      <canvas
        ref={canvasRef}
        className="map-grid cursor-crosshair"
        onClick={handleCanvasClick}
        onMouseMove={handleCanvasMouseMove}
        onMouseLeave={handleCanvasMouseLeave}
      />
      
      {/* Tooltip */}
      {hoveredTile && (
        <div 
          className="unit-tooltip"
          style={{ 
            left: hoveredTile.x, 
            top: hoveredTile.y 
          }}
        >
          <div className="text-xs">
            <div>Terrain: {hoveredTile.tile.terrain}</div>
            {hoveredTile.tile.resource && (
              <div>Resource: {hoveredTile.tile.resource}</div>
            )}
            {hoveredTile.tile.owner && (
              <div>Owner: {hoveredTile.tile.owner}</div>
            )}
            {hoveredTile.tile.unit_id && (
              <div>Unit: {gameState.units[hoveredTile.tile.unit_id]?.type}</div>
            )}
            {hoveredTile.tile.city_id && (
              <div>City: HP {gameState.cities[hoveredTile.tile.city_id]?.hp}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}