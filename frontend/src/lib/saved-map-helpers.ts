/**
 * Pure helpers for the Phase 5 map builder UI. Live in /lib so they can
 * be unit-tested without spinning up the canvas-based editor component.
 */
import type { SavedMapSpawnZone, SavedMapTile, Terrain } from "@/types/game";

export const TERRAIN_BRUSHES: Terrain[] = [
  "grass",
  "forest",
  "hills",
  "mountain",
  "desert",
  "swamp",
  "water",
];

export const TERRAIN_LABELS: Record<Terrain, string> = {
  grass: "Grass",
  forest: "Forest",
  hills: "Hills",
  mountain: "Mountain",
  desert: "Desert",
  swamp: "Swamp",
  water: "Water",
};

/** Mirrors the backend's `_SPAWN_ELIGIBLE_TERRAINS` (passable + city-eligible).
 * Duplicated client-side so the editor can flag invalid spawn placements
 * inline without a round-trip; the server is still the source of truth and
 * re-validates on save. */
export const SPAWN_ELIGIBLE_TERRAINS: ReadonlySet<Terrain> = new Set<Terrain>([
  "grass",
  "forest",
  "hills",
  "desert",
]);

/** Terrains that cannot carry a resource — backend rejects on save. */
export const RESOURCE_FORBIDDEN_TERRAINS: ReadonlySet<Terrain> = new Set<Terrain>([
  "mountain",
  "water",
]);

export const SAVED_MAP_DIM_MIN = 10;
export const SAVED_MAP_DIM_MAX = 100;

/** Build a width × height tile grid filled with `terrain`. Tiles are
 * row-major (y outer, x inner) so callers can serialise to the backend
 * without reshuffling. */
export function buildBlankTiles(
  width: number,
  height: number,
  terrain: Terrain = "grass",
): SavedMapTile[] {
  const tiles: SavedMapTile[] = [];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      tiles.push({ x, y, terrain, resource: null });
    }
  }
  return tiles;
}

/** Resize an existing tile grid to (newWidth, newHeight). Tiles in the
 * preserved overlap keep their terrain + resource; new tiles default to
 * `fillTerrain`. Resize is destructive — tiles outside the new bounds
 * are dropped. */
export function resizeTiles(
  tiles: readonly SavedMapTile[],
  oldWidth: number,
  oldHeight: number,
  newWidth: number,
  newHeight: number,
  fillTerrain: Terrain = "grass",
): SavedMapTile[] {
  const byKey = new Map<string, SavedMapTile>();
  for (const t of tiles) {
    byKey.set(`${t.x},${t.y}`, t);
  }
  const next: SavedMapTile[] = [];
  for (let y = 0; y < newHeight; y++) {
    for (let x = 0; x < newWidth; x++) {
      const existing = byKey.get(`${x},${y}`);
      if (existing && x < oldWidth && y < oldHeight) {
        next.push(existing);
      } else {
        next.push({ x, y, terrain: fillTerrain, resource: null });
      }
    }
  }
  return next;
}

/** Drop spawn zones that fall outside the new bounds. Used after a
 * destructive resize. */
export function clipSpawnZones(
  zones: readonly SavedMapSpawnZone[],
  width: number,
  height: number,
): SavedMapSpawnZone[] {
  return zones.filter((z) => z.x >= 0 && z.x < width && z.y >= 0 && z.y < height);
}

export function tileIndex(x: number, y: number, width: number): number {
  return y * width + x;
}

export interface ValidationIssue {
  field:
    | "name"
    | "width"
    | "height"
    | "spawn_zones"
    | "tiles"
    | "general";
  message: string;
}

/** Mirror of the backend's saved-map validation, run client-side so the
 * editor can surface errors before a save round-trip. The server still
 * re-validates on save (single source of truth); this is purely an
 * editor-side affordance. */
export function validateSavedMapDraft(draft: {
  name: string;
  width: number;
  height: number;
  tiles: readonly SavedMapTile[];
  spawnZones: readonly SavedMapSpawnZone[];
}): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  if (!draft.name.trim()) {
    issues.push({ field: "name", message: "Name is required." });
  } else if (draft.name.length > 120) {
    issues.push({ field: "name", message: "Name must be ≤ 120 characters." });
  }
  if (
    draft.width < SAVED_MAP_DIM_MIN ||
    draft.width > SAVED_MAP_DIM_MAX
  ) {
    issues.push({
      field: "width",
      message: `Width must be between ${SAVED_MAP_DIM_MIN} and ${SAVED_MAP_DIM_MAX}.`,
    });
  }
  if (
    draft.height < SAVED_MAP_DIM_MIN ||
    draft.height > SAVED_MAP_DIM_MAX
  ) {
    issues.push({
      field: "height",
      message: `Height must be between ${SAVED_MAP_DIM_MIN} and ${SAVED_MAP_DIM_MAX}.`,
    });
  }
  if (draft.spawnZones.length < 2) {
    issues.push({
      field: "spawn_zones",
      message: "At least 2 spawn zones are required.",
    });
  }
  const byLoc = new Map<string, SavedMapTile>();
  for (const t of draft.tiles) {
    byLoc.set(`${t.x},${t.y}`, t);
  }
  for (const z of draft.spawnZones) {
    const t = byLoc.get(`${z.x},${z.y}`);
    if (!t) {
      issues.push({
        field: "spawn_zones",
        message: `Spawn zone (${z.x},${z.y}) has no matching tile.`,
      });
      continue;
    }
    if (!SPAWN_ELIGIBLE_TERRAINS.has(t.terrain as Terrain)) {
      issues.push({
        field: "spawn_zones",
        message: `Spawn zone (${z.x},${z.y}) is on ${t.terrain} — must be on grass, forest, hills, or desert.`,
      });
    }
  }
  return issues;
}
