# Plan: Prototype Rollout Completion

> Source PRD: `plans/prototype-rollout-completion-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: no new product routes; one new dev-only route `/dev/gallery` for the in-repo design-system gallery (gated behind a build-time flag or a path that 404s in production builds).
- **Schema**: no schema changes. This rollout is purely visual / UX. Engine terrain enum + saved-maps schema work is owned by the sibling `map-system-overhaul` PRD.
- **Component library**: the new shared primitives (`Panel`, `Tag`, `Stat`, `StatPair`, `Kbd`) live alongside the existing shadcn primitives in the shared UI directory. They wrap CSS variables introduced in the earlier rollout (`--bg-subtle`, `--surface`, `--ink`/`--ink-soft`/`--ink-muted`, `--accent`/`--accent-soft`, `--parchment-edge`, `--success`/`--warning`).
- **Brand surface**: heraldic 8-player palette and `<Identity>` (`HumanAvatar` / `AgentAvatar`) are the canonical entry points for any new actor-affiliated surface.
- **Map renderer extension model**: PixiMap accepts new optional props (`frameVariant`, `tooltipMode`, ring-palette resolver, optional MiniMap satellite component). All highlight ring colours route through CSS variables, never hard-coded hex.
- **TopBar split**: a server `<TopBarServer>` (calls `auth()`, owns the sign-out server action) wraps a client `<TopBar>` that takes `email`, `signOutAction`, and optional `game` context. Pages render whichever fits their server/client position.
- **Observation surface**: `/games/[id]/observe` and `/games/[id]/replay` are consolidated into a single `<ObservationSurface>` component. The page-level wrapper differs only in TopBar's game-state tag (`live` vs `replay`) and in whether live polling is enabled.
- **Determinism + behaviour preservation**: all queries, mutations, server actions, lobby flows, gameplay logic, and existing test-ids stay identical. Only JSX, classNames, and inline styles change. Existing tests must pass through every phase.
- **Light/dark and frame variants are orthogonal**: variant choice is per call site, not per theme. Theme toggle remains the only user-controlled global visual switch.

---

## Phase 1: Foundation — shared primitives + dev gallery

**User stories**: 32 (Panel primitive), 33 (Tag primitive), 34 (visual gallery), 36 (consolidate duplicated inline JSX)

### What to build

A small, well-tested set of brand-vocabulary primitives that every later phase consumes, plus a single dev-only page that renders every variant of every primitive in isolation. Existing inline copies of the Panel and Tag patterns (currently duplicated across the lobby client and observation view) collapse onto the new primitives in the same phase, so the inventory of inline copies is zero by the end of Phase 1.

The gallery page is a flat React page (no Storybook install) that lives at a dev-only route. It renders: every wordmark variant, every Identity treatment (human + agent), every frame variant placeholder, every Tag tone, every Stat / StatPair sample, the Kbd hint, and a sample Panel with header + action slot. It is the visual contract for everything that follows.

### Acceptance criteria

- [ ] `<Panel>` supports optional title, optional right-aligned action slot, `padded` toggle, `bordered` default.
- [ ] `<Tag>` exposes tones: neutral / accent / success / warning / live / destructive, plus `mono` boolean.
- [ ] `<Stat>` (vertical: display numeral over mono-uppercase label) and `<StatPair>` (horizontal: mono label + tabular value) are exported.
- [ ] `<Kbd>` ships and replaces the inline implementation on the landing page.
- [ ] The lobby client's inline `Panel` and the observation view's inline `Panel` / `Tag` definitions are removed and replaced with imports.
- [ ] `/dev/gallery` renders every variant under both light and dark themes (toggleable in-page).
- [ ] `tsc --noEmit`, `eslint`, and `npm run test -- --run` all pass with no behaviour regressions.

---

## Phase 2: TopBar split + game-detail/replay/diplomacy header swap

**User stories**: 35 (existing tests pass through rebuild), enables phases 6 and 8

### What to build

Split the existing `<TopBar>` (currently a server component using `auth()` + `signOut`) into two pieces: a server-only `<TopBarServer>` that owns the auth/server-action plumbing and a client `<TopBar>` that takes `email`, an imported sign-out server action, and optional `game` context. The lobby page (server) keeps using `<TopBarServer>`. The game-detail page (client), the replay page (client), and the diplomacy page (client) all swap their hand-rolled headers for `<TopBar>`, passing the email down from a thin server shell.

Game state context (`name`, `state` tag, turn / max) is rendered through TopBar's existing `game` prop, which means each subroute gets a consistent header without each page reinventing the chrome.

### Acceptance criteria

- [ ] `<TopBarServer>` wraps `<TopBar>` and is consumed by the lobby page unchanged.
- [ ] `<TopBar>` accepts `email`, `signOutAction`, and optional `game` props and renders identically to the current server variant when wrapped by `<TopBarServer>`.
- [ ] The active/ended branch of the game-detail page renders `<TopBar game={...}>` instead of its hand-rolled header. Diplomacy / replay subroute headers do the same.
- [ ] Sign-out from any page that uses the client `<TopBar>` works end-to-end.
- [ ] Theme toggle remains in the TopBar across all four pages.
- [ ] `tsc`, `eslint`, full test suite pass.

---

## Phase 3: Map renderer chrome + MiniMap component

**User stories**: 7 (tile tooltip), 8 (queued-order ring), 22 (parchment fog), 23 (frame variants), 24 (frame consistency across pages), 25 (parchment fog), 26 (ring CSS vars), 27 (mini-map viewport rectangle + click-to-pan)

### What to build

Extend `<PixiMap>` with the four prototype frame variants (`inset` / `parchment` / `cartographic` / `floating`), an optional parchment tile tooltip, parchment-tinted fog overlay, and CSS-variable-driven highlight rings. Ship a new `<MiniMap>` component as a low-zoom satellite renderer with a viewport-rectangle layer and click-to-pan dispatch. The marketing-side decorative SVG renderer (used on landing + sign-in) gains the same frame-variant chrome via a thin shared wrapper so every map surface in the app — Pixi or static — looks like part of one system.

The mini-map is wired into the observation map panel as the Phase 3 demo target. Wiring it into the gameplay left rail happens in Phase 4 alongside the rest of the gameplay sidebar work.

### Acceptance criteria

- [ ] `<PixiMap>` accepts `frameVariant: 'inset' | 'parchment' | 'cartographic' | 'floating'` (default `'inset'`) and `tooltipMode: 'parchment' | 'off'` (default `'parchment'`).
- [ ] All four frame variants render correctly side by side on `/dev/gallery`.
- [ ] Tile-hover tooltip shows mono `(x, y)` plus owning unit / city, positioned above cursor, dismissed on mouseleave.
- [ ] Fog of war renders as a parchment-tinted mask (not flat black) with a low-opacity cross-hatch SVG pattern.
- [ ] Selection / valid-move / valid-attack / queued-order ring colours are sourced from CSS variables.
- [ ] `<MiniMap>` renders the full board at low zoom inside a `floating` frame, overlays a viewport rectangle that tracks parent map zoom + pan, and dispatches click-to-pan back to the parent.
- [ ] `<MiniMap>` is rendered inside the observation view's map panel as the integration smoke.
- [ ] The static decorative map renderer (landing / sign-in) accepts the same `frameVariant` prop via a shared wrapper.
- [ ] Existing pixi-map / observation tests pass.

---

## Phase 4: Gameplay sidebar — unit/city/rules/submission + resource bar + mini-map dock

**User stories**: 1 (unit panel slab title + tabular stats), 2 (action buttons share visual rank), 3 (consistent panel header strip), 4 (resource bar glyphs + mono +delta), 5 (End Turn = only accent button), 6 (mini-map docked in left rail), 8 (queued-order ring)

### What to build

Rebuild the gameplay sidebar around the new `<Panel>` / `<Stat>` / `<Tag>` primitives. UnitPanel, CityPanel, RulesContent, and SubmissionRoster all become Panel-pattern surfaces with mono-uppercase headers, slab numerals on stats, and flat-rank action buttons (no primary highlighting). The Resource bar at the top of the gameplay view becomes a row of glyph + tabular numeral + mono `+delta` chips matching the prototype. The "End Turn" button is the only accent-coloured affordance in the sidebar.

The mini-map shipped in Phase 3 docks into a new gameplay left rail, becoming a permanent navigation aid.

### Acceptance criteria

- [ ] UnitPanel renders as `<Panel title="Selection">` with display-font unit name, mono `kind · (x, y)` subtitle, a `<StatPair>` grid for HP / Moves / Atk / Def, and a flat row of default-variant action buttons.
- [ ] CityPanel mirrors UnitPanel's structure with the city's build queue, garrison roster, and trainable / buildable lists living inside child Panels.
- [ ] RulesContent renders as `<Panel title="Rules · selected">` with display-font entity name and a Tag-driven cost line.
- [ ] SubmissionRoster renders as a Panel with one row per player, using `<Identity>` and a state Tag (`submitted` / `deciding`).
- [ ] The resource bar uses the prototype's glyphs, slab-tabular numerals, and mono green `+delta` indicators.
- [ ] The End Turn button is the only `accent`-coloured button visible in the gameplay sidebar.
- [ ] A docked mini-map appears in a new gameplay left rail and reflects pan/zoom of the main map.
- [ ] All 25 existing gameplay-view tests pass; no test-id changes.

---

## Phase 5: Tech tree panel rebuild

**User stories**: 3 (panel header consistency, subset)

### What to build

Restructure TechTreePanel and TechGroup around `<Panel>` and `<Stat>`. Each tech group becomes a sub-Panel; each tech row uses the prototype's mono-uppercase label + display-font name + Tag-driven status (`researched` / `available` / `locked`) treatment. Active research progress shows as a slab numeral progress fraction with a mono-coloured progress bar.

Tech-tree behaviour is unchanged — clicking an available tech still queues the research action through the existing mutation.

### Acceptance criteria

- [ ] TechTreePanel renders as `<Panel title="Research">` with the active-research progress strip at the top.
- [ ] Each tech group is a child Panel with the group name as a kicker.
- [ ] Each tech row uses the prototype's stat + Tag idiom; status tones map cleanly onto the existing tech states.
- [ ] Research-target click handler is unchanged; existing tech-related tests pass.

---

## Phase 6: Diplomacy — sidebar panel + `/diplomacy` route

**User stories**: 28 (per-thread Panel with Identity header), 29 (mono numerals + +/− pills on resource inputs), 30 (relationship Tag tones), 31 (unread badge as accent-soft Tag)

### What to build

Rebuild DiplomacyPanel (in the gameplay sidebar) and the standalone `/games/[id]/diplomacy` route around the new primitives. Each opponent thread becomes a Panel whose header carries that opponent's `<Identity>`. ProposalCard, ProposeTreatyForm, DiplomacyThreadView, and ResourceInputs adopt the prototype's vocabulary: mono numerals, `+/−` pills for resource amounts, Tag-driven relationship state (peace=success, alliance=accent, war=destructive, ceasefire=warning), accent-soft unread badges.

The standalone diplomacy route gains the new `<TopBar>` from Phase 2 with the appropriate game-state tag.

### Acceptance criteria

- [ ] DiplomacyPanel in the gameplay sidebar renders one Panel per opponent thread with Identity in the header.
- [ ] ProposalCard renders as a sub-Panel inside the thread Panel with mono terms (turns / resources) and Tag-tone accept/reject buttons.
- [ ] ProposeTreatyForm's resource-input grid uses tabular mono numerals and prototype-style `+/−` pill controls.
- [ ] Relationship state (peace / alliance / war / ceasefire) renders as a single Tag with the matching tone, used in both the panel and the thread Panel header.
- [ ] Unread badges use `accent-soft` Tag styling.
- [ ] `/games/[id]/diplomacy` route renders with the new `<TopBar>` and shares the same Panel structure as the in-game DiplomacyPanel.
- [ ] All existing diplomacy-related tests and behaviours pass.

---

## Phase 7: Waiting room rebuild

**User stories**: 9 (slot rows with Identity), 10 (agent-key + MCP-config Panels), 11 (Actions Panel), 12 (redeem CTA Panel), 13 (slot edit form nests in row), 14 (lobby header metadata as StatPair)

### What to build

Restructure the waiting branch of the game-detail page around the new primitives. Player slots become Panel rows with `<Identity>` and heraldic colour. Agent keys, MCP-config hint, redeem-needs-signin CTA, and the slot key copy panel each become Panel instances. Join / Leave / Start consolidate into a single `<Panel title="Actions">` with the End-turn-style primary button. The seed / map dimensions / created-at strip becomes a horizontal `<StatPair>` row inside the lobby header Panel.

The slot-edit and slot-invite flows continue to nest inside the slot row's Panel; the existing test-ids and data-flow are preserved.

### Acceptance criteria

- [ ] Player slot list renders inside `<Panel title="Players · N/M">` with one row per slot using `<Identity>` and slot index in mono.
- [ ] Agent-keys, MCP-config, redeem-CTA panels are all Panel instances; the MCP-config-hint kicker is in accent.
- [ ] Slot edit / invite forms render inline within their slot row's Panel; `lobby-slot-{i}-edit` / `lobby-slot-{i}-invite` test-ids remain.
- [ ] Join / Leave / Start consolidate into `<Panel title="Actions">`; the primary button uses End-turn styling.
- [ ] Lobby header metadata (seed / dimensions / created-at) renders as a horizontal StatPair row.
- [ ] All Phase 2-5 lobby behaviours (join, leave, slot reconfigure, agent-key copy, regenerate, invite, redeem, archive) work end-to-end.
- [ ] All existing waiting-room tests and data-testids pass.

---

## Phase 8: Observation surface — scrubber, prompt accordion, JSON diff + replay consolidation

**User stories**: 15 (scrubber under map), 16 (scrubber drives state refetch), 17 (Prompt tab with 4 sections), 18 (god-mode empty state for Prompt), 19 (event ticks coloured by kind), 20 (JSON diff tab), 21 (replay parity with observation)

### What to build

Add a new `<Scrubber>` Panel under the observation map (range slider with event ticks coloured by event kind, current-turn label in mono, prev / play / next controls). Reorder the side-panel tabs to: Prompt / JSON / Players / Events / Stats. Build `<PromptAccordion>` with the four prototype sections (`observe()` / `available tools` / `reasoning` / `action`) populated from the per-turn prompt snapshot, with graceful per-section degradation when fields are missing. Build `<JsonView>` showing the diff between the previous turn's state and the scrubber-selected turn, with insertions/deletions tinted in success/destructive overlays.

Consolidate `/games/[id]/replay` and the active/ended branch of `/games/[id]/observe` (and the embedded observation in game-detail) onto a single `<ObservationSurface>` component. The wrapping page only differs in the TopBar's game-state tag (`live` vs `replay`) and in whether live polling is enabled.

### Acceptance criteria

- [ ] `<Scrubber>` Panel renders below the map with a range slider, prev / play / next buttons, and event ticks coloured by event kind.
- [ ] Dragging the scrubber drives both the map and side panel queries to fetch state for that turn (not the live turn).
- [ ] Side-panel tabs are: Prompt / JSON / Players / Events / Stats (in that order). The Prompt tab is gated to perspectives with a recorded prompt; god-mode renders the empty state.
- [ ] `<PromptAccordion>` renders the four prototype sections; missing fields render an empty placeholder per section rather than blocking the tab.
- [ ] `<JsonView>` renders a per-turn state diff with success-tinted insertions and destructive-tinted deletions.
- [ ] `<ObservationSurface>` is consumed by both `/games/[id]/observe` and `/games/[id]/replay`. The replay page disables live polling and changes the TopBar tag to `replay`.
- [ ] Live observation continues to poll every `ACTIVE_POLL_INTERVAL` only when the scrubber is at the latest turn; scrubbing back pauses live polling until the scrubber returns to the latest turn.
- [ ] All existing observation, perspective-switcher, prompt-accordion, and replay tests pass.
- [ ] Manual review confirms identical behaviour and visual treatment between live observation and replay across both light and dark themes.
