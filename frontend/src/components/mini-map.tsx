"use client";

import { useCallback, useMemo, useRef } from "react";

import { MapFrame } from "@/components/ui/map-frame";
import { TERRAIN_COLORS, PLAYER_COLORS } from "@/types/game";
import type { Coord, GameState, ViewportRect } from "@/types/game";

interface MiniMapProps {
  gameState: GameState;
  /** Current viewport rect of the parent map, in tile coords. */
  viewport?: ViewportRect | null;
  /** Click-to-pan: receives the tile coord under the click so the
   *  parent map can recentre on it. */
  onPanRequest?: (coord: Coord) => void;
  /** Pixel width of the rendered mini-map. Height is derived from the
   *  game's aspect ratio so the rectangle remains shape-true. */
  width?: number;
}

/**
 * Low-zoom satellite renderer for the main map. Renders terrain via
 * <rect> per tile, owners as a tinted overlay, units / cities as
 * dots, and the parent map's current viewport as an accent-coloured
 * rectangle. Click anywhere to pan the parent.
 *
 * Implemented as plain SVG rather than a second Pixi instance — the
 * mini-map is a fraction of the main map's tile count and a static
 * SVG paints faster, costs no GPU, and gives free click-to-pan.
 */
export function MiniMap({
  gameState,
  viewport,
  onPanRequest,
  width = 200,
}: MiniMapProps) {
  const { map_width, map_height, tiles, units, cities, players } = gameState;
  const aspect = map_width / map_height;
  const height = Math.round(width / aspect);
  const tilePx = width / map_width;
  const svgRef = useRef<SVGSVGElement>(null);

  const tileLookup = useMemo(() => {
    const m = new Map<string, (typeof tiles)[number]>();
    for (const t of tiles) m.set(`${t.loc.x},${t.loc.y}`, t);
    return m;
  }, [tiles]);

  const handleClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!onPanRequest) return;
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const tx = Math.max(0, Math.min(map_width - 1, Math.floor(px / tilePx)));
      const ty = Math.max(0, Math.min(map_height - 1, Math.floor(py / tilePx)));
      onPanRequest({ x: tx, y: ty });
    },
    [onPanRequest, map_width, map_height, tilePx],
  );

  const viewportRectPx = viewport
    ? {
        x: Math.max(0, viewport.x * tilePx),
        y: Math.max(0, viewport.y * tilePx),
        width: Math.max(2, Math.min(width, viewport.width * tilePx)),
        height: Math.max(2, Math.min(height, viewport.height * tilePx)),
      }
    : null;

  return (
    <MapFrame
      variant="floating"
      style={{ width, height, background: "var(--map-void)" }}
    >
      <svg
        ref={svgRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{ display: "block", cursor: onPanRequest ? "crosshair" : "default" }}
        onClick={handleClick}
        aria-label="Mini-map"
      >
        {/* Terrain — emit a rect for every visible tile. Unexplored
            tiles fall back to the map-void background. */}
        {tiles.map((t) => (
          <rect
            key={`${t.loc.x}-${t.loc.y}`}
            x={t.loc.x * tilePx}
            y={t.loc.y * tilePx}
            width={tilePx}
            height={tilePx}
            fill={TERRAIN_COLORS[t.terrain] ?? "#7BAE5B"}
          />
        ))}

        {/* Owner tint — a translucent player-colour overlay marks
            controlled tiles without losing the terrain underneath. */}
        {tiles.map((t) => {
          if (!t.owner) return null;
          const idx = players.indexOf(t.owner);
          const color = PLAYER_COLORS[idx] ?? "#666666";
          return (
            <rect
              key={`o-${t.loc.x}-${t.loc.y}`}
              x={t.loc.x * tilePx}
              y={t.loc.y * tilePx}
              width={tilePx}
              height={tilePx}
              fill={color}
              opacity={0.32}
            />
          );
        })}

        {/* Unexplored tiles get a subtle parchment tint so they read
            as part of the map rather than holes. */}
        {Array.from({ length: map_height }).flatMap((_, gy) =>
          Array.from({ length: map_width }).map((__, gx) =>
            tileLookup.has(`${gx},${gy}`) ? null : (
              <rect
                key={`fog-${gx}-${gy}`}
                x={gx * tilePx}
                y={gy * tilePx}
                width={tilePx}
                height={tilePx}
                fill="#2a2218"
                opacity={0.92}
              />
            ),
          ),
        )}

        {/* Cities — slightly larger square, tinted to owner. */}
        {Object.values(cities).map((c) => {
          const idx = players.indexOf(c.owner);
          const color = PLAYER_COLORS[idx] ?? "#bbbbbb";
          const size = Math.max(2.5, tilePx * 0.9);
          return (
            <rect
              key={`c-${c.id}`}
              x={c.loc.x * tilePx + (tilePx - size) / 2}
              y={c.loc.y * tilePx + (tilePx - size) / 2}
              width={size}
              height={size}
              fill={color}
              stroke="#0a0a14"
              strokeWidth={0.5}
            />
          );
        })}

        {/* Units — dot per top-of-stack so the mini-map shows
            distribution at a glance. */}
        {Object.values(units).map((u) => {
          const idx = players.indexOf(u.owner);
          const color = PLAYER_COLORS[idx] ?? "#bbbbbb";
          return (
            <circle
              key={`u-${u.id}`}
              cx={u.loc.x * tilePx + tilePx / 2}
              cy={u.loc.y * tilePx + tilePx / 2}
              r={Math.max(1, tilePx * 0.28)}
              fill={color}
              stroke="#0a0a14"
              strokeWidth={0.4}
            />
          );
        })}

        {/* Viewport rectangle — accent-coloured outline marking the
            parent map's currently visible area. */}
        {viewportRectPx && (
          <rect
            x={viewportRectPx.x}
            y={viewportRectPx.y}
            width={viewportRectPx.width}
            height={viewportRectPx.height}
            fill="none"
            stroke="var(--ring-accent)"
            strokeWidth={1.5}
            opacity={0.95}
            pointerEvents="none"
          />
        )}
      </svg>
    </MapFrame>
  );
}
