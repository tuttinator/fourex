# Parley — Design Brief

A brief intended for use with Claude Design (or a human designer working
alongside it). Covers what Parley is, who it's for, the current visual
state, and the assets we need produced.

---

## 1. What Parley is

**Parley** is a 4X turn-based strategy game (eXplore, eXpand, eXploit,
eXterminate) where humans and AI agents share the same board. Players
found cities, develop economies, fight wars, and negotiate treaties on a
toroidal hex/grid map. The engine is fully deterministic — same seed
plus same actions yields identical outcomes — which makes it usable as a
reproducible research sandbox for AI agent behaviour as well as a game
that real people can play.

Live deployment: **parley.quest**.

The product has three audiences that all use the same UI:

1. **Human players** — joining a lobby, taking a seat, playing turns
   against other humans and/or agents.
2. **Agent developers** — connecting their own MCP-driven agent to a
   seat, watching it play, and inspecting what it did and why.
3. **AI researchers / observers** — watching matches live, scrubbing
   replays, comparing agent decisions across turns.

The "humans and AIs at the same table" framing is the differentiator —
the design needs to make that feel natural rather than like a research
tool with a player veneer bolted on.

## 2. Current state of the UI

Stack: Next.js 15 / React 19 / Tailwind / shadcn-ui (Radix) / TanStack
Query / Pixi.js for the map canvas.

Today the UI is functional but visually generic:

- **Theme** is unmodified shadcn defaults — neutral greys, default
  border radius, no brand colour. See `frontend/src/app/globals.css`.
- **Landing page** (`src/app/page.tsx`) is a stock card grid with
  lucide icons. Title is just the word "Parley" in default type.
- **Game surfaces** (`gameplay-view.tsx`, `pixi-map.tsx`,
  `observation-view.tsx`, `event-log.tsx`, `player-list.tsx`,
  `rules-reference-panel.tsx`, `prompt-accordion.tsx`) all share the
  same neutral chrome.
- **Map sprites** are hand-drawn 32×32 SVG pixel art (CC0). Coverage:
  4 terrains, 4 resources, 4 unit types + per-player tint banner, 3
  city variants + city tint banner, 6 building indicators, 4 worker
  improvements. See `frontend/public/sprites/ATTRIBUTION.md`. The
  resolver in `frontend/src/lib/sprite-atlas.ts` is designed for
  drop-in pack swaps.
- **No logo, favicon, OG image, or marketing art** exists.

The pixel-art map style is something we want to keep and lean into. It
is the only piece of visual identity the product currently has.

## 3. What we want from the design pass

A coherent visual identity that:

- Reads as a **game first, research tool second** — warm, tactile,
  invites you to play. Today it reads as a dashboard.
- Holds up across three very different contexts: a marketing landing
  page, a dense gameplay screen, and a replay/observation view full of
  JSON and prompt logs.
- Extends the existing pixel-art map sprites rather than fighting
  them — the chrome around the map should feel like it belongs to the
  same world.
- Works in **light and dark mode**. The current theme has both; dark
  is likely the primary mode for long observation sessions.
- Stays implementable in **Tailwind + shadcn tokens**. We do not want
  to rip out the component library. Re-skin via CSS variables, not a
  full UI rewrite.
- Supports **up to 8 player colours** that remain distinguishable on
  the map, in the player list, and in event log entries — including
  for common forms of colour blindness.

Tone target: think *Civilization* or *Old World*'s warmth crossed with
the calm density of a good observability tool. Parchment-and-ink rather
than neon-and-glass. Avoid: generic SaaS gradients, Web3 / crypto
aesthetics, AAA sci-fi.

## 4. Out of scope

- Re-architecting the frontend or component library.
- Replacing the pixel-art sprite pack (we may extend it; we are not
  starting over).
- Anything backend, MCP-server, or agent-runtime related.
- Animations beyond simple hover / state transitions.

## 5. Required deliverables

Grouped from highest to lowest priority. A first pass that nails 5.1
through 5.3 is already shippable.

### 5.1 Brand core

- **Wordmark / logo** for "Parley". Two lock-ups: full wordmark, and a
  square mark for favicon / app icon / agent avatars.
- **Colour system** as Tailwind/shadcn CSS variables: background,
  foreground, card, primary, secondary, muted, accent, destructive,
  border, ring — for both light and dark. Plus an explicit
  **8-player palette** that is colour-blind-safe and works on top of
  the four terrain tiles.
- **Type pairing** (display + UI + mono). Must include a monospace for
  the JSON / prompt / event-log views.
- **Iconography direction** — we use `lucide-react` today; either
  confirm that fits, or specify replacements / overrides for game
  concepts (units, cities, resources, diplomacy actions).

### 5.2 Re-skinned key screens (high-fidelity mocks)

In light and dark, desktop-first (≥1280px), with a tablet variant for
the gameplay view:

1. **Landing / marketing page** (`/`) — replaces the current stock
   card layout. Should explain the human-plus-agent premise and lead
   to the lobby.
2. **Lobby / games list** (`/games`) — list of open seats, in-progress
   matches, and finished games; the entry point for both humans
   joining and agents being invited.
3. **Gameplay view** (`/games/[id]`) — the dense screen: Pixi map
   centre, selected-unit / selected-city affordance panel, queued
   orders, end-turn control, event log, rules-reference panel,
   diplomacy controls. This is the screen players spend the most time
   on; it must not feel cramped after re-skinning.
4. **Observation / replay view** — fog-of-war perspective switcher,
   turn timeline scrubber, prompt accordion (LLM reasoning per turn),
   diff highlighting, JSON viewer.
5. **Sign-in** (`/signin`) — minimal but on-brand.

Each mock should call out the shadcn primitives in use so the
implementation is mechanical.

### 5.3 Map chrome

The Pixi map itself stays as pixel art. The chrome around it does not.

- Frame / border treatment for the Pixi canvas.
- Hover tooltip style for tiles, units, cities (currently
  `unit-tooltip` in `globals.css`).
- Selection / valid-move / valid-attack / queued-order highlight
  styles. Today: yellow ring for moves, red ring for attacks,
  `diff-highlight` pulse for diffs — these are placeholders.
- Fog-of-war overlay treatment.
- Mini-map / overview thumbnail style (if introduced).

### 5.4 Sprite extensions (optional, lower priority)

The existing CC0 pack covers the basics but will need to grow as the
ruleset expands. Useful additions, in roughly the order we'll need them:

- 2–3 additional terrain types (desert, hills, swamp).
- 2–3 additional unit types (cavalry, siege, settler-distinct-from-worker).
- Treaty / diplomatic-state icons (alliance, war, ceasefire, trade).
- Per-player heraldry / banner variants beyond a flat colour tint.

Match the existing 32×32 (units/cities/terrain), 16×16 (resources),
10×10 (building indicators), 20×20 (improvements) sizing and the
existing pixel-art style. Deliver as SVG. CC0 or compatible licence so
they can sit next to the current pack.

### 5.5 Marketing surface

- **Favicon** set (16, 32, 180, 512).
- **OG / social card** (1200×630) for the landing page and for
  shareable game links.
- **README hero image** for the GitHub repo.

## 6. Reference points to design *against*

- *Civilization VI* — too cartoonish for us, but the warmth of the
  parchment UI and the readability at zoomed-out scales is the bar.
- *Old World* — closer in spirit. Restrained, literate, takes itself
  seriously without being grim.
- *Linear* / *Vercel dashboard* — calm density we want for the
  observation view, but the sterile coolness is what we're trying to
  avoid in the rest of the product.
- *Anthropic's own marketing site* — type discipline and the comfort
  with whitespace are good influences; the colour palette is too
  corporate for a game.

## 7. Constraints and gotchas worth knowing

- **The map is the product.** Anything that makes the Pixi canvas
  harder to read — heavy chrome, low-contrast overlays, fussy
  borders — is a net loss, no matter how nice it looks in isolation.
- **Per-player colour shows up everywhere.** It tints unit and city
  banner sprites, marks event-log lines, fills the player list, and
  colours diplomatic relationship badges. The 8-colour palette has to
  survive all of these contexts, not just look good in a swatch
  grid.
- **Agents are first-class players.** When an AI takes a seat it
  needs an avatar / identity treatment that sits next to a human
  player's identity without looking second-class or like a system
  message.
- **Replay and live views share components.** A design that only
  works for one will create drift. Treat them as the same surface in
  two states.
- **Accessibility is not optional** — keyboard navigation, ARIA live
  regions for the event stream, and screen-reader-friendly labels are
  already in scope for the frontend.

## 8. What to hand back

A single Figma file (or equivalent) containing:

1. Brand core — wordmark, colour tokens (mapped to shadcn CSS
   variable names), type ramp, 8-player palette swatches with
   contrast checks against each terrain.
2. High-fidelity mocks of the five screens in §5.2, light + dark.
3. Map-chrome component sheet covering the items in §5.3.
4. Exported asset files: SVG wordmark + mark, favicons, OG image,
   any new sprites.
5. A short Loom or written walkthrough explaining the system so an
   engineer can re-skin `globals.css`, the shadcn theme, and
   `pixi-map.tsx` without guessing at intent.
