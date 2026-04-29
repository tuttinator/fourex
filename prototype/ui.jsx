// ui.jsx — small UI vocabulary keyed off the theme tokens.
// Names mirror shadcn primitives so the eng team's mental model lines up.

const Btn = ({ variant = 'default', size = 'md', icon, iconRight, children, style, ...rest }) => {
  const base = {
    appearance: 'none', border: 0, cursor: 'pointer',
    fontFamily: 'var(--font-ui)', fontWeight: 500,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    gap: 8, whiteSpace: 'nowrap', userSelect: 'none',
    transition: 'background 120ms, border-color 120ms, color 120ms, transform 80ms',
  };
  const sizes = {
    sm: { height: 28, padding: '0 10px', fontSize: 12, borderRadius: 6 },
    md: { height: 34, padding: '0 14px', fontSize: 13, borderRadius: 7 },
    lg: { height: 42, padding: '0 18px', fontSize: 14, borderRadius: 8 },
  };
  const variants = {
    default: {
      background: 'var(--surface)', color: 'var(--ink)',
      boxShadow: 'inset 0 0 0 1px var(--border), 0 1px 0 rgba(0,0,0,0.02)',
    },
    primary: {
      background: 'var(--accent)', color: 'var(--accent-ink)',
      boxShadow: 'inset 0 0 0 1px var(--accent), 0 1px 0 rgba(0,0,0,0.12)',
    },
    ghost: { background: 'transparent', color: 'var(--ink-soft)' },
    outline: {
      background: 'transparent', color: 'var(--ink)',
      boxShadow: 'inset 0 0 0 1px var(--border-strong)',
    },
    danger: {
      background: 'var(--destructive)', color: 'white',
      boxShadow: 'inset 0 0 0 1px var(--destructive)',
    },
  };
  return (
    <button {...rest} style={{ ...base, ...sizes[size], ...variants[variant], ...style }}>
      {icon}{children}{iconRight}
    </button>
  );
};

const Panel = ({ title, action, children, style, padded = true }) => (
  <section style={{
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 10,
    overflow: 'hidden',
    boxShadow: '0 1px 0 rgba(0,0,0,0.02)',
    display: 'flex', flexDirection: 'column',
    ...style,
  }}>
    {title && (
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
      }}>
        <h3 style={{
          margin: 0, fontFamily: 'var(--font-ui)', fontWeight: 600,
          fontSize: 11.5, letterSpacing: '0.06em', textTransform: 'uppercase',
          color: 'var(--ink-muted)',
        }}>{title}</h3>
        {action && <div>{action}</div>}
      </header>
    )}
    <div style={{ padding: padded ? 14 : 0, flex: 1, minHeight: 0 }}>{children}</div>
  </section>
);

const Tag = ({ tone = 'neutral', mono = false, children, style }) => {
  const tones = {
    neutral: { bg: 'var(--surface-alt)', fg: 'var(--ink-soft)', bd: 'var(--border)' },
    accent:  { bg: 'var(--accent-soft)', fg: 'var(--accent)', bd: 'var(--accent-soft)' },
    success: { bg: 'oklch(from var(--success) l c h / 0.12)', fg: 'var(--success)', bd: 'oklch(from var(--success) l c h / 0.20)' },
    warning: { bg: 'oklch(from var(--warning) l c h / 0.14)', fg: 'oklch(from var(--warning) calc(l - 0.10) c h)', bd: 'oklch(from var(--warning) l c h / 0.30)' },
    live:    { bg: 'var(--accent-soft)', fg: 'var(--accent)', bd: 'transparent' },
  };
  const t = tones[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 8px', borderRadius: 999,
      background: t.bg, color: t.fg,
      boxShadow: `inset 0 0 0 1px ${t.bd}`,
      fontFamily: mono ? 'var(--font-mono)' : 'var(--font-ui)',
      fontSize: 11, fontWeight: 500, letterSpacing: mono ? '0.02em' : '0.005em',
      lineHeight: 1.5,
      ...style,
    }}>
      {tone === 'live' && <Dot color="var(--accent)" pulse />}
      {children}
    </span>
  );
};

const Dot = ({ color = 'currentColor', pulse = false, size = 6 }) => (
  <span style={{
    width: size, height: size, borderRadius: '50%',
    background: color, display: 'inline-block', flexShrink: 0,
    animation: pulse ? 'parley-pulse 1.6s ease-in-out infinite' : 'none',
  }}/>
);

// Resource chip used in topbars and panels
const Resource = ({ icon, label, value, delta, tone }) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', gap: 6,
    fontFamily: 'var(--font-ui)', fontSize: 13,
    color: 'var(--ink)',
  }}>
    <span style={{ width: 14, height: 14, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>{icon}</span>
    <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{value}</span>
    {delta != null && (
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 11,
        color: delta >= 0 ? 'var(--success)' : 'var(--destructive)',
        fontVariantNumeric: 'tabular-nums',
      }}>{delta >= 0 ? `+${delta}` : delta}</span>
    )}
  </span>
);

// Resource icons — flat shapes, not lucide. Keep minimal so they sit in
// 14×14 chips next to numbers.
const RIcon = {
  food: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <path d="M 7 1.5 C 4 1.5 2 4 2 7 C 2 10 4 12.5 7 12.5 C 10 12.5 12 10 12 7 C 12 4 10 1.5 7 1.5 Z" fill="oklch(0.72 0.140 75)"/>
      <path d="M 7 2.2 C 6 3 5.5 4 5.5 5 C 5.5 6 6 6.5 7 6.5 C 8 6.5 8.5 6 8.5 5 C 8.5 4 8 3 7 2.2 Z" fill="oklch(0.92 0.080 75)" opacity="0.75"/>
    </svg>
  ),
  wood: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <rect x="1.5" y="3" width="11" height="8" rx="1" fill="oklch(0.45 0.080 50)"/>
      <path d="M 1.5 5 L 12.5 5 M 1.5 7 L 12.5 7 M 1.5 9 L 12.5 9" stroke="oklch(0.32 0.060 50)" strokeWidth="0.6"/>
    </svg>
  ),
  ore: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <path d="M 7 1.5 L 12 5 L 10.5 12 L 3.5 12 L 2 5 Z" fill="oklch(0.62 0.020 60)" stroke="oklch(0.40 0.020 60)" strokeWidth="0.5"/>
      <path d="M 7 1.5 L 9 5 L 7 8 L 5 5 Z" fill="oklch(0.78 0.020 60)" opacity="0.6"/>
    </svg>
  ),
  crystal: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <path d="M 7 1.5 L 11 5 L 7 12.5 L 3 5 Z" fill="var(--accent)" opacity="0.85"/>
      <path d="M 7 1.5 L 9 5 L 7 12.5 L 5 5 Z" fill="white" opacity="0.35"/>
    </svg>
  ),
  unit: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <path d="M 4 11 L 7 4 L 10 11 Z" fill="var(--ink-soft)"/>
    </svg>
  ),
  city: (
    <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
      <rect x="2.5" y="6" width="9" height="6" fill="var(--ink-soft)"/>
      <rect x="6" y="3" width="2" height="3" fill="var(--ink-soft)"/>
      <rect x="3.5" y="5" width="1" height="1" fill="var(--ink-soft)"/>
      <rect x="6.5" y="5" width="1" height="1" fill="var(--ink-soft)"/>
      <rect x="9.5" y="5" width="1" height="1" fill="var(--ink-soft)"/>
    </svg>
  ),
};

// Section title — used in panels and to organize landing
const SectionTitle = ({ kicker, children, style }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, ...style }}>
    {kicker && (
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 11,
        textTransform: 'uppercase', letterSpacing: '0.10em',
        color: 'var(--accent)',
      }}>{kicker}</span>
    )}
    <h2 style={{
      margin: 0, fontFamily: 'var(--font-display)', fontWeight: 500,
      color: 'var(--ink)', letterSpacing: '-0.02em', lineHeight: 1.05,
      fontSize: 'clamp(28px, 3.4vw, 44px)',
    }}>{children}</h2>
  </div>
);

// KBD — keycap visual
const Kbd = ({ children, style }) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    minWidth: 18, height: 18, padding: '0 5px',
    background: 'var(--surface)', color: 'var(--ink-muted)',
    borderRadius: 4, boxShadow: 'inset 0 0 0 1px var(--border), 0 1px 0 var(--border)',
    fontFamily: 'var(--font-mono)', fontSize: 10.5,
    ...style,
  }}>{children}</span>
);

// Avatar disc for a list of players (not the agent/human switch — that's in brand.jsx)
const PlayerSwatch = ({ color, size = 12, style }) => (
  <span style={{
    width: size, height: size, borderRadius: 3, background: color,
    boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,0.30)',
    flexShrink: 0,
    ...style,
  }}/>
);

// Tabs — top-of-panel switcher
const Tabs = ({ value, options, onChange, style }) => (
  <div style={{
    display: 'inline-flex', gap: 2, padding: 2,
    background: 'var(--surface-alt)', borderRadius: 8,
    boxShadow: 'inset 0 0 0 1px var(--border)',
    ...style,
  }}>
    {options.map(opt => {
      const k = typeof opt === 'string' ? opt : opt.value;
      const label = typeof opt === 'string' ? opt : opt.label;
      const active = k === value;
      return (
        <button key={k}
          onClick={() => onChange(k)}
          style={{
            appearance: 'none', border: 0, cursor: 'pointer',
            padding: '5px 12px', borderRadius: 6,
            background: active ? 'var(--surface)' : 'transparent',
            color: active ? 'var(--ink)' : 'var(--ink-muted)',
            boxShadow: active ? 'inset 0 0 0 1px var(--border), 0 1px 0 rgba(0,0,0,0.02)' : 'none',
            fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 500,
            transition: 'background 100ms, color 100ms',
          }}>{label}</button>
      );
    })}
  </div>
);

Object.assign(window, { Btn, Panel, Tag, Dot, Resource, RIcon, SectionTitle, Kbd, PlayerSwatch, Tabs });
