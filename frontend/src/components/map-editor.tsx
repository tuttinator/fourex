/**
 * Phase 5 (map system overhaul): admin-facing saved-map authoring UI.
 *
 * Renders a paintable canvas grid with a tools palette (one brush per
 * terrain, a spawn-zone marker, an eraser) and a sidebar form for
 * metadata + dimensions. Click and click-drag both apply the active
 * tool. Spawn zones render as a coloured pin overlay above terrain
 * fills so they remain visible while the admin paints underneath.
 *
 * Save round-trips through `api.createSavedMap` / `api.updateSavedMap`
 * (Phase 4 endpoints); validation errors come back as 400s with
 * field-specific detail strings, surfaced inline.
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { api, ApiError } from "@/lib/api";
import {
  RESOURCE_FORBIDDEN_TERRAINS,
  SAVED_MAP_DIM_MAX,
  SAVED_MAP_DIM_MIN,
  SPAWN_ELIGIBLE_TERRAINS,
  TERRAIN_BRUSHES,
  TERRAIN_LABELS,
  buildBlankTiles,
  clipSpawnZones,
  resizeTiles,
  tileIndex,
  validateSavedMapDraft,
} from "@/lib/saved-map-helpers";
import {
  TERRAIN_COLORS,
  type SavedMap,
  type SavedMapSpawnZone,
  type SavedMapTile,
  type Terrain,
} from "@/types/game";

type Tool =
  | { kind: "terrain"; terrain: Terrain }
  | { kind: "spawn" }
  | { kind: "eraser" };

interface MapEditorProps {
  /** Existing saved map for edit mode; absent for /maps/new. */
  initial?: SavedMap;
}

const SPAWN_PIN_COLOR = "#ef4444";
const SPAWN_PIN_BORDER = "#f8fafc";
const GRID_LINE_COLOR = "rgba(15, 23, 42, 0.18)";
const HOVER_OUTLINE_COLOR = "rgba(15, 23, 42, 0.55)";

const MIN_TILE_PX = 10;
const MAX_TILE_PX = 32;
const DEFAULT_DIM = 24;

function clampDim(value: number): number {
  if (Number.isNaN(value)) return SAVED_MAP_DIM_MIN;
  return Math.max(SAVED_MAP_DIM_MIN, Math.min(SAVED_MAP_DIM_MAX, value));
}

export function MapEditor({ initial }: MapEditorProps) {
  const router = useRouter();
  const { toast } = useToast();

  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [width, setWidth] = useState<number>(initial?.width ?? DEFAULT_DIM);
  const [height, setHeight] = useState<number>(initial?.height ?? DEFAULT_DIM);
  const [tiles, setTiles] = useState<SavedMapTile[]>(
    () => initial?.tiles ?? buildBlankTiles(DEFAULT_DIM, DEFAULT_DIM, "grass"),
  );
  const [spawnZones, setSpawnZones] = useState<SavedMapSpawnZone[]>(
    () => initial?.spawn_zones ?? [],
  );
  const [tool, setTool] = useState<Tool>({ kind: "terrain", terrain: "grass" });
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isPaintingRef = useRef(false);
  const lastPaintedRef = useRef<string | null>(null);

  const tilePx = useMemo(() => {
    // Fit the canvas inside ~720px on the long side; clamp to a usable
    // pixel range so 100×100 stays clickable and 10×10 doesn't fill the
    // entire viewport.
    const longest = Math.max(width, height);
    const target = Math.floor(720 / longest);
    return Math.max(MIN_TILE_PX, Math.min(MAX_TILE_PX, target));
  }, [width, height]);

  const canvasWidth = width * tilePx;
  const canvasHeight = height * tilePx;

  const issues = useMemo(
    () =>
      validateSavedMapDraft({
        name,
        width,
        height,
        tiles,
        spawnZones,
      }),
    [name, width, height, tiles, spawnZones],
  );

  const issueByField = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const issue of issues) {
      (map[issue.field] ??= []).push(issue.message);
    }
    return map;
  }, [issues]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const t of tiles) {
      const fill = TERRAIN_COLORS[t.terrain as Terrain] ?? "#cccccc";
      ctx.fillStyle = fill;
      ctx.fillRect(t.x * tilePx, t.y * tilePx, tilePx, tilePx);
      if (t.resource) {
        // Small white dot on tiles that carry a resource so authors can
        // see where parametric-template seeded resources still are.
        ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
        ctx.beginPath();
        ctx.arc(
          t.x * tilePx + tilePx / 2,
          t.y * tilePx + tilePx / 2,
          Math.max(2, tilePx / 6),
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
    }

    if (tilePx >= 12) {
      ctx.strokeStyle = GRID_LINE_COLOR;
      ctx.lineWidth = 1;
      for (let x = 0; x <= width; x++) {
        ctx.beginPath();
        ctx.moveTo(x * tilePx + 0.5, 0);
        ctx.lineTo(x * tilePx + 0.5, canvasHeight);
        ctx.stroke();
      }
      for (let y = 0; y <= height; y++) {
        ctx.beginPath();
        ctx.moveTo(0, y * tilePx + 0.5);
        ctx.lineTo(canvasWidth, y * tilePx + 0.5);
        ctx.stroke();
      }
    }

    // Spawn zones — coloured pin overlay above terrain.
    for (const z of spawnZones) {
      const cx = z.x * tilePx + tilePx / 2;
      const cy = z.y * tilePx + tilePx / 2;
      const r = Math.max(3, tilePx / 2.6);
      ctx.fillStyle = SPAWN_PIN_COLOR;
      ctx.strokeStyle = SPAWN_PIN_BORDER;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }

    if (hover) {
      ctx.strokeStyle = HOVER_OUTLINE_COLOR;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        hover.x * tilePx + 1,
        hover.y * tilePx + 1,
        tilePx - 2,
        tilePx - 2,
      );
    }
  }, [
    tiles,
    spawnZones,
    hover,
    tilePx,
    width,
    height,
    canvasWidth,
    canvasHeight,
  ]);

  useEffect(() => {
    draw();
  }, [draw]);

  const applyTool = useCallback(
    (x: number, y: number, currentTool: Tool) => {
      const key = `${x},${y}`;
      if (lastPaintedRef.current === key && currentTool.kind !== "spawn") {
        // Don't repaint the same tile during a single drag (spawn toggles
        // are click-driven, not drag-driven).
        return;
      }
      lastPaintedRef.current = key;

      if (currentTool.kind === "terrain") {
        setTiles((prev) => {
          const idx = tileIndex(x, y, width);
          if (idx < 0 || idx >= prev.length) return prev;
          const t = prev[idx];
          if (t.terrain === currentTool.terrain && !t.resource) return prev;
          const next = prev.slice();
          // Re-painted terrain may now forbid the existing resource — drop
          // it to keep the row valid against the backend's invariant.
          const resource = RESOURCE_FORBIDDEN_TERRAINS.has(currentTool.terrain)
            ? null
            : t.resource ?? null;
          next[idx] = {
            ...t,
            terrain: currentTool.terrain,
            resource,
          };
          return next;
        });
        // If the new terrain is no longer spawn-eligible, drop any spawn
        // zone on this tile so the editor doesn't leak invalid state.
        if (!SPAWN_ELIGIBLE_TERRAINS.has(currentTool.terrain)) {
          setSpawnZones((prev) =>
            prev.filter((z) => !(z.x === x && z.y === y)),
          );
        }
        return;
      }

      if (currentTool.kind === "spawn") {
        setSpawnZones((prev) => {
          const exists = prev.some((z) => z.x === x && z.y === y);
          if (exists) {
            return prev.filter((z) => !(z.x === x && z.y === y));
          }
          return [...prev, { x, y }];
        });
        return;
      }

      // Eraser: clear resource on the tile and any spawn pin sitting on it.
      setTiles((prev) => {
        const idx = tileIndex(x, y, width);
        if (idx < 0 || idx >= prev.length) return prev;
        const t = prev[idx];
        if (!t.resource) return prev;
        const next = prev.slice();
        next[idx] = { ...t, resource: null };
        return next;
      });
      setSpawnZones((prev) => prev.filter((z) => !(z.x === x && z.y === y)));
    },
    [width],
  );

  const tileFromEvent = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>): { x: number; y: number } | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const x = Math.floor(px / tilePx);
      const y = Math.floor(py / tilePx);
      if (x < 0 || x >= width || y < 0 || y >= height) return null;
      return { x, y };
    },
    [tilePx, width, height],
  );

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      const target = tileFromEvent(event);
      if (!target) return;
      isPaintingRef.current = true;
      lastPaintedRef.current = null;
      // Capture so pointermove keeps firing even if the cursor leaves
      // the canvas — the same convention used by tile.x stops dragging
      // off-grid from "sticking".
      event.currentTarget.setPointerCapture(event.pointerId);
      applyTool(target.x, target.y, tool);
    },
    [tileFromEvent, applyTool, tool],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      const target = tileFromEvent(event);
      setHover(target);
      if (!target || !isPaintingRef.current) return;
      // Spawn-toggle is click-only; dragging across tiles with the spawn
      // tool only adds (never removes) so a drag doesn't immediately undo
      // its own work.
      if (tool.kind === "spawn") {
        setSpawnZones((prev) => {
          if (prev.some((z) => z.x === target.x && z.y === target.y)) {
            return prev;
          }
          return [...prev, { x: target.x, y: target.y }];
        });
        return;
      }
      applyTool(target.x, target.y, tool);
    },
    [tileFromEvent, applyTool, tool],
  );

  const handlePointerUp = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      isPaintingRef.current = false;
      lastPaintedRef.current = null;
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        // releasePointerCapture throws if the id was never captured —
        // safe to ignore.
      }
    },
    [],
  );

  const handlePointerLeave = useCallback(() => {
    setHover(null);
  }, []);

  const handleResize = useCallback(
    (newWidth: number, newHeight: number) => {
      const w = clampDim(newWidth);
      const h = clampDim(newHeight);
      if (w === width && h === height) return;
      // Confirm before destroying tile data outside the new bounds.
      const wouldClip = w < width || h < height;
      if (wouldClip) {
        const ok = window.confirm(
          "Resizing smaller will discard tiles outside the new bounds. Continue?",
        );
        if (!ok) return;
      }
      setTiles((prev) => resizeTiles(prev, width, height, w, h));
      setSpawnZones((prev) => clipSpawnZones(prev, w, h));
      setWidth(w);
      setHeight(h);
    },
    [width, height],
  );

  const handleFillAll = useCallback(
    (terrain: Terrain) => {
      setTiles(buildBlankTiles(width, height, terrain));
      if (!SPAWN_ELIGIBLE_TERRAINS.has(terrain)) {
        setSpawnZones([]);
      }
    },
    [width, height],
  );

  const handleSave = useCallback(async () => {
    if (issues.length > 0) {
      toast({
        title: "Cannot save",
        description: issues[0].message,
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    setServerError(null);
    try {
      const payload = {
        name: name.trim(),
        description: description?.trim() ? description.trim() : null,
        width,
        height,
        tiles,
        spawn_zones: spawnZones,
      };
      if (initial) {
        await api.updateSavedMap(initial.id, payload);
        toast({ title: "Map updated" });
      } else {
        await api.createSavedMap(payload);
        toast({ title: "Map saved" });
      }
      router.push("/maps");
      router.refresh();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Save failed";
      setServerError(message);
      toast({
        title: "Save failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  }, [
    issues,
    initial,
    name,
    description,
    width,
    height,
    tiles,
    spawnZones,
    router,
    toast,
  ]);

  const handleCancel = useCallback(() => {
    router.push("/maps");
  }, [router]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-8">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-2xl text-ink">
          {initial ? `Edit map: ${initial.name}` : "New map"}
        </h1>
        <p className="text-xs text-ink-muted">
          {width} × {height} · {spawnZones.length} spawn zone
          {spawnZones.length === 1 ? "" : "s"}
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="flex flex-col gap-3">
          <div
            className="overflow-auto rounded border border-ink/10 bg-white p-2"
            data-testid="map-editor-canvas-container"
          >
            <canvas
              ref={canvasRef}
              width={canvasWidth}
              height={canvasHeight}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onPointerLeave={handlePointerLeave}
              style={{
                touchAction: "none",
                cursor: "crosshair",
                imageRendering: "pixelated",
              }}
              data-testid="map-editor-canvas"
            />
          </div>

          <div className="flex flex-wrap gap-2" data-testid="map-editor-tools">
            {TERRAIN_BRUSHES.map((terrain) => {
              const active =
                tool.kind === "terrain" && tool.terrain === terrain;
              return (
                <button
                  key={terrain}
                  type="button"
                  onClick={() => setTool({ kind: "terrain", terrain })}
                  className={`flex items-center gap-2 rounded border px-3 py-1.5 text-xs ${
                    active
                      ? "border-ink bg-ink text-white"
                      : "border-ink/20 text-ink hover:border-ink/40"
                  }`}
                  data-testid={`tool-terrain-${terrain}`}
                  aria-pressed={active}
                >
                  <span
                    aria-hidden
                    className="h-3 w-3 rounded-sm border border-ink/20"
                    style={{ background: TERRAIN_COLORS[terrain] }}
                  />
                  {TERRAIN_LABELS[terrain]}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => setTool({ kind: "spawn" })}
              className={`rounded border px-3 py-1.5 text-xs ${
                tool.kind === "spawn"
                  ? "border-ink bg-ink text-white"
                  : "border-ink/20 text-ink hover:border-ink/40"
              }`}
              data-testid="tool-spawn"
              aria-pressed={tool.kind === "spawn"}
            >
              Spawn pin
            </button>
            <button
              type="button"
              onClick={() => setTool({ kind: "eraser" })}
              className={`rounded border px-3 py-1.5 text-xs ${
                tool.kind === "eraser"
                  ? "border-ink bg-ink text-white"
                  : "border-ink/20 text-ink hover:border-ink/40"
              }`}
              data-testid="tool-eraser"
              aria-pressed={tool.kind === "eraser"}
            >
              Eraser
            </button>
          </div>
        </div>

        <aside className="flex w-full flex-col gap-4 lg:w-80">
          <div className="space-y-2">
            <Label htmlFor="map-name">Name</Label>
            <Input
              id="map-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              data-testid="map-editor-name"
            />
            {issueByField.name?.map((message) => (
              <p
                key={message}
                className="text-xs text-red-600"
                data-testid="error-name"
              >
                {message}
              </p>
            ))}
          </div>

          <div className="space-y-2">
            <Label htmlFor="map-description">Description</Label>
            <textarea
              id="map-description"
              value={description ?? ""}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={2000}
              rows={3}
              className="w-full rounded border border-ink/20 bg-white p-2 text-sm"
              data-testid="map-editor-description"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-2">
              <Label htmlFor="map-width">Width</Label>
              <Input
                id="map-width"
                type="number"
                min={SAVED_MAP_DIM_MIN}
                max={SAVED_MAP_DIM_MAX}
                value={width}
                onChange={(event) =>
                  handleResize(parseInt(event.target.value, 10), height)
                }
                data-testid="map-editor-width"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="map-height">Height</Label>
              <Input
                id="map-height"
                type="number"
                min={SAVED_MAP_DIM_MIN}
                max={SAVED_MAP_DIM_MAX}
                value={height}
                onChange={(event) =>
                  handleResize(width, parseInt(event.target.value, 10))
                }
                data-testid="map-editor-height"
              />
            </div>
          </div>
          {issueByField.width?.map((message) => (
            <p
              key={message}
              className="text-xs text-red-600"
              data-testid="error-width"
            >
              {message}
            </p>
          ))}
          {issueByField.height?.map((message) => (
            <p
              key={message}
              className="text-xs text-red-600"
              data-testid="error-height"
            >
              {message}
            </p>
          ))}

          <div className="space-y-2">
            <Label>Starter</Label>
            <div className="flex flex-wrap gap-2">
              {(["grass", "water", "desert"] as const).map((terrain) => (
                <Button
                  key={terrain}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handleFillAll(terrain)}
                  data-testid={`fill-${terrain}`}
                >
                  Fill {TERRAIN_LABELS[terrain].toLowerCase()}
                </Button>
              ))}
            </div>
            <p className="text-xs text-ink-muted">
              Replaces the entire grid with the chosen terrain. Spawn zones
              clear when filling with terrain that can&apos;t host them.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Spawn zones ({spawnZones.length})</Label>
            {spawnZones.length === 0 ? (
              <p className="text-xs text-ink-muted">
                None yet. Pick the spawn-pin tool and click on the map to
                place markers.
              </p>
            ) : (
              <ul
                className="max-h-40 space-y-1 overflow-auto text-xs"
                data-testid="spawn-list"
              >
                {spawnZones.map((z, index) => (
                  <li
                    key={`${z.x},${z.y}`}
                    className="flex items-center justify-between rounded bg-paper px-2 py-1"
                  >
                    <span className="font-mono">
                      ({z.x}, {z.y})
                    </span>
                    <button
                      type="button"
                      className="text-red-600 hover:underline"
                      onClick={() =>
                        setSpawnZones((prev) =>
                          prev.filter((_, i) => i !== index),
                        )
                      }
                      data-testid={`spawn-remove-${index}`}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {issueByField.spawn_zones?.map((message) => (
              <p
                key={message}
                className="text-xs text-red-600"
                data-testid="error-spawn"
              >
                {message}
              </p>
            ))}
          </div>

          {serverError && (
            <p
              className="text-xs text-red-600"
              data-testid="error-server"
            >
              {serverError}
            </p>
          )}

          <div className="flex gap-2">
            <Button
              type="button"
              onClick={handleSave}
              disabled={saving || issues.length > 0}
              data-testid="map-editor-save"
            >
              {saving ? "Saving…" : initial ? "Save changes" : "Create map"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              data-testid="map-editor-cancel"
            >
              Cancel
            </Button>
          </div>
        </aside>
      </div>
    </div>
  );
}
