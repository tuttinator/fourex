import { Assets, type Texture } from 'pixi.js'

import type { Resource, Terrain } from '@/types/game'

const TERRAIN_SPRITE_URLS: Record<Terrain, string> = {
  plains: '/sprites/terrain-plains.svg',
  forest: '/sprites/terrain-forest.svg',
  mountain: '/sprites/terrain-mountain.svg',
  water: '/sprites/terrain-water.svg',
}

const RESOURCE_SPRITE_URLS: Record<Resource, string> = {
  food: '/sprites/resource-food.svg',
  wood: '/sprites/resource-wood.svg',
  ore: '/sprites/resource-ore.svg',
  crystal: '/sprites/resource-crystal.svg',
}

export interface SpriteAtlas {
  terrain: Record<Terrain, Texture>
  resource: Record<Resource, Texture>
}

let cached: Promise<SpriteAtlas> | null = null

export function loadSpriteAtlas(): Promise<SpriteAtlas> {
  if (!cached) {
    cached = (async () => {
      const urls = [
        ...Object.values(TERRAIN_SPRITE_URLS),
        ...Object.values(RESOURCE_SPRITE_URLS),
      ]
      const loaded = (await Assets.load(urls)) as Record<string, Texture>

      const terrain = {} as Record<Terrain, Texture>
      for (const [key, url] of Object.entries(TERRAIN_SPRITE_URLS) as [
        Terrain,
        string,
      ][]) {
        terrain[key] = loaded[url]
      }

      const resource = {} as Record<Resource, Texture>
      for (const [key, url] of Object.entries(RESOURCE_SPRITE_URLS) as [
        Resource,
        string,
      ][]) {
        resource[key] = loaded[url]
      }

      return { terrain, resource }
    })()
  }
  return cached
}

export function resetSpriteAtlasCacheForTests(): void {
  cached = null
}

export const SPRITE_ATLAS_URLS = {
  terrain: TERRAIN_SPRITE_URLS,
  resource: RESOURCE_SPRITE_URLS,
} as const
