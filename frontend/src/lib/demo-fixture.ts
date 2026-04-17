import type { GameState } from '@/types/game'

/**
 * Generates a static 20x20 game state fixture for demo/testing purposes.
 * Deterministic — always produces the same output.
 */
export function createDemoGameState(width = 20, height = 20): GameState {
  const players = ['player_alpha', 'player_beta', 'player_gamma', 'player_delta']

  // Deterministic terrain based on position
  function getTerrain(x: number, y: number) {
    // Create natural-looking terrain patterns
    const v = Math.sin(x * 0.3) * Math.cos(y * 0.4) + Math.sin((x + y) * 0.2)
    if (y === 0 || y === height - 1 || x === 0 || x === width - 1) return 'water'
    if (v > 0.8) return 'mountain'
    if (v > 0.2) return 'forest'
    if (v < -0.8) return 'water'
    return 'plains'
  }

  // Resources placed deterministically
  const resourceTypes = ['food', 'wood', 'ore', 'crystal'] as const
  function getResource(x: number, y: number, terrain: string): string | undefined {
    if (terrain === 'water') return undefined
    const hash = (x * 31 + y * 17) % 100
    if (hash < 8) return resourceTypes[hash % 4]
    return undefined
  }

  // Generate tiles
  const tiles: Record<string, unknown>[] = []
  let tileId = 0
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const terrain = getTerrain(x, y)
      const resource = getResource(x, y, terrain)
      const tile: Record<string, unknown> = {
        id: tileId++,
        loc: { x, y },
        terrain,
      }
      if (resource) tile.resource = resource
      tiles.push(tile)
    }
  }

  // Place cities with buildings
  const cityPositions = [
    { x: 3, y: 3, owner: players[0], buildings: ['granary', 'barracks'] },
    { x: 16, y: 3, owner: players[1], buildings: ['walls'] },
    { x: 3, y: 16, owner: players[2], buildings: ['granary'] },
    { x: 16, y: 16, owner: players[3], buildings: [] },
    { x: 10, y: 10, owner: players[0], buildings: ['granary', 'barracks', 'walls'] },
  ]

  const cities: Record<number, unknown> = {}
  cityPositions.forEach((cp, i) => {
    const cityId = i + 1
    cities[cityId] = {
      id: cityId,
      owner: cp.owner,
      loc: { x: cp.x, y: cp.y },
      hp: 10 + i * 2,
      buildings: cp.buildings,
    }
    // Mark tile as owned by city
    const tileIdx = cp.y * width + cp.x
    ;(tiles[tileIdx] as Record<string, unknown>).city_id = cityId
    ;(tiles[tileIdx] as Record<string, unknown>).owner = cp.owner
  })

  // Set territory ownership around cities
  for (const cp of cityPositions) {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) {
        const tx = cp.x + dx
        const ty = cp.y + dy
        if (tx < 0 || tx >= width || ty < 0 || ty >= height) continue
        if (Math.abs(dx) + Math.abs(dy) > 2) continue
        const tileIdx = ty * width + tx
        const t = tiles[tileIdx] as Record<string, unknown>
        if (!t.owner) t.owner = cp.owner
      }
    }
  }

  // Place units
  const unitDefs = [
    { type: 'scout', owner: players[0], x: 5, y: 5, hp: 2 },
    { type: 'soldier', owner: players[0], x: 4, y: 3, hp: 4 },
    { type: 'worker', owner: players[0], x: 3, y: 4, hp: 2 },
    { type: 'archer', owner: players[0], x: 9, y: 9, hp: 3 },

    { type: 'scout', owner: players[1], x: 14, y: 4, hp: 2 },
    { type: 'soldier', owner: players[1], x: 15, y: 3, hp: 4 },
    { type: 'soldier', owner: players[1], x: 17, y: 3, hp: 3 },
    { type: 'archer', owner: players[1], x: 16, y: 5, hp: 3 },

    { type: 'scout', owner: players[2], x: 4, y: 15, hp: 2 },
    { type: 'worker', owner: players[2], x: 3, y: 17, hp: 2 },
    { type: 'soldier', owner: players[2], x: 5, y: 16, hp: 4 },

    { type: 'scout', owner: players[3], x: 15, y: 15, hp: 2 },
    { type: 'archer', owner: players[3], x: 17, y: 17, hp: 3 },
    { type: 'worker', owner: players[3], x: 16, y: 17, hp: 2 },
  ]

  const units: Record<number, unknown> = {}
  unitDefs.forEach((ud, i) => {
    const unitId = i + 1
    units[unitId] = {
      id: unitId,
      owner: ud.owner,
      type: ud.type,
      hp: ud.hp,
      moves_left: 2,
      loc: { x: ud.x, y: ud.y },
    }
    const tileIdx = ud.y * width + ud.x
    ;(tiles[tileIdx] as Record<string, unknown>).unit_id = unitId
  })

  // Place some improvements
  const improvements = [
    { x: 4, y: 2, type: 'farm' },
    { x: 2, y: 3, type: 'farm' },
    { x: 15, y: 2, type: 'mine' },
    { x: 17, y: 4, type: 'crystal_extractor' },
    { x: 4, y: 17, type: 'farm' },
    { x: 15, y: 17, type: 'mine' },
  ]
  for (const imp of improvements) {
    const tileIdx = imp.y * width + imp.x
    ;(tiles[tileIdx] as Record<string, unknown>).improvement = imp.type
  }

  return {
    turn: 12,
    rng_state: 42,
    map_width: width,
    map_height: height,
    tiles,
    units,
    cities,
    players,
    diplomacy: {
      'player_alpha:player_beta': 'war',
      'player_alpha:player_gamma': 'peace',
      'player_alpha:player_delta': 'peace',
      'player_beta:player_gamma': 'peace',
      'player_beta:player_delta': 'alliance',
      'player_gamma:player_delta': 'war',
    },
    stockpiles: {
      player_alpha: { food: 150, wood: 80, ore: 40, crystal: 10 },
      player_beta: { food: 120, wood: 100, ore: 60, crystal: 5 },
      player_gamma: { food: 90, wood: 60, ore: 30, crystal: 20 },
      player_delta: { food: 110, wood: 70, ore: 50, crystal: 15 },
    },
    next_unit_id: unitDefs.length + 1,
    next_city_id: cityPositions.length + 1,
    max_turns: 100,
  } as unknown as GameState
}
