import { describe, expect, it } from "vitest";

import {
  buildBlankTiles,
  clipSpawnZones,
  resizeTiles,
  validateSavedMapDraft,
} from "@/lib/saved-map-helpers";

describe("buildBlankTiles", () => {
  it("emits width × height tiles in row-major order", () => {
    const tiles = buildBlankTiles(3, 2, "grass");
    expect(tiles).toHaveLength(6);
    expect(tiles.map((t) => `${t.x},${t.y}`)).toEqual([
      "0,0",
      "1,0",
      "2,0",
      "0,1",
      "1,1",
      "2,1",
    ]);
    expect(tiles.every((t) => t.terrain === "grass")).toBe(true);
    expect(tiles.every((t) => t.resource === null)).toBe(true);
  });
});

describe("resizeTiles", () => {
  it("preserves overlapping tiles and fills new ones", () => {
    const before = buildBlankTiles(2, 2, "grass");
    before[3] = { x: 1, y: 1, terrain: "water", resource: null };

    const after = resizeTiles(before, 2, 2, 3, 3, "desert");
    expect(after).toHaveLength(9);
    expect(after.find((t) => t.x === 1 && t.y === 1)?.terrain).toBe("water");
    expect(after.find((t) => t.x === 2 && t.y === 0)?.terrain).toBe("desert");
    expect(after.find((t) => t.x === 2 && t.y === 2)?.terrain).toBe("desert");
  });

  it("drops tiles outside the new bounds when shrinking", () => {
    const before = buildBlankTiles(3, 3, "grass");
    const after = resizeTiles(before, 3, 3, 2, 2);
    expect(after).toHaveLength(4);
    expect(after.every((t) => t.x < 2 && t.y < 2)).toBe(true);
  });
});

describe("clipSpawnZones", () => {
  it("removes zones outside new bounds", () => {
    const zones = [
      { x: 0, y: 0 },
      { x: 5, y: 5 },
      { x: 9, y: 9 },
    ];
    expect(clipSpawnZones(zones, 6, 6)).toEqual([
      { x: 0, y: 0 },
      { x: 5, y: 5 },
    ]);
  });
});

describe("validateSavedMapDraft", () => {
  function blank(width: number, height: number) {
    return buildBlankTiles(width, height, "grass");
  }

  it("flags an empty name", () => {
    const issues = validateSavedMapDraft({
      name: "",
      width: 10,
      height: 10,
      tiles: blank(10, 10),
      spawnZones: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
      ],
    });
    expect(issues.some((i) => i.field === "name")).toBe(true);
  });

  it("flags out-of-range dimensions", () => {
    const issues = validateSavedMapDraft({
      name: "ok",
      width: 5,
      height: 200,
      tiles: [],
      spawnZones: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
      ],
    });
    expect(issues.some((i) => i.field === "width")).toBe(true);
    expect(issues.some((i) => i.field === "height")).toBe(true);
  });

  it("requires at least 2 spawn zones", () => {
    const issues = validateSavedMapDraft({
      name: "ok",
      width: 10,
      height: 10,
      tiles: blank(10, 10),
      spawnZones: [{ x: 0, y: 0 }],
    });
    expect(issues.some((i) => i.field === "spawn_zones")).toBe(true);
  });

  it("flags spawn zones on impassable terrain", () => {
    const tiles = blank(10, 10);
    tiles[0] = { x: 0, y: 0, terrain: "water", resource: null };
    const issues = validateSavedMapDraft({
      name: "ok",
      width: 10,
      height: 10,
      tiles,
      spawnZones: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
      ],
    });
    expect(issues.some((i) => i.field === "spawn_zones")).toBe(true);
  });

  it("returns no issues for a valid draft", () => {
    const issues = validateSavedMapDraft({
      name: "Test map",
      width: 10,
      height: 10,
      tiles: blank(10, 10),
      spawnZones: [
        { x: 0, y: 0 },
        { x: 9, y: 9 },
      ],
    });
    expect(issues).toEqual([]);
  });
});
