import { Assets, type Texture } from 'pixi.js'

import type {
  BuildingType,
  ImprovementType,
  Resource,
  Terrain,
  UnitType,
} from '@/types/game'

// PNG tiles for the new biome-aware terrain set. The PNG art lives under
// /sprites/tile-*.png; the legacy SVG terrain sprites are no longer used.
const TERRAIN_SPRITE_URLS: Record<Terrain, string> = {
  grass: '/sprites/tile-grass.png',
  forest: '/sprites/tile-forest.png',
  hills: '/sprites/tile-hills.png',
  mountain: '/sprites/tile-mountain.png',
  desert: '/sprites/tile-desert.png',
  swamp: '/sprites/tile-swamp.png',
  water: '/sprites/tile-water.png',
}

const RESOURCE_SPRITE_URLS: Record<Resource, string> = {
  food: '/sprites/resource-food.svg',
  wood: '/sprites/resource-wood.svg',
  ore: '/sprites/resource-ore.svg',
  crystal: '/sprites/resource-crystal.svg',
  // Science is a synthetic resource produced by cities; it never appears
  // on a tile so this entry exists only to keep the `Record<Resource,...>`
  // type exhaustive. Rendering code gates on `tile.resource` so this is
  // never actually loaded.
  science: '/sprites/resource-crystal.svg',
}

const UNIT_SPRITE_URLS: Record<UnitType, string> = {
  scout: '/sprites/unit-scout.svg',
  worker: '/sprites/unit-worker.svg',
  soldier: '/sprites/unit-soldier.svg',
  archer: '/sprites/unit-archer.svg',
}

const BUILDING_SPRITE_URLS: Record<BuildingType, string> = {
  granary: '/sprites/building-granary.svg',
  barracks: '/sprites/building-barracks.svg',
  walls: '/sprites/building-walls.svg',
  monument: '/sprites/building-monument.svg',
  library: '/sprites/building-library.svg',
  temple: '/sprites/building-temple.svg',
}

const IMPROVEMENT_SPRITE_URLS: Record<ImprovementType, string> = {
  farm: '/sprites/improvement-farm.svg',
  mine: '/sprites/improvement-mine.svg',
  lumber_mill: '/sprites/improvement-lumber-mill.svg',
  crystal_extractor: '/sprites/improvement-crystal-extractor.svg',
}

// City sprite variants. The resolver below picks one per city based on
// its buildings list (walls → fortress; ≥2 buildings → town; else outpost).
export type CityVariant = 'outpost' | 'town' | 'fortress'

const CITY_VARIANT_SPRITE_URLS: Record<CityVariant, string> = {
  outpost: '/sprites/city-outpost.svg',
  town: '/sprites/city-town.svg',
  fortress: '/sprites/city-fortress.svg',
}

// Player-colour overlay frames — drawn pure white so Pixi.tint multiplies
// the player colour cleanly without bleed.
const OVERLAY_SPRITE_URLS = {
  unitBanner: '/sprites/unit-banner.svg',
  cityBanner: '/sprites/city-banner.svg',
} as const

export interface SpriteAtlas {
  terrain: Record<Terrain, Texture>
  resource: Record<Resource, Texture>
  unit: Record<UnitType, Texture>
  building: Record<BuildingType, Texture>
  improvement: Record<ImprovementType, Texture>
  city: Record<CityVariant, Texture>
  overlay: { unitBanner: Texture; cityBanner: Texture }
}

let cached: Promise<SpriteAtlas> | null = null

export function loadSpriteAtlas(): Promise<SpriteAtlas> {
  if (!cached) {
    cached = (async () => {
      const urls = [
        ...Object.values(TERRAIN_SPRITE_URLS),
        ...Object.values(RESOURCE_SPRITE_URLS),
        ...Object.values(UNIT_SPRITE_URLS),
        ...Object.values(BUILDING_SPRITE_URLS),
        ...Object.values(IMPROVEMENT_SPRITE_URLS),
        ...Object.values(CITY_VARIANT_SPRITE_URLS),
        ...Object.values(OVERLAY_SPRITE_URLS),
      ]
      const loaded = (await Assets.load(urls)) as Record<string, Texture>

      const mapToTextures = <K extends string>(
        urlMap: Record<K, string>,
      ): Record<K, Texture> => {
        const out = {} as Record<K, Texture>
        for (const [key, url] of Object.entries(urlMap) as [K, string][]) {
          out[key] = loaded[url]
        }
        return out
      }

      return {
        terrain: mapToTextures(TERRAIN_SPRITE_URLS),
        resource: mapToTextures(RESOURCE_SPRITE_URLS),
        unit: mapToTextures(UNIT_SPRITE_URLS),
        building: mapToTextures(BUILDING_SPRITE_URLS),
        improvement: mapToTextures(IMPROVEMENT_SPRITE_URLS),
        city: mapToTextures(CITY_VARIANT_SPRITE_URLS),
        overlay: {
          unitBanner: loaded[OVERLAY_SPRITE_URLS.unitBanner],
          cityBanner: loaded[OVERLAY_SPRITE_URLS.cityBanner],
        },
      }
    })()
  }
  return cached
}

export function resetSpriteAtlasCacheForTests(): void {
  cached = null
}

// City-variant selector. Pure data lookup; callers stay ignorant of the
// variant-selection policy.
export function cityVariantFor(buildings: readonly BuildingType[]): CityVariant {
  if (buildings.includes('walls')) return 'fortress'
  if (buildings.length >= 2) return 'town'
  return 'outpost'
}

export const SPRITE_ATLAS_URLS = {
  terrain: TERRAIN_SPRITE_URLS,
  resource: RESOURCE_SPRITE_URLS,
  unit: UNIT_SPRITE_URLS,
  building: BUILDING_SPRITE_URLS,
  improvement: IMPROVEMENT_SPRITE_URLS,
  city: CITY_VARIANT_SPRITE_URLS,
  overlay: OVERLAY_SPRITE_URLS,
} as const
