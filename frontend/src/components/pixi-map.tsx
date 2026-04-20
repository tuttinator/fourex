'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import type { MapCanvasProps, Tile } from '@/types/game'
import { TERRAIN_COLORS, UNIT_COLORS, PLAYER_COLORS } from '@/types/game'
import { Application, Container, Graphics, Text, TextStyle } from 'pixi.js'

const TILE_SIZE = 32

const RESOURCE_ICONS: Record<string, string> = {
  food: 'F',
  wood: 'W',
  ore: 'O',
  crystal: 'C',
}

const UNIT_ICONS: Record<string, string> = {
  scout: 'Sc',
  worker: 'Wk',
  soldier: 'So',
  archer: 'Ar',
}

const IMPROVEMENT_ICONS: Record<string, string> = {
  farm: '~',
  mine: '^',
  crystal_extractor: '*',
}

function hexToNumber(hex: string): number {
  return parseInt(hex.replace('#', ''), 16)
}

function buildTileLookup(tiles: Tile[]): Map<string, Tile> {
  const map = new Map<string, Tile>()
  for (const tile of tiles) {
    map.set(`${tile.loc.x},${tile.loc.y}`, tile)
  }
  return map
}

interface HoverData {
  tile: Tile
  unit?: { type: string; hp: number; owner: string; moves_left: number }
  city?: { hp: number; owner: string; buildings: string[] }
  screenX: number
  screenY: number
}

export function PixiMap({
  gameState,
  selectedPlayer,
  fogOfWarEnabled = false,
  onTileClick,
  onUnitClick,
  onCityClick,
  selectedUnitId,
  selectedCityId,
  highlightedTiles,
  attackTiles,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const appRef = useRef<Application | null>(null)
  const worldRef = useRef<Container | null>(null)
  const isPanningRef = useRef(false)
  const lastPointerRef = useRef({ x: 0, y: 0 })
  const [hover, setHover] = useState<HoverData | null>(null)
  const [pixiReady, setPixiReady] = useState(0)

  // Initialise Pixi application
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const app = new Application()
    let disposed = false
    let initialized = false
    let appDestroyed = false

    const destroyApp = () => {
      if (!initialized || appDestroyed) return

      appDestroyed = true
      app.destroy(true, { children: true })

      if (appRef.current === app) {
        appRef.current = null
      }
      if (worldRef.current?.parent === app.stage) {
        worldRef.current = null
      }
    }

    const init = async () => {
      try {
        await app.init({
          background: 0x1a1a2e,
          resizeTo: container,
          antialias: true,
          resolution: window.devicePixelRatio || 1,
          autoDensity: true,
        })
      } catch (error) {
        if (!disposed) {
          console.error('Failed to initialize Pixi map', error)
        }
        return
      }

      initialized = true

      if (disposed) {
        destroyApp()
        return
      }

      container.appendChild(app.canvas)

      const world = new Container()
      world.eventMode = 'static'
      world.interactiveChildren = true
      app.stage.addChild(world)
      appRef.current = app
      worldRef.current = world
      setPixiReady((version) => version + 1)
    }

    init()

    return () => {
      disposed = true
      destroyApp()
    }
  }, [])

  // Render game state into the world container
  useEffect(() => {
    const world = worldRef.current
    if (!world) return

    world.removeChildren()

    const { map_width, map_height, tiles, units, cities, players } = gameState
    const tileLookup = buildTileLookup(tiles)

    // Terrain layer — draw all tiles, marking unexplored ones as dark
    const terrainGfx = new Graphics()
    if (fogOfWarEnabled) {
      // Draw unexplored tiles first (dark background for full grid)
      for (let gy = 0; gy < map_height; gy++) {
        for (let gx = 0; gx < map_width; gx++) {
          if (!tileLookup.has(`${gx},${gy}`)) {
            terrainGfx.rect(gx * TILE_SIZE, gy * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            terrainGfx.fill(0x0a0a14)
          }
        }
      }
    }
    // Draw visible tiles
    for (const tile of tiles) {
      const x = tile.loc.x * TILE_SIZE
      const y = tile.loc.y * TILE_SIZE
      const colour = hexToNumber(TERRAIN_COLORS[tile.terrain])

      terrainGfx.rect(x, y, TILE_SIZE, TILE_SIZE)
      terrainGfx.fill(colour)
    }
    world.addChild(terrainGfx)

    // Grid lines
    const gridGfx = new Graphics()
    gridGfx.setStrokeStyle({ width: 0.5, color: 0x333333, alpha: 0.5 })
    for (let gx = 0; gx <= map_width; gx++) {
      gridGfx.moveTo(gx * TILE_SIZE, 0)
      gridGfx.lineTo(gx * TILE_SIZE, map_height * TILE_SIZE)
      gridGfx.stroke()
    }
    for (let gy = 0; gy <= map_height; gy++) {
      gridGfx.moveTo(0, gy * TILE_SIZE)
      gridGfx.lineTo(map_width * TILE_SIZE, gy * TILE_SIZE)
      gridGfx.stroke()
    }
    world.addChild(gridGfx)

    // Resource indicators
    const resourceStyle = new TextStyle({
      fontFamily: 'monospace',
      fontSize: 9,
      fill: 0xffd700,
      fontWeight: 'bold',
    })
    for (const tile of tiles) {
      if (tile.resource) {
        const label = new Text({
          text: RESOURCE_ICONS[tile.resource] || '?',
          style: resourceStyle,
        })
        label.x = tile.loc.x * TILE_SIZE + TILE_SIZE - 10
        label.y = tile.loc.y * TILE_SIZE + 1
        world.addChild(label)
      }
    }

    // Improvements
    const improvementStyle = new TextStyle({
      fontFamily: 'monospace',
      fontSize: 10,
      fill: 0xcccccc,
    })
    for (const tile of tiles) {
      if (tile.improvement) {
        const label = new Text({
          text: IMPROVEMENT_ICONS[tile.improvement] || '?',
          style: improvementStyle,
        })
        label.x = tile.loc.x * TILE_SIZE + 2
        label.y = tile.loc.y * TILE_SIZE + TILE_SIZE - 13
        world.addChild(label)
      }
    }

    // Owner borders
    const ownerGfx = new Graphics()
    for (const tile of tiles) {
      if (tile.owner) {
        const playerIndex = players.indexOf(tile.owner)
        const colour = hexToNumber(PLAYER_COLORS[playerIndex] ?? '#666666')
        const x = tile.loc.x * TILE_SIZE
        const y = tile.loc.y * TILE_SIZE

        ownerGfx.setStrokeStyle({ width: 2, color: colour, alpha: 0.6 })
        ownerGfx.rect(x + 1, y + 1, TILE_SIZE - 2, TILE_SIZE - 2)
        ownerGfx.stroke()
      }
    }
    world.addChild(ownerGfx)

    // Cities
    const cityLabelStyle = new TextStyle({
      fontFamily: 'monospace',
      fontSize: 9,
      fill: 0xffffff,
      fontWeight: 'bold',
    })
    for (const city of Object.values(cities)) {
      const cx = city.loc.x * TILE_SIZE + TILE_SIZE / 2
      const cy = city.loc.y * TILE_SIZE + TILE_SIZE / 2
      const playerIndex = players.indexOf(city.owner)
      const colour = hexToNumber(PLAYER_COLORS[playerIndex] ?? '#666666')

      const cityGfx = new Graphics()
      // Outer circle
      cityGfx.circle(cx, cy, 12)
      cityGfx.fill(colour)
      cityGfx.setStrokeStyle({ width: 1.5, color: 0x000000 })
      cityGfx.circle(cx, cy, 12)
      cityGfx.stroke()

      // Building indicators as small dots around the city
      if (city.buildings.length > 0) {
        const buildingColours: Record<string, number> = {
          granary: 0xffd700,
          barracks: 0xff4444,
          walls: 0x888888,
          monument: 0xd8b4fe,
          library: 0x93c5fd,
          temple: 0xfbcfe8,
        }
        city.buildings.forEach((b, i) => {
          const angle = (i * 2 * Math.PI) / Math.max(city.buildings.length, 3) - Math.PI / 2
          const bx = cx + Math.cos(angle) * 9
          const by = cy + Math.sin(angle) * 9
          cityGfx.circle(bx, by, 2)
          cityGfx.fill(buildingColours[b] ?? 0xffffff)
        })
      }

      world.addChild(cityGfx)

      // HP text
      const hpLabel = new Text({
        text: city.hp.toString(),
        style: cityLabelStyle,
      })
      hpLabel.anchor.set(0.5, 0.5)
      hpLabel.x = cx
      hpLabel.y = cy
      world.addChild(hpLabel)
    }

    // Highlight overlay for queued-move target tiles (Phase 4)
    if (highlightedTiles && highlightedTiles.length > 0) {
      const highlightGfx = new Graphics()
      for (const coord of highlightedTiles) {
        const hx = coord.x * TILE_SIZE
        const hy = coord.y * TILE_SIZE
        highlightGfx.rect(hx, hy, TILE_SIZE, TILE_SIZE)
        highlightGfx.fill({ color: 0xfbbf24, alpha: 0.35 })
        highlightGfx.setStrokeStyle({ width: 2, color: 0xfbbf24, alpha: 0.9 })
        highlightGfx.rect(hx + 1, hy + 1, TILE_SIZE - 2, TILE_SIZE - 2)
        highlightGfx.stroke()
      }
      world.addChild(highlightGfx)
    }

    // Attack-target overlay (Phase 5) — red tile for each hostile in range.
    if (attackTiles && attackTiles.length > 0) {
      const attackGfx = new Graphics()
      for (const coord of attackTiles) {
        const hx = coord.x * TILE_SIZE
        const hy = coord.y * TILE_SIZE
        attackGfx.rect(hx, hy, TILE_SIZE, TILE_SIZE)
        attackGfx.fill({ color: 0xef4444, alpha: 0.35 })
        attackGfx.setStrokeStyle({ width: 2, color: 0xef4444, alpha: 0.95 })
        attackGfx.rect(hx + 1, hy + 1, TILE_SIZE - 2, TILE_SIZE - 2)
        attackGfx.stroke()
      }
      world.addChild(attackGfx)
    }

    // Selected-city ring (Phase 5)
    if (selectedCityId != null) {
      const city = cities[selectedCityId]
      if (city) {
        const ring = new Graphics()
        ring.setStrokeStyle({ width: 2.5, color: 0xfbbf24, alpha: 1 })
        const cx = city.loc.x * TILE_SIZE + TILE_SIZE / 2
        const cy = city.loc.y * TILE_SIZE + TILE_SIZE / 2
        ring.circle(cx, cy, 15)
        ring.stroke()
        world.addChild(ring)
      }
    }

    // Units
    const unitLabelStyle = new TextStyle({
      fontFamily: 'monospace',
      fontSize: 8,
      fill: 0xffffff,
      fontWeight: 'bold',
    })
    for (const unit of Object.values(units)) {
      const ux = unit.loc.x * TILE_SIZE
      const uy = unit.loc.y * TILE_SIZE
      const playerIndex = players.indexOf(unit.owner)
      const unitColour = hexToNumber(UNIT_COLORS[unit.type])
      const playerColour = hexToNumber(PLAYER_COLORS[playerIndex] ?? '#666666')

      const unitGfx = new Graphics()
      // Unit rectangle with player colour border
      unitGfx.roundRect(ux + 5, uy + 5, TILE_SIZE - 10, TILE_SIZE - 10, 3)
      unitGfx.fill(unitColour)
      unitGfx.setStrokeStyle({ width: 1.5, color: playerColour })
      unitGfx.roundRect(ux + 5, uy + 5, TILE_SIZE - 10, TILE_SIZE - 10, 3)
      unitGfx.stroke()
      world.addChild(unitGfx)

      // Unit type label
      const label = new Text({
        text: UNIT_ICONS[unit.type] || '?',
        style: unitLabelStyle,
      })
      label.anchor.set(0.5, 0.5)
      label.x = ux + TILE_SIZE / 2
      label.y = uy + TILE_SIZE / 2
      world.addChild(label)

      if (selectedUnitId != null && unit.id === selectedUnitId) {
        const ring = new Graphics()
        ring.setStrokeStyle({ width: 2.5, color: 0xfbbf24, alpha: 1 })
        ring.roundRect(ux + 3, uy + 3, TILE_SIZE - 6, TILE_SIZE - 6, 4)
        ring.stroke()
        world.addChild(ring)
      }
    }

    // Interactive layer for hover/click detection
    const interactiveLayer = new Graphics()
    interactiveLayer.rect(0, 0, map_width * TILE_SIZE, map_height * TILE_SIZE)
    interactiveLayer.fill({ color: 0x000000, alpha: 0 })
    interactiveLayer.eventMode = 'static'
    interactiveLayer.cursor = 'crosshair'

    interactiveLayer.on('pointermove', (e) => {
      if (isPanningRef.current) return

      const local = world.toLocal(e.global)
      const tileX = Math.floor(local.x / TILE_SIZE)
      const tileY = Math.floor(local.y / TILE_SIZE)

      if (tileX < 0 || tileX >= map_width || tileY < 0 || tileY >= map_height) {
        setHover(null)
        return
      }

      const tile = tileLookup.get(`${tileX},${tileY}`)
      if (!tile) {
        setHover(null)
        return
      }

      const hoverData: HoverData = {
        tile,
        screenX: e.global.x,
        screenY: e.global.y,
      }

      if (tile.unit_id && units[tile.unit_id]) {
        const u = units[tile.unit_id]
        hoverData.unit = { type: u.type, hp: u.hp, owner: u.owner, moves_left: u.moves_left }
      }

      if (tile.city_id && cities[tile.city_id]) {
        const c = cities[tile.city_id]
        hoverData.city = { hp: c.hp, owner: c.owner, buildings: [...c.buildings] }
      }

      setHover(hoverData)
    })

    interactiveLayer.on('pointerdown', (e) => {
      const local = world.toLocal(e.global)
      const tileX = Math.floor(local.x / TILE_SIZE)
      const tileY = Math.floor(local.y / TILE_SIZE)
      const tile = tileLookup.get(`${tileX},${tileY}`)
      if (!tile) return

      onTileClick?.(tile)
      if (tile.unit_id && units[tile.unit_id]) onUnitClick?.(units[tile.unit_id])
      if (tile.city_id && cities[tile.city_id]) onCityClick?.(cities[tile.city_id])
    })

    world.addChild(interactiveLayer)
  }, [gameState, selectedPlayer, fogOfWarEnabled, onTileClick, onUnitClick, onCityClick, pixiReady, selectedUnitId, selectedCityId, highlightedTiles, attackTiles])

  // Zoom handler
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault()
    const world = worldRef.current
    if (!world) return

    const direction = e.deltaY < 0 ? 1 : -1
    const factor = 1 + direction * 0.1
    const newScale = Math.min(Math.max(world.scale.x * factor, 0.25), 4)

    // Zoom towards cursor
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const cursorX = e.clientX - rect.left
    const cursorY = e.clientY - rect.top

    const worldBefore = world.toLocal({ x: cursorX, y: cursorY })
    world.scale.set(newScale)
    const worldAfter = world.toLocal({ x: cursorX, y: cursorY })

    world.x += (worldAfter.x - worldBefore.x) * newScale
    world.y += (worldAfter.y - worldBefore.y) * newScale
  }, [])

  // Pan handlers
  const handlePointerDown = useCallback((e: PointerEvent) => {
    // Middle mouse button or right click for pan, or left click + drag
    if (e.button === 1 || e.button === 2 || e.button === 0) {
      isPanningRef.current = true
      lastPointerRef.current = { x: e.clientX, y: e.clientY }
    }
  }, [])

  const handlePointerMove = useCallback((e: PointerEvent) => {
    if (!isPanningRef.current) return
    const world = worldRef.current
    if (!world) return

    const dx = e.clientX - lastPointerRef.current.x
    const dy = e.clientY - lastPointerRef.current.y

    // Only start panning if we've moved a meaningful distance
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      world.x += dx
      world.y += dy
      lastPointerRef.current = { x: e.clientX, y: e.clientY }
    }
  }, [])

  const handlePointerUp = useCallback(() => {
    isPanningRef.current = false
  }, [])

  const handleMouseLeave = useCallback(() => {
    setHover(null)
    isPanningRef.current = false
  }, [])

  // Attach event listeners
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    container.addEventListener('wheel', handleWheel, { passive: false })
    container.addEventListener('pointerdown', handlePointerDown)
    container.addEventListener('pointermove', handlePointerMove)
    container.addEventListener('pointerup', handlePointerUp)
    container.addEventListener('pointerleave', handlePointerUp)
    container.addEventListener('mouseleave', handleMouseLeave)

    return () => {
      container.removeEventListener('wheel', handleWheel)
      container.removeEventListener('pointerdown', handlePointerDown)
      container.removeEventListener('pointermove', handlePointerMove)
      container.removeEventListener('pointerup', handlePointerUp)
      container.removeEventListener('pointerleave', handlePointerUp)
      container.removeEventListener('mouseleave', handleMouseLeave)
    }
  }, [handleWheel, handlePointerDown, handlePointerMove, handlePointerUp, handleMouseLeave])

  return (
    <div className="relative w-full h-full overflow-hidden bg-gray-900">
      <div ref={containerRef} className="w-full h-full" />

      {/* Tooltip */}
      {hover && (
        <div
          className="absolute pointer-events-none z-50 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white shadow-lg"
          style={{
            left: hover.screenX + 12,
            top: hover.screenY + 12,
          }}
        >
          <div className="space-y-0.5">
            <div className="font-semibold capitalize">{hover.tile.terrain}</div>
            <div className="text-gray-400">
              ({hover.tile.loc.x}, {hover.tile.loc.y})
            </div>
            {hover.tile.resource && (
              <div>
                Resource: <span className="text-yellow-400 capitalize">{hover.tile.resource}</span>
              </div>
            )}
            {hover.tile.owner && (
              <div>
                Owner: <span className="text-blue-300">{hover.tile.owner}</span>
              </div>
            )}
            {hover.tile.improvement && (
              <div>
                Improvement: <span className="text-gray-300 capitalize">{hover.tile.improvement}</span>
              </div>
            )}
            {hover.unit && (
              <div className="border-t border-gray-600 pt-0.5 mt-0.5">
                <span className="capitalize">{hover.unit.type}</span>{' '}
                <span className="text-gray-400">
                  HP:{hover.unit.hp} Mv:{hover.unit.moves_left}
                </span>
              </div>
            )}
            {hover.city && (
              <div className="border-t border-gray-600 pt-0.5 mt-0.5">
                City HP:{hover.city.hp}
                {hover.city.buildings.length > 0 && (
                  <div className="text-gray-400">
                    {hover.city.buildings.join(', ')}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
