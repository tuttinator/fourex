// brand.jsx — wordmarks, square mark, identity glyphs, sprite atoms
//
// All wordmarks are SVG. The user asked for 3-4 variants; expose via tweak.
// Each lock-up has a horizontal form for nav/landing and a square form for
// favicon/avatar.

// ────────── WORDMARKS ──────────

// Variant 1: "Flag" — a simple parley flag (white triangle pennant on staff)
// inline with the wordmark. Heraldic, on-theme (parley = a parlay flag).
function WordmarkFlag({ size = 32, mono = false, color }) {
  const c = color || 'var(--ink)';
  const accent = mono ? c : 'var(--accent)';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: size * 0.32,
      fontFamily: 'var(--font-display)', fontWeight: 600,
      fontSize: size, lineHeight: 1, letterSpacing: '-0.015em',
      color: c,
    }}>
      <svg width={size * 0.92} height={size * 1.05} viewBox="0 0 24 28" fill="none" aria-hidden>
        {/* staff */}
        <rect x="3.4" y="1" width="1.2" height="26" rx="0.5" fill={c} />
        {/* pennant */}
        <path d="M 5 2 L 22 5.5 L 5 9 Z" fill={accent} />
        {/* tiny base */}
        <rect x="2" y="25.5" width="4" height="1.5" rx="0.5" fill={c} />
      </svg>
      <span>Parley</span>
    </span>
  );
}

// Variant 2: "Monogram" — slab P inside a rounded square. Calmer.
function WordmarkMonogram({ size = 32, mono = false, color }) {
  const c = color || 'var(--ink)';
  const accent = mono ? c : 'var(--accent)';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: size * 0.36,
      fontFamily: 'var(--font-display)', fontWeight: 600,
      fontSize: size, lineHeight: 1, letterSpacing: '-0.015em',
      color: c,
    }}>
      <svg width={size * 1.05} height={size * 1.05} viewBox="0 0 32 32" aria-hidden>
        <rect x="0.5" y="0.5" width="31" height="31" rx="6" fill={accent} />
        <text x="16" y="23.5" textAnchor="middle"
              fontFamily="var(--font-display)" fontWeight="700" fontSize="22"
              fill="var(--accent-ink)">P</text>
      </svg>
      <span>Parley</span>
    </span>
  );
}

// Variant 3: "Stamp" — wordmark inside a hairline ruled cartouche, like a
// printed map cartouche. Most "old-world" of the lot.
function WordmarkStamp({ size = 32, mono = false, color }) {
  const c = color || 'var(--ink)';
  const w = size * 5.2;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      fontFamily: 'var(--font-display)', fontWeight: 600,
      fontSize: size, lineHeight: 1, letterSpacing: '0.01em',
      color: c, position: 'relative',
      padding: `${size * 0.22}px ${size * 0.55}px`,
      border: `1px solid ${c}`,
      borderRadius: 2,
    }}>
      <span style={{
        position: 'absolute', inset: size * 0.10 + 'px',
        border: `1px solid ${c}`, borderRadius: 1, opacity: 0.45,
        pointerEvents: 'none',
      }}/>
      <span style={{ fontVariant: 'small-caps', letterSpacing: '0.06em' }}>Parley</span>
    </span>
  );
}

// Variant 4: "Plain" — just the slab wordmark, no symbol. For tight contexts.
function WordmarkPlain({ size = 32, mono = false, color }) {
  const c = color || 'var(--ink)';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'baseline', gap: 2,
      fontFamily: 'var(--font-display)', fontWeight: 700,
      fontSize: size, lineHeight: 1, letterSpacing: '-0.025em',
      color: c,
    }}>
      <span>Parley</span>
      <span style={{
        color: 'var(--accent)', fontSize: size * 0.55,
        transform: `translateY(-${size * 0.30}px)`,
        marginLeft: 1,
      }}>·</span>
    </span>
  );
}

function Wordmark({ variant = 'flag', ...rest }) {
  if (variant === 'monogram') return <WordmarkMonogram {...rest} />;
  if (variant === 'stamp')    return <WordmarkStamp    {...rest} />;
  if (variant === 'plain')    return <WordmarkPlain    {...rest} />;
  return <WordmarkFlag {...rest} />;
}

// Square mark for favicon/avatar/agent identity slot
function SquareMark({ size = 32, color }) {
  const c = color || 'var(--accent)';
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect x="0" y="0" width="32" height="32" rx="6" fill={c} />
      <path d="M 11 7 L 11 25 M 11 8 L 21 11.5 L 11 15"
            stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="square" fill="none"/>
    </svg>
  );
}

// ────────── IDENTITY GLYPHS ──────────
// Humans get initials on a tinted disc. Agents get a deterministic geometric
// glyph keyed off their ID — same prominence, different visual language.

function HumanAvatar({ name, color, size = 28 }) {
  const initial = (name || '?').trim().slice(0, 1).toUpperCase();
  return (
    <span style={{
      width: size, height: size, borderRadius: '50%',
      background: color, color: 'white',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-ui)', fontWeight: 600,
      fontSize: size * 0.42, letterSpacing: '0.02em',
      boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,.15)',
      flexShrink: 0,
    }}>{initial}</span>
  );
}

// Agent glyph: 3x3 dot pattern derived from a hash of the id, on a square
// chip with hairline border. Reads as "machine" without being a robot icon.
function hashStr(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function AgentAvatar({ id, color, size = 28 }) {
  const h = hashStr(id || 'agent');
  // 3x3 grid; bit per cell. Always at least the center filled.
  const cells = [];
  for (let i = 0; i < 9; i++) {
    cells.push(((h >> i) & 1) === 1 || i === 4);
  }
  // Mirror left↔right for symmetry (heraldic feel)
  for (let r = 0; r < 3; r++) {
    cells[r * 3 + 2] = cells[r * 3 + 0];
    cells[r * 3 + 1] = cells[r * 3 + 1] || ((h >> (10 + r)) & 1) === 1;
  }
  const dot = size / 5.5;
  const gap = (size - dot * 3) / 4;
  return (
    <span style={{
      width: size, height: size, borderRadius: 5,
      background: color,
      display: 'inline-grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gridTemplateRows: 'repeat(3, 1fr)',
      gap: gap,
      padding: gap,
      boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,.20)',
      flexShrink: 0,
    }}>
      {cells.map((on, i) => (
        <span key={i} style={{
          background: on ? 'rgba(255,255,255,.95)' : 'transparent',
          borderRadius: 1,
        }}/>
      ))}
    </span>
  );
}

// Unified identity component
function Identity({ kind, name, id, color, size = 28, showLabel = false, label }) {
  const Avatar = kind === 'agent' ? AgentAvatar : HumanAvatar;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <Avatar name={name} id={id || name} color={color} size={size} />
      {showLabel && (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.15 }}>
          <span style={{ fontFamily: 'var(--font-ui)', fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
            {name}
          </span>
          {label && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 10.5,
              color: 'var(--ink-muted)', letterSpacing: '0.02em',
              textTransform: 'uppercase',
            }}>{label}</span>
          )}
        </span>
      )}
    </span>
  );
}

// ────────── PIXEL TILE PLACEHOLDER ──────────
// Tiny pixel-art-ish cell for sprite-strip displays in the brand panel.
// The real game uses 32x32 PNG/SVG; this is just a stand-in.

function PixelTile({ kind, size = 32 }) {
  // Each kind is a 4x4 simplified palette pattern.
  const palettes = {
    grass:   ['#7BAE5B', '#6FA253', '#85B962', '#6FA253'],
    water:   ['#3F84B8', '#4A91C4', '#3679AC', '#4A91C4'],
    forest:  ['#3E7A48', '#2F6238', '#3E7A48', '#2F6238'],
    mountain:['#7C7670', '#67625D', '#857F78', '#67625D'],
    desert:  ['#D8C188', '#C9B07A', '#E0CB95', '#C9B07A'],
    hills:   ['#A89860', '#90814F', '#B6A66D', '#90814F'],
  };
  const pal = palettes[kind] || palettes.grass;
  const cells = [];
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      // Pseudo-random within a deterministic walk
      const i = (r * 7 + c * 3 + (kind || '').charCodeAt(0)) % 4;
      cells.push(pal[i]);
    }
  }
  return (
    <span style={{
      width: size, height: size,
      display: 'inline-grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gridTemplateRows: 'repeat(4, 1fr)',
      imageRendering: 'pixelated',
      flexShrink: 0,
    }}>
      {cells.map((c, i) => <span key={i} style={{ background: c }}/>)}
    </span>
  );
}

Object.assign(window, {
  Wordmark, WordmarkFlag, WordmarkMonogram, WordmarkStamp, WordmarkPlain,
  SquareMark, HumanAvatar, AgentAvatar, Identity, PixelTile,
});
