// pixel-map.jsx
// A small Canvas2D renderer that fakes the look of the team's sprite map.
// Not pretending to be Pixi — this is a visual stand-in for design review.
//
// Generates a deterministic island map from a seed. Draws terrain, trees,
// mountains, rivers, resources, units (with player tint), cities, and the
// chrome overlays from the brief: yellow valid-move ring, red attack ring,
// queued-order ghost, fog-of-war veil, selection box, valid-move sparkles.

function makeRng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xFFFFFFFF;
  };
}

// Terrain palette — each cell is drawn as 4×4 mini-pixels for that crunchy feel.
const TERRAIN = {
  grass:    { base: '#7BAE5B', dark: '#6CA053', light: '#86B965', specks: ['#9CC579', '#558E47'] },
  forest:   { base: '#3E7A48', dark: '#2F6238', light: '#4F8A56', specks: ['#5C9962', '#22512A'] },
  hills:    { base: '#9C8A55', dark: '#7C6E40', light: '#B6A36A', specks: ['#C4B47C', '#695D38'] },
  mountain: { base: '#7C7670', dark: '#5F5A55', light: '#9A938C', specks: ['#A9A29B', '#4D4A47'] },
  water:    { base: '#3F84B8', dark: '#2D6E9F', light: '#549AC9', specks: ['#67ACDA', '#235479'] },
  desert:   { base: '#D8C188', dark: '#BDA76A', light: '#E8D29A', specks: ['#EDDDAB', '#9C8C5A'] },
  swamp:    { base: '#5F7A4F', dark: '#48613A', light: '#75906A', specks: ['#83A07B', '#3A4F2E'] },
};

function generateMap(cols, rows, seed = 7) {
  const rng = makeRng(seed);
  const tiles = [];
  // Build a smooth height field via diamond-square-ish noise
  const hf = new Float32Array(cols * rows);
  for (let i = 0; i < hf.length; i++) hf[i] = rng();
  // Smooth a few times
  for (let pass = 0; pass < 3; pass++) {
    const next = new Float32Array(hf.length);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        let s = 0, n = 0;
        for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
          const rr = r + dr, cc = c + dc;
          if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
          s += hf[rr * cols + cc]; n++;
        }
        next[r * cols + c] = s / n;
      }
    }
    hf.set(next);
  }
  // Edge falloff to make an island
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const dx = (c - cols / 2) / (cols / 2);
      const dy = (r - rows / 2) / (rows / 2);
      const d = Math.sqrt(dx * dx + dy * dy);
      hf[r * cols + c] -= Math.max(0, d - 0.55) * 1.2;
    }
  }
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const h = hf[r * cols + c];
      let kind;
      if (h < 0.30) kind = 'water';
      else if (h < 0.36) kind = 'desert';
      else if (h < 0.55) kind = 'grass';
      else if (h < 0.62) kind = 'forest';
      else if (h < 0.72) kind = 'hills';
      else kind = 'mountain';
      // Sprinkle swamps near coasts
      if (kind === 'grass' && rng() < 0.04) kind = 'swamp';
      tiles.push({ kind, h });
    }
  }
  return tiles;
}

// Draw a single terrain tile as a 4x4 mini-grid of pixels.
function drawTile(ctx, x, y, size, kind, rng) {
  const t = TERRAIN[kind] || TERRAIN.grass;
  const sub = size / 4;
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      const roll = rng();
      let color;
      if (roll < 0.10) color = t.specks[0];
      else if (roll < 0.20) color = t.specks[1];
      else if (roll < 0.50) color = t.dark;
      else if (roll < 0.80) color = t.base;
      else color = t.light;
      ctx.fillStyle = color;
      ctx.fillRect(x + c * sub, y + r * sub, Math.ceil(sub), Math.ceil(sub));
    }
  }
}

// Tree silhouette on a tile
function drawTree(ctx, x, y, size) {
  const cx = x + size / 2, cy = y + size / 2;
  ctx.fillStyle = '#1F4724';
  // canopy
  ctx.fillRect(cx - size * 0.28, cy - size * 0.30, size * 0.56, size * 0.40);
  ctx.fillRect(cx - size * 0.36, cy - size * 0.16, size * 0.72, size * 0.28);
  // trunk
  ctx.fillStyle = '#5A3A1E';
  ctx.fillRect(cx - size * 0.05, cy + size * 0.10, size * 0.10, size * 0.22);
  // highlight
  ctx.fillStyle = '#3C7A40';
  ctx.fillRect(cx - size * 0.20, cy - size * 0.22, size * 0.10, size * 0.10);
}

function drawMountain(ctx, x, y, size) {
  ctx.fillStyle = '#4A4540';
  // triangle silhouette
  for (let i = 0; i < size * 0.55; i++) {
    const w = i;
    ctx.fillRect(x + size / 2 - w / 2, y + size * 0.85 - i, w, 1);
  }
  // snowcap
  ctx.fillStyle = '#E8E2D8';
  ctx.fillRect(x + size * 0.42, y + size * 0.30, size * 0.16, size * 0.05);
}

function drawResource(ctx, x, y, size, kind) {
  const cx = x + size / 2, cy = y + size / 2;
  const colors = {
    food:    '#E0C56C',
    wood:    '#7A4F2A',
    ore:     '#A8A4A0',
    crystal: '#B470C8',
  };
  ctx.fillStyle = colors[kind] || '#fff';
  if (kind === 'crystal') {
    // diamond
    ctx.fillRect(cx - 1, cy - 4, 2, 8);
    ctx.fillRect(cx - 2, cy - 2, 4, 4);
  } else {
    ctx.fillRect(cx - 2, cy - 2, 4, 4);
  }
}

function drawUnit(ctx, x, y, size, kind, color) {
  // Banner: tinted base rectangle
  ctx.fillStyle = color;
  ctx.fillRect(x + size * 0.18, y + size * 0.62, size * 0.64, size * 0.22);
  // Body silhouette
  ctx.fillStyle = '#2A1F18';
  if (kind === 'soldier') {
    // helmet + body
    ctx.fillRect(x + size * 0.36, y + size * 0.18, size * 0.28, size * 0.18);
    ctx.fillRect(x + size * 0.30, y + size * 0.32, size * 0.40, size * 0.28);
  } else if (kind === 'worker') {
    ctx.fillRect(x + size * 0.38, y + size * 0.20, size * 0.24, size * 0.18);
    ctx.fillRect(x + size * 0.32, y + size * 0.36, size * 0.36, size * 0.24);
    // tool
    ctx.fillStyle = '#8A6A3A';
    ctx.fillRect(x + size * 0.66, y + size * 0.30, size * 0.05, size * 0.30);
  } else if (kind === 'scout') {
    ctx.fillRect(x + size * 0.38, y + size * 0.16, size * 0.24, size * 0.14);
    ctx.fillRect(x + size * 0.34, y + size * 0.30, size * 0.32, size * 0.30);
  } else if (kind === 'archer') {
    ctx.fillRect(x + size * 0.38, y + size * 0.18, size * 0.24, size * 0.16);
    ctx.fillRect(x + size * 0.32, y + size * 0.32, size * 0.36, size * 0.28);
    ctx.fillStyle = '#8A6A3A';
    // bow
    ctx.fillRect(x + size * 0.20, y + size * 0.30, size * 0.04, size * 0.30);
  }
}

function drawCity(ctx, x, y, size, color) {
  // banner
  ctx.fillStyle = color;
  ctx.fillRect(x + size * 0.10, y + size * 0.74, size * 0.80, size * 0.14);
  // walls
  ctx.fillStyle = '#A89E8C';
  ctx.fillRect(x + size * 0.16, y + size * 0.42, size * 0.68, size * 0.32);
  // crenellations
  for (let i = 0; i < 4; i++) {
    ctx.fillRect(x + size * (0.18 + i * 0.18), y + size * 0.36, size * 0.10, size * 0.08);
  }
  // door
  ctx.fillStyle = '#3A2A1A';
  ctx.fillRect(x + size * 0.44, y + size * 0.56, size * 0.12, size * 0.18);
  // tower
  ctx.fillStyle = '#A89E8C';
  ctx.fillRect(x + size * 0.42, y + size * 0.20, size * 0.16, size * 0.28);
  ctx.fillStyle = color;
  // flag on tower
  ctx.fillRect(x + size * 0.50, y + size * 0.14, size * 0.18, size * 0.10);
}

function PixelMap({
  cols = 22, rows = 16, seed = 11,
  tile = 28,
  units = [],
  cities = [],
  selected = null,
  validMoves = [],
  attacks = [],
  queued = [],
  fog = [],
  hovered = null,
  onTileHover, onTileClick,
  showCoords = false,
  showGrid = true,
  frameVariant = 'inset', // 'inset' | 'parchment' | 'cartographic' | 'floating'
}) {
  const canvasRef = React.useRef(null);
  const overlayRef = React.useRef(null);
  // Static layer (terrain + decorations + cities) is cached and only redrawn
  // when the map shape itself changes.
  const map = React.useMemo(() => generateMap(cols, rows, seed), [cols, rows, seed]);

  // Decoration layer — derived from terrain, deterministic.
  const decorations = React.useMemo(() => {
    const rng = makeRng(seed + 1);
    const decs = [];
    for (let i = 0; i < map.length; i++) {
      const t = map[i];
      const r = Math.floor(i / cols), c = i % cols;
      if (t.kind === 'forest' && rng() < 0.85) decs.push({ r, c, kind: 'tree' });
      if (t.kind === 'mountain' && rng() < 0.80) decs.push({ r, c, kind: 'mountain' });
      if (t.kind === 'grass' && rng() < 0.04) decs.push({ r, c, kind: 'food' });
      if (t.kind === 'hills' && rng() < 0.12) decs.push({ r, c, kind: 'ore' });
      if (t.kind === 'mountain' && rng() < 0.06) decs.push({ r, c, kind: 'crystal' });
    }
    return decs;
  }, [map, cols, seed]);

  // Static layer renders to an offscreen canvas; we just blit it.
  const staticCanvasRef = React.useRef(null);
  React.useEffect(() => {
    const off = document.createElement('canvas');
    off.width = cols * tile;
    off.height = rows * tile;
    const ctx = off.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    // terrain
    const trng = makeRng(seed + 2);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const t = map[r * cols + c];
        drawTile(ctx, c * tile, r * tile, tile, t.kind, trng);
      }
    }
    // decorations
    for (const d of decorations) {
      const x = d.c * tile, y = d.r * tile;
      if (d.kind === 'tree') drawTree(ctx, x, y, tile);
      else if (d.kind === 'mountain') drawMountain(ctx, x, y, tile);
      else drawResource(ctx, x, y, tile, d.kind);
    }
    // cities
    for (const city of cities) {
      drawCity(ctx, city.c * tile, city.r * tile, tile, city.color);
    }
    staticCanvasRef.current = off;
    // Trigger overlay repaint
    if (canvasRef.current) {
      const main = canvasRef.current.getContext('2d');
      main.imageSmoothingEnabled = false;
      main.clearRect(0, 0, off.width, off.height);
      main.drawImage(off, 0, 0);
    }
  }, [map, decorations, cols, rows, tile, seed, cities]);

  // Overlay layer (units + selection rings + fog) — repainted often.
  React.useEffect(() => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Grid
    if (showGrid) {
      ctx.strokeStyle = 'rgba(0,0,0,0.18)';
      ctx.lineWidth = 1;
      for (let c = 0; c <= cols; c++) {
        ctx.beginPath(); ctx.moveTo(c * tile + 0.5, 0); ctx.lineTo(c * tile + 0.5, rows * tile); ctx.stroke();
      }
      for (let r = 0; r <= rows; r++) {
        ctx.beginPath(); ctx.moveTo(0, r * tile + 0.5); ctx.lineTo(cols * tile, r * tile + 0.5); ctx.stroke();
      }
    }

    // Fog of war
    for (const f of fog) {
      ctx.fillStyle = 'rgba(20,16,10,0.55)';
      ctx.fillRect(f.c * tile, f.r * tile, tile, tile);
    }

    // Valid-move ring (warm gold, not neon)
    for (const m of validMoves) {
      ctx.fillStyle = 'rgba(218, 178, 89, 0.22)';
      ctx.fillRect(m.c * tile, m.r * tile, tile, tile);
      ctx.strokeStyle = 'rgba(218, 178, 89, 0.95)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(m.c * tile + 1, m.r * tile + 1, tile - 2, tile - 2);
    }
    // Attack ring (oxblood)
    for (const a of attacks) {
      ctx.fillStyle = 'rgba(181, 48, 46, 0.20)';
      ctx.fillRect(a.c * tile, a.r * tile, tile, tile);
      ctx.strokeStyle = 'rgba(181, 48, 46, 0.95)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(a.c * tile + 1, a.r * tile + 1, tile - 2, tile - 2);
    }
    // Queued-order arrow
    for (const q of queued) {
      const fx = q.from.c * tile + tile / 2;
      const fy = q.from.r * tile + tile / 2;
      const tx = q.to.c * tile + tile / 2;
      const ty = q.to.r * tile + tile / 2;
      ctx.strokeStyle = 'rgba(250, 245, 235, 0.85)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.moveTo(fx, fy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.setLineDash([]);
      // arrowhead
      const ang = Math.atan2(ty - fy, tx - fx);
      ctx.fillStyle = 'rgba(250, 245, 235, 0.95)';
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - 6 * Math.cos(ang - 0.4), ty - 6 * Math.sin(ang - 0.4));
      ctx.lineTo(tx - 6 * Math.cos(ang + 0.4), ty - 6 * Math.sin(ang + 0.4));
      ctx.closePath();
      ctx.fill();
    }

    // Units (drawn after rings so they sit on top)
    for (const u of units) {
      drawUnit(ctx, u.c * tile, u.r * tile, tile, u.kind, u.color);
    }

    // Selection box on top
    if (selected) {
      ctx.strokeStyle = 'rgba(250, 245, 235, 0.95)';
      ctx.lineWidth = 2;
      ctx.strokeRect(selected.c * tile + 0.5, selected.r * tile + 0.5, tile - 1, tile - 1);
      ctx.strokeStyle = 'rgba(20,16,10,0.6)';
      ctx.lineWidth = 1;
      ctx.strokeRect(selected.c * tile - 0.5, selected.r * tile - 0.5, tile + 1, tile + 1);
    }

    // Hover (subtle)
    if (hovered) {
      ctx.fillStyle = 'rgba(250,245,235,0.10)';
      ctx.fillRect(hovered.c * tile, hovered.r * tile, tile, tile);
    }
  }, [units, fog, validMoves, attacks, queued, selected, hovered, cols, rows, tile, showGrid]);

  function handleMove(e) {
    if (!onTileHover) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const c = Math.floor((e.clientX - rect.left) * (cols * tile) / rect.width / tile);
    const r = Math.floor((e.clientY - rect.top) * (rows * tile) / rect.height / tile);
    if (c >= 0 && c < cols && r >= 0 && r < rows) onTileHover({ r, c });
  }
  function handleLeave() { onTileHover && onTileHover(null); }
  function handleClick(e) {
    if (!onTileClick) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const c = Math.floor((e.clientX - rect.left) * (cols * tile) / rect.width / tile);
    const r = Math.floor((e.clientY - rect.top) * (rows * tile) / rect.height / tile);
    if (c >= 0 && c < cols && r >= 0 && r < rows) onTileClick({ r, c });
  }

  // Frame styles
  const frameStyles = {
    inset: {
      padding: 0,
      background: 'var(--map-void)',
      border: '1px solid var(--border-strong)',
      borderRadius: 8,
      boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.20), 0 1px 0 rgba(255,255,255,0.04), 0 12px 28px -16px rgba(0,0,0,0.35)',
    },
    parchment: {
      padding: 12,
      background: 'var(--parchment)',
      border: '1px solid var(--parchment-edge)',
      borderRadius: 4,
      boxShadow: 'inset 0 0 0 1px var(--parchment-edge), 0 1px 0 rgba(255,255,255,0.5), 0 18px 40px -22px rgba(0,0,0,0.45)',
      backgroundImage: 'radial-gradient(circle at 30% 20%, rgba(0,0,0,0.04), transparent 60%), radial-gradient(circle at 70% 80%, rgba(0,0,0,0.06), transparent 60%)',
    },
    cartographic: {
      padding: 16,
      background: 'var(--parchment)',
      border: '2px double var(--ink)',
      borderRadius: 0,
      boxShadow: '0 18px 40px -22px rgba(0,0,0,0.45)',
    },
    floating: {
      padding: 0,
      background: 'transparent',
      border: 'none',
      borderRadius: 0,
      boxShadow: 'none',
    },
  };

  return (
    <div style={{
      ...frameStyles[frameVariant],
      position: 'relative',
      width: '100%', height: '100%',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {/* corner marks for cartographic frame */}
      {frameVariant === 'cartographic' && (
        <>
          <CornerMark pos="tl"/><CornerMark pos="tr"/><CornerMark pos="bl"/><CornerMark pos="br"/>
        </>
      )}
      <div
        style={{
          position: 'relative',
          width: cols * tile, height: rows * tile,
          maxWidth: '100%', maxHeight: '100%',
          imageRendering: 'pixelated',
        }}
        onMouseMove={handleMove}
        onMouseLeave={handleLeave}
        onClick={handleClick}
      >
        <canvas
          ref={canvasRef}
          width={cols * tile} height={rows * tile}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', imageRendering: 'pixelated' }}
        />
        <canvas
          ref={overlayRef}
          width={cols * tile} height={rows * tile}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', imageRendering: 'pixelated', pointerEvents: 'none' }}
        />
      </div>
    </div>
  );
}

function CornerMark({ pos }) {
  const map = {
    tl: { top: 6, left: 6 },
    tr: { top: 6, right: 6, transform: 'scaleX(-1)' },
    bl: { bottom: 6, left: 6, transform: 'scaleY(-1)' },
    br: { bottom: 6, right: 6, transform: 'scale(-1,-1)' },
  };
  return (
    <svg width="22" height="22" viewBox="0 0 22 22"
         style={{ position: 'absolute', ...map[pos], pointerEvents: 'none' }} aria-hidden>
      <path d="M 1 1 L 1 8 M 1 1 L 8 1" stroke="var(--ink)" strokeWidth="1.5" fill="none" />
      <circle cx="1" cy="1" r="1.6" fill="var(--ink)" />
    </svg>
  );
}

Object.assign(window, { PixelMap, generateMap });
