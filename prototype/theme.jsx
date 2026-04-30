// theme.jsx — design tokens for Parley
// All colors as oklch strings so palette-shift / dark-mode flip in one place.

const PARLEY = {
  // Type pairings — display / ui / mono
  // User wanted "slab serif with character, not Fraunces". Roboto Slab is the
  // pragmatic pick (variable, broad weight range, no Fraunces fatigue). The
  // alternates exposed as a tweak give them an A/B without touching code.
  fontStacks: {
    'roboto-slab': {
      display: '"Roboto Slab", "DM Serif Display", Georgia, serif',
      ui: '"Inter Tight", Inter, ui-sans-serif, system-ui, sans-serif',
      mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
      label: 'Roboto Slab + Inter Tight',
    },
    'newsreader': {
      display: 'Newsreader, "Source Serif 4", Georgia, serif',
      ui: '"Inter Tight", Inter, ui-sans-serif, system-ui, sans-serif',
      mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
      label: 'Newsreader + Inter Tight',
    },
    'instrument': {
      display: '"Instrument Serif", "EB Garamond", Georgia, serif',
      ui: '"Geist", "Inter Tight", ui-sans-serif, system-ui, sans-serif',
      mono: '"Geist Mono", "JetBrains Mono", ui-monospace, monospace',
      label: 'Instrument Serif + Geist',
    },
  },

  // Light / dark token sets. Modeled on shadcn semantic names so the
  // engineering team can map 1:1 onto their CSS variables.
  themes: {
    light: {
      // Warm parchment-tinted neutrals. Not literal paper texture — just
      // hue-shifted toward 80° (pale honey).
      bg:           'oklch(0.985 0.008 80)',     // page
      bgSubtle:     'oklch(0.965 0.011 80)',     // section breaks
      surface:      'oklch(1.000 0.000 0)',      // cards, panels
      surfaceAlt:   'oklch(0.975 0.010 80)',     // table rows / hover
      parchment:    'oklch(0.955 0.020 78)',     // map backing, tooltips
      parchmentEdge:'oklch(0.895 0.028 70)',     // map frame inner edge

      ink:          'oklch(0.205 0.018 60)',     // primary text
      inkSoft:      'oklch(0.380 0.015 60)',     // secondary text
      inkMuted:     'oklch(0.560 0.012 60)',     // tertiary / hint
      inkFaint:     'oklch(0.720 0.010 60)',     // disabled, captions

      border:       'oklch(0.900 0.012 70)',
      borderStrong: 'oklch(0.820 0.016 65)',
      ring:         'oklch(0.520 0.140 25)',     // focus, matches accent

      // Single signal accent — oxblood/garnet. Heraldic, not corporate.
      accent:       'oklch(0.520 0.140 25)',
      accentHover:  'oklch(0.470 0.150 25)',
      accentSoft:   'oklch(0.945 0.030 25)',     // tag backgrounds
      accentInk:    'oklch(0.985 0.008 80)',     // text on accent

      success:      'oklch(0.520 0.115 145)',
      warning:      'oklch(0.640 0.130 75)',
      destructive:  'oklch(0.520 0.180 28)',

      // Map-specific
      mapVoid:      'oklch(0.215 0.018 60)',     // outside-of-map area
      tooltipBg:    'oklch(0.980 0.020 78)',
      tooltipInk:   'oklch(0.205 0.018 60)',
    },
    dark: {
      bg:           'oklch(0.180 0.010 60)',
      bgSubtle:     'oklch(0.215 0.012 60)',
      surface:      'oklch(0.235 0.014 60)',
      surfaceAlt:   'oklch(0.265 0.014 60)',
      parchment:    'oklch(0.310 0.018 65)',
      parchmentEdge:'oklch(0.380 0.020 65)',

      ink:          'oklch(0.965 0.010 80)',
      inkSoft:      'oklch(0.800 0.012 75)',
      inkMuted:     'oklch(0.620 0.014 70)',
      inkFaint:     'oklch(0.460 0.014 65)',

      border:       'oklch(0.310 0.014 60)',
      borderStrong: 'oklch(0.380 0.016 60)',
      ring:         'oklch(0.680 0.150 30)',

      accent:       'oklch(0.665 0.155 28)',     // garnet, brightened for dark
      accentHover:  'oklch(0.720 0.155 28)',
      accentSoft:   'oklch(0.295 0.060 25)',
      accentInk:    'oklch(0.165 0.018 60)',

      success:      'oklch(0.700 0.140 145)',
      warning:      'oklch(0.770 0.150 80)',
      destructive:  'oklch(0.660 0.190 28)',

      mapVoid:      'oklch(0.115 0.012 60)',
      tooltipBg:    'oklch(0.255 0.016 65)',
      tooltipInk:   'oklch(0.965 0.010 80)',
    },
  },

  // 8-player heraldic palette. Picked for max discriminability on
  // green/blue/gray/sand terrain AND pairwise CB safety. Each color also
  // has an "ink" pair for text on swatches and a "soft" pair for badges.
  // Ordered: positions 1–8 in a typical 8-player game.
  players: [
    { id: 'crimson', name: 'Crimson', hue: 22,  hex: '#B5302E' }, // deep red, classic flag
    { id: 'indigo',  name: 'Indigo',  hue: 265, hex: '#3D3F8F' }, // deep blue-violet
    { id: 'ochre',   name: 'Ochre',   hue: 78,  hex: '#C49A2C' }, // warm yellow, distinct from grass
    { id: 'forest',  name: 'Forest',  hue: 155, hex: '#2E6E4D' }, // dark cool green vs. grass green
    { id: 'plum',    name: 'Plum',    hue: 340, hex: '#7E2D52' }, // wine
    { id: 'teal',    name: 'Teal',    hue: 200, hex: '#1F6F87' }, // sea
    { id: 'slate',   name: 'Slate',   hue: 250, hex: '#4A5568' }, // cool dark gray (not bg gray)
    { id: 'ember',   name: 'Ember',   hue: 38,  hex: '#C7541C' }, // burnt orange
  ],

  // Density scales — affects row heights, paddings, gaps
  density: {
    compact: { row: 28, pad: 8,  gap: 8,  tile: 18 },
    regular: { row: 36, pad: 12, gap: 12, tile: 22 },
    comfy:   { row: 44, pad: 16, gap: 16, tile: 26 },
  },

  // Map frame variants — exposed via tweaks
  mapFrames: ['inset', 'parchment', 'cartographic', 'floating'],

  // Wordmark variants — exposed via tweaks
  wordmarks: ['flag', 'monogram', 'stamp', 'plain'],
};

// Build CSS variables from a theme set. Returns a string for <style>.
function buildThemeVars(themeName, fontKey, density) {
  const t = PARLEY.themes[themeName];
  const f = PARLEY.fontStacks[fontKey];
  const d = PARLEY.density[density];
  const lines = [
    `--bg:${t.bg}`,
    `--bg-subtle:${t.bgSubtle}`,
    `--surface:${t.surface}`,
    `--surface-alt:${t.surfaceAlt}`,
    `--parchment:${t.parchment}`,
    `--parchment-edge:${t.parchmentEdge}`,
    `--ink:${t.ink}`,
    `--ink-soft:${t.inkSoft}`,
    `--ink-muted:${t.inkMuted}`,
    `--ink-faint:${t.inkFaint}`,
    `--border:${t.border}`,
    `--border-strong:${t.borderStrong}`,
    `--ring:${t.ring}`,
    `--accent:${t.accent}`,
    `--accent-hover:${t.accentHover}`,
    `--accent-soft:${t.accentSoft}`,
    `--accent-ink:${t.accentInk}`,
    `--success:${t.success}`,
    `--warning:${t.warning}`,
    `--destructive:${t.destructive}`,
    `--map-void:${t.mapVoid}`,
    `--tooltip-bg:${t.tooltipBg}`,
    `--tooltip-ink:${t.tooltipInk}`,
    `--font-display:${f.display}`,
    `--font-ui:${f.ui}`,
    `--font-mono:${f.mono}`,
    `--row-h:${d.row}px`,
    `--pad:${d.pad}px`,
    `--gap:${d.gap}px`,
    `--tile:${d.tile}px`,
  ];
  return `:root{${lines.join(';')}}`;
}

// Find a player descriptor by id (or null).
function getPlayer(id) {
  return PARLEY.players.find(p => p.id === id) || null;
}

Object.assign(window, { PARLEY, buildThemeVars, getPlayer });
