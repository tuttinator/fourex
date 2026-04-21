'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import type { MapCanvasProps, Tile } from '@/types/game'
import { TERRAIN_COLORS, PLAYER_COLORS } from '@/types/game'
import { Application, Container, Graphics, Sprite, Text } from 'pixi.js'
import {
  cityVariantFor,
  loadSpriteAtlas,
  type SpriteAtlas,
} from '@/lib/sprite-atlas'

const TILE_SIZE = 32
const RESOURCE_SPRITE_SIZE = 14
const IMPROVEMENT_SPRITE_SIZE = 20
const CITY_SPRITE_SIZE = 32
const BUILDING_INDICATOR_SIZE = 10
const STACK_BADGE_RADIUS = 7

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
  movePathsByTile,
  attackTiles,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const appRef = useRef<Application | null>(null)
  const worldRef = useRef<Container | null>(null)
  const atlasRef = useRef<SpriteAtlas | null>(null)
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

      try {
        atlasRef.current = await loadSpriteAtlas()
      } catch (error) {
        if (!disposed) {
          console.error('Failed to load sprite atlas', error)
        }
      }

      if (disposed) {
        destroyApp()
        return
      }

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

    // Terrain layer — unexplored fog stays as Graphics (no sprite), but
    // every explored tile renders as a sprite from the atlas so the map
    // reads as art rather than a diagram (Phase 1).
    const atlas = atlasRef.current

    if (fogOfWarEnabled) {
      const fogGfx = new Graphics()
      for (let gy = 0; gy < map_height; gy++) {
        for (let gx = 0; gx < map_width; gx++) {
          if (!tileLookup.has(`${gx},${gy}`)) {
            fogGfx.rect(gx * TILE_SIZE, gy * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            fogGfx.fill(0x0a0a14)
          }
        }
      }
      world.addChild(fogGfx)
    }

    for (const tile of tiles) {
      const x = tile.loc.x * TILE_SIZE
      const y = tile.loc.y * TILE_SIZE
      const texture = atlas?.terrain[tile.terrain]

      if (texture) {
        const sprite = new Sprite(texture)
        sprite.x = x
        sprite.y = y
        sprite.width = TILE_SIZE
        sprite.height = TILE_SIZE
        world.addChild(sprite)
      } else {
        // Fallback while the atlas is still loading — keeps the map
        // readable on the first paint instead of flashing empty tiles.
        const fallback = new Graphics()
        fallback.rect(x, y, TILE_SIZE, TILE_SIZE)
        fallback.fill(hexToNumber(TERRAIN_COLORS[tile.terrain]))
        world.addChild(fallback)
      }
    }

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

    // Resource indicators — rendered as sprites from the atlas, anchored
    // to the top-right corner of the tile (Phase 1).
    for (const tile of tiles) {
      if (!tile.resource) continue
      const texture = atlas?.resource[tile.resource]
      if (!texture) continue
      const sprite = new Sprite(texture)
      sprite.width = RESOURCE_SPRITE_SIZE
      sprite.height = RESOURCE_SPRITE_SIZE
      sprite.x = tile.loc.x * TILE_SIZE + TILE_SIZE - RESOURCE_SPRITE_SIZE - 1
      sprite.y = tile.loc.y * TILE_SIZE + 1
      world.addChild(sprite)
    }

    // Improvements — sprite per tile, bottom-left anchored (Phase 2).
    for (const tile of tiles) {
      if (!tile.improvement) continue
      const texture = atlas?.improvement[tile.improvement]
      if (!texture) continue
      const sprite = new Sprite(texture)
      sprite.width = IMPROVEMENT_SPRITE_SIZE
      sprite.height = IMPROVEMENT_SPRITE_SIZE
      sprite.x = tile.loc.x * TILE_SIZE + 1
      sprite.y = tile.loc.y * TILE_SIZE + TILE_SIZE - IMPROVEMENT_SPRITE_SIZE - 1
      world.addChild(sprite)
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

    // Cities — variant sprite + player-coloured banner overlay + per-building
    // indicator sprites arranged around the tile (Phase 2).
    for (const city of Object.values(cities)) {
      const tileX = city.loc.x * TILE_SIZE
      const tileY = city.loc.y * TILE_SIZE
      const cx = tileX + TILE_SIZE / 2
      const cy = tileY + TILE_SIZE / 2
      const playerIndex = players.indexOf(city.owner)
      const playerColour = hexToNumber(PLAYER_COLORS[playerIndex] ?? '#666666')
      const variant = cityVariantFor(city.buildings)

      const cityTexture = atlas?.city[variant]
      if (cityTexture) {
        const sprite = new Sprite(cityTexture)
        sprite.width = CITY_SPRITE_SIZE
        sprite.height = CITY_SPRITE_SIZE
        sprite.x = tileX
        sprite.y = tileY
        world.addChild(sprite)
      } else {
        // Atlas still loading — keep tile readable with a coloured disc.
        const fallback = new Graphics()
        fallback.circle(cx, cy, 12)
        fallback.fill(playerColour)
        world.addChild(fallback)
      }

      // Player-colour banner overlay (tinted white frame).
      if (atlas?.overlay.cityBanner) {
        const banner = new Sprite(atlas.overlay.cityBanner)
        banner.width = TILE_SIZE
        banner.height = TILE_SIZE
        banner.x = tileX
        banner.y = tileY
        banner.tint = playerColour
        world.addChild(banner)
      }

      // Per-building indicator sprites arranged in a ring around the city.
      if (city.buildings.length > 0 && atlas) {
        city.buildings.forEach((b, i) => {
          const texture = atlas.building[b]
          if (!texture) return
          const angle =
            (i * 2 * Math.PI) / Math.max(city.buildings.length, 3) - Math.PI / 2
          const bx = cx + Math.cos(angle) * 14 - BUILDING_INDICATOR_SIZE / 2
          const by = cy + Math.sin(angle) * 14 - BUILDING_INDICATOR_SIZE / 2
          const sprite = new Sprite(texture)
          sprite.width = BUILDING_INDICATOR_SIZE
          sprite.height = BUILDING_INDICATOR_SIZE
          sprite.x = bx
          sprite.y = by
          world.addChild(sprite)
        })
      }
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

    // Hovered-destination path preview (Phase 2 gameplay-improvements).
    // Draws the server-computed chain of tiles from the selected unit's
    // current location to the hovered reachable tile so the player can
    // verify the route before committing.
    if (hover && movePathsByTile) {
      const hoverKey = `${hover.tile.loc.x},${hover.tile.loc.y}`
      const path = movePathsByTile[hoverKey]
      if (path && path.length > 0) {
        const pathGfx = new Graphics()
        for (const step of path) {
          const px = step.x * TILE_SIZE
          const py = step.y * TILE_SIZE
          pathGfx.setStrokeStyle({ width: 3, color: 0xf59e0b, alpha: 1 })
          pathGfx.rect(px + 3, py + 3, TILE_SIZE - 6, TILE_SIZE - 6)
          pathGfx.stroke()
        }
        world.addChild(pathGfx)
      }
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

    // Units — per-type sprite with a tinted player-colour banner overlay
    // underneath (Phase 2). The base sprite is distinct per unit type so
    // silhouette reads at a glance; the banner provides the player-colour
    // cue that survives on contested / shared tiles.
    for (const unit of Object.values(units)) {
      const ux = unit.loc.x * TILE_SIZE
      const uy = unit.loc.y * TILE_SIZE
      const playerIndex = players.indexOf(unit.owner)
      const playerColour = hexToNumber(PLAYER_COLORS[playerIndex] ?? '#666666')

      if (atlas?.overlay.unitBanner) {
        const banner = new Sprite(atlas.overlay.unitBanner)
        banner.width = TILE_SIZE
        banner.height = TILE_SIZE
        banner.x = ux
        banner.y = uy
        banner.tint = playerColour
        world.addChild(banner)
      }

      const unitTexture = atlas?.unit[unit.type]
      if (unitTexture) {
        const sprite = new Sprite(unitTexture)
        sprite.width = TILE_SIZE
        sprite.height = TILE_SIZE
        sprite.x = ux
        sprite.y = uy
        world.addChild(sprite)
      } else {
        // Atlas still loading — keep the tile readable with a fallback.
        const fallback = new Graphics()
        fallback.roundRect(ux + 5, uy + 5, TILE_SIZE - 10, TILE_SIZE - 10, 3)
        fallback.fill(playerColour)
        world.addChild(fallback)
      }

      if (selectedUnitId != null && unit.id === selectedUnitId) {
        const ring = new Graphics()
        ring.setStrokeStyle({ width: 2.5, color: 0xfbbf24, alpha: 1 })
        ring.roundRect(ux + 3, uy + 3, TILE_SIZE - 6, TILE_SIZE - 6, 4)
        ring.stroke()
        world.addChild(ring)
      }
    }

    // Stack-count badge (Phase 4 gameplay-improvements). Rendered above
    // the unit sprites so the badge reads cleanly on any terrain. Shown
    // whenever the visible stack on a tile holds 2+ units — owner-agnostic
    // so enemy stacks also surface a tactical cue at a glance.
    for (const tile of tiles) {
      const count = tile.unit_ids?.length ?? 0
      if (count < 2) continue
      const badgeCx = tile.loc.x * TILE_SIZE + STACK_BADGE_RADIUS + 1
      const badgeCy = tile.loc.y * TILE_SIZE + STACK_BADGE_RADIUS + 1
      const badge = new Graphics()
      badge.circle(badgeCx, badgeCy, STACK_BADGE_RADIUS)
      badge.fill({ color: 0x111827, alpha: 0.9 })
      badge.setStrokeStyle({ width: 1, color: 0xfbbf24, alpha: 1 })
      badge.circle(badgeCx, badgeCy, STACK_BADGE_RADIUS)
      badge.stroke()
      world.addChild(badge)

      const label = new Text({
        text: String(count),
        style: {
          fontFamily: 'sans-serif',
          fontSize: 10,
          fontWeight: 'bold',
          fill: 0xfbbf24,
          align: 'center',
        },
      })
      label.anchor.set(0.5)
      label.x = badgeCx
      label.y = badgeCy
      world.addChild(label)
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

      const topUnitId = tile.unit_ids?.[tile.unit_ids.length - 1]
      if (topUnitId !== undefined && units[topUnitId]) {
        const u = units[topUnitId]
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

      onTileClick?.(tile, { x: e.global.x, y: e.global.y })
      const clickedUnitId = tile.unit_ids?.[tile.unit_ids.length - 1]
      if (clickedUnitId !== undefined && units[clickedUnitId]) onUnitClick?.(units[clickedUnitId])
      if (tile.city_id && cities[tile.city_id]) onCityClick?.(cities[tile.city_id])
    })

    world.addChild(interactiveLayer)
  }, [gameState, selectedPlayer, fogOfWarEnabled, onTileClick, onUnitClick, onCityClick, pixiReady, selectedUnitId, selectedCityId, highlightedTiles, movePathsByTile, attackTiles, hover])

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
