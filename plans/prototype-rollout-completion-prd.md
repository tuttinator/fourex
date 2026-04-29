# Prototype Rollout — Completion PRD

## Problem Statement

Roughly half of the Parley prototype has been translated into production: the design tokens, fonts, brand components, landing page, sign-in, lobby table, theme toggle, and the chrome of the observation/gameplay views. The dense interior surfaces still ride on the original stock-shadcn cards stacked on top of each other — they pick up the new oklch tokens through the theme but do not yet show the prototype's parchment-Panel idiom: mono-uppercase header strips on a `bg-subtle` background, slab-serif numerals for stats, accent kicker labels, heraldic Identity treatment for actors.

Specifically, today the user-visible gaps are:

- **Gameplay sidebar.** UnitPanel, CityPanel, TechTreePanel, DiplomacyPanel, ProposalCard, ProposeTreatyForm, SubmissionRoster, and RulesContent all render as plain shadcn `Card` stacks. The "End Turn" button is one of several primary-coloured affordances rather than the only accent action. Action buttons compete visually with the action they sit next to.
- **Lobby waiting room.** Player slots, agent-key handoff, MCP-config hint, redeem-CTA, and the actions row all use loose `Card` blocks with no header rhythm and no Identity treatment.
- **Map renderer.** PixiMap exposes no frame variants (the prototype defines four: inset / parchment / cartographic / floating), no tile-hover tooltip, no parchment-tinted fog overlay, and no mini-map. Selection / valid-move / valid-attack / queued-order rings are still hard-coded colour values rather than CSS variables.
- **Observation view.** Lacks the prototype's turn-timeline scrubber and the four-section prompt accordion (`observe()` / `available tools` / `reasoning` / `action`). Replay sits on a separate route with its own ad-hoc styling.
- **Diplomacy route.** Has not been touched in the rebrand.

The result is a UI with two visual languages: the new identity outside (landing, lobby, signin), the old generic dashboard inside (anywhere a player or observer spends real time). The product still reads as "research tool with a brand veneer" rather than "game first."

The map *system* itself — terrain enum, generator, saved maps, admin role, sprite/atlas alignment — is being addressed in a sibling PRD at `plans/map-system-overhaul-prd.md`. This PRD is purely the visual/UX completion of the prototype rollout, on top of whatever terrain set the engine ends up exposing.

## Solution

Finish the prototype translation in a single coherent pass:

1. **Rebuild interior panels to the prototype's minimal idiom.** UnitPanel, CityPanel, TechTreePanel, DiplomacyPanel, the waiting-room cards, ProposalCard, and the diplomacy thread view all become Panel-pattern surfaces (mono-uppercase header strip on `bg-subtle`, slab-serif numerals for stats, accent kicker labels, heraldic Identity for actors). Functionality stays — the JSX/styling is rewritten; the queries, mutations, props, and test-ids do not change.

2. **Add a unified map chrome system.** PixiMap gains a `frameVariant` prop with all four prototype options (`inset`, `parchment`, `cartographic`, `floating`) controlling the surrounding border, corner ornaments, and bleed. Tile hover surfaces a brand-styled mono pill tooltip. Fog of war renders as a parchment-tinted mask. A new `<MiniMap>` component (a low-zoom PixiMap derivative with a viewport-rectangle indicator and click-to-pan) ships in the gameplay left rail and on the observation map panel.

3. **Wire scrubber + prompt accordion into observation.** The observation view gains the prototype's turn-timeline scrubber (range slider with per-event ticks coloured by event kind, plus prev / play / next buttons) and the four-section prompt accordion. Existing turn-history endpoints feed the scrubber. The accordion reads from existing per-turn prompt-snapshot data and degrades per-section if a field is missing.

4. **Restyle `/replay` and `/diplomacy` subroutes.** Both pick up the new TopBar shell, the Panel idiom, and the matching scrubber / accordion components. The replay surface is consolidated with the live observation surface so they share a single source of truth.

The brand kit `/brand` page from the prototype is intentionally skipped — engineers can read source for the design system; we do not surface it in production.

## User Stories

### Players (gameplay)

1. As a player taking a turn, I want the unit-selection panel to lead with the unit's name in slab serif and core stats in tabular numerals, so the panel reads like a command sheet rather than a form.
2. As a player, I want the buttons under the unit panel ("Move", "Attack", "Hold", "Fortify", "Found city", "Build improvement") to share a single visual rank with no "primary" colour competing with End Turn, so I am not pulled toward an action by chrome alone.
3. As a player, I want every panel I open in the sidebar (unit, city, tech, diplomacy) to use the same mono-uppercase header strip on a parchment background, so I navigate the sidebar by header recognition.
4. As a player, I want the resource bar at the top of the gameplay view to show flat colour glyphs (food / wood / ore / crystal) sized to match the prototype, with `+delta` in mono green, so I can read stockpile and income at a glance without parsing icons.
5. As a player, I want the "End Turn" button to be the only `accent`-coloured affordance in the gameplay sidebar, so the turn-flow primary action is unambiguous.
6. As a player, I want a mini-map docked in the gameplay left rail showing the whole board with a viewport rectangle, so I can see relative positions without zooming out.
7. As a player hovering a tile, I want a tooltip showing `tile (x, y)` in mono on a parchment pill, plus any owning unit or city on that tile, so I get tile facts without opening a full panel.
8. As a player whose unit has a queued multi-turn order, I want the queued-order destination + path on the map to render in the same warning-tinted ring as the prototype, so an active queue is unmistakable next to live moves and attacks.

### Players (lobby waiting room)

9. As a lobby creator, I want each player slot to render as a Panel row with the heraldic seat colour and the agent/human Identity treatment, plus the slot index in mono, so the slot list reads like the prototype's seat array.
10. As a lobby creator, I want the agent-key panel and the MCP-config-hint panel to share the Panel idiom (mono-uppercase header on a parchment strip, accent kicker for "configure your MCP client"), so they sit visually with the rest of the lobby instead of standing out as bright cards.
11. As a lobby creator, I want the "Join lobby" / "Start game" / "Leave lobby" buttons grouped in a single Panel labeled "Actions" with the End-turn button styling, so I always know where the active controls live.
12. As an invited player, I want the redeem-needs-signin CTA to use the parchment Panel + accent kicker treatment, so it does not feel like an error message.
13. As a lobby creator, I want the slot-edit form (type human/agent, name, invite email) to nest inside the same row's Panel rather than expanding into a separate card, so my visual focus stays anchored on the slot I'm editing.
14. As a lobby creator, I want the seed / map dimensions / created-at metadata strip to use mono labels and tabular values, so the room reads as a deterministic-game artefact, not a marketing card.

### Observers / replays

15. As an observer, I want a turn timeline scrubber under the map showing the current turn, a prev / play / next button trio, and small ticks marking event-bearing turns, so I can skip to interesting moments at a glance.
16. As an observer dragging the scrubber, I want the map and side panels to refetch state for that turn (not the live turn), so I can scrub history during a live game without losing my place.
17. As an observer with a player perspective selected, I want a "Prompt" tab on the side panel showing the four prototype sections (`observe()` / `available tools` / `reasoning` / `action`) populated from that turn's saved prompt, so I can audit the agent's decision.
18. As an observer in god-mode without a perspective, I want the Prompt tab to render an empty state ("select a player perspective to view their prompt") rather than disappearing, so the IA stays consistent across modes.
19. As an observer, I want the scrubber's event ticks coloured by event type (move / attack / found / treaty / turn-resolved), so the timeline reads as a story.
20. As an observer, I want a "JSON" tab next to "Prompt" showing the diff between the previous and current turn's state, with insertions and deletions tinted, so I can see what changed without reading prose.
21. As an observer in replay mode (status=ended), I want the same scrubber + tabs available with no live polling, so the surface is identical to mid-game observation.
22. As an observer, I want the same observation surface to drive both the live observe page and the replay page, so I do not learn a different UI for finished games.

### Map chrome (everywhere)

23. As any user, I want the map renderer to support all four frame variants (`inset` / `parchment` / `cartographic` / `floating`), so a page picks the treatment that fits its density.
24. As any user, I want the lobby's marketing map preview, the gameplay map, the observation map, the mini-map, and the sign-in decorative map to share the renderer's frame system, so the map looks like one consistent piece across the app.
25. As any user, I want fog of war to render as a parchment-tinted overlay (not flat black), so unexplored tiles still feel like part of the map.
26. As any user, I want unit / city / valid-move / valid-attack / queued-order ring colours to come from CSS variables, so the look survives a future theme change.
27. As any user, I want the mini-map's viewport rectangle to track my main-map zoom and pan in real time and to accept clicks for jump-to, so it is a genuine navigation aid not just a decoration.

### Diplomacy

28. As a player on the diplomacy page, I want each opponent thread rendered as a Panel with their Identity in the header strip, so I always know whose conversation I'm reading.
29. As a player composing a treaty, I want the proposal form's resource-input grid to use mono numerals and the same `+/−` pill controls as the resource bar, so the form reads like the rest of the gameplay UI.
30. As a player viewing a peace / war / alliance state, I want the relationship to render as a single Tag with the matching tone (success / destructive / accent), so the state is legible from any panel.
31. As a player who has just received a treaty proposal, I want the unread badge on the diplomacy tab to use the accent-soft Tag, so I can tell at a glance whether anything needs my attention.

### System / cross-cutting

32. As a developer, I want a single `<Panel>` primitive (parchment header strip, optional title, optional action slot, optional `padded={false}`) to live in the shared UI directory, so I am not redefining it inline in each surface.
33. As a developer, I want a single `<Tag>` primitive consolidating the inline-tag pattern (tones: neutral / accent / success / warning / live / destructive), so tone changes propagate by changing one file.
34. As a designer, I want the four prototype frame variants and the four prototype wordmark variants exposed in isolated visual states (storybook-style page or in-repo gallery), so I can verify a new surface picks the right combination without standing up the live game.
35. As an operator, I want the existing component test suite (lobby, gameplay-view, observation, perspective-switcher, prompt-accordion, replay) to keep passing through the rebuild, so we ship without behaviour regressions.
36. As a maintainer, I want the consolidation of duplicated inline `Panel` / `Tag` JSX (currently copy-pasted across three or four files) into shared primitives, so the next surface I touch isn't another round of copy-paste.

## Implementation Decisions

### Shared primitives

- A new `<Panel>` component becomes the canonical container: optional mono-uppercase title on a `bg-subtle` header strip, optional right-aligned action slot, optional `padded={false}` for table / list contents, and a `bordered` default. Existing inline copies (in the lobby client, observation view, and the in-progress refactors of the gameplay sidebar) collapse into this primitive.
- A new `<Tag>` component consolidates the repeated tone-styled span. Tones cover all the prototype's variants plus `destructive`. Replaces inline tag implementations across lobby, observation, gameplay, and the diplomacy route.
- A new `<Stat>` (display-font numeral over mono-uppercase label, vertical stack) and `<StatPair>` (label + tabular value, horizontal) for the unit / city / research stat grids, the resource bar, and the lobby map metadata strip.
- A new `<Kbd>` primitive for keyboard-shortcut hints (currently inlined on the landing page).
- A `<RingPalette>` configuration object (consumed by pixi-map) ties highlight ring colours to CSS variables, so the renderer reads them through a single resolver.

### Interior panel rebuild

- `UnitPanel`, `CityPanel`, `TechTreePanel`, `DiplomacyPanel`, `ProposalCard`, `ProposeTreatyForm`, `SubmissionRoster`, and `RulesContent` are rebuilt around `<Panel>` and `<Stat>`. The existing logic, queries, mutations, and props stay unchanged — the JSX/styling is rewritten.
- Per-entity headers carry an `<Identity>` (for player-affiliated panels) or a small terrain/sprite glyph (for tile/unit panels).
- Action buttons in unit / city panels render as a flat row (default-variant buttons per the prototype). No primary highlighting on action buttons.
- The "End Turn" button is the only `accent`-coloured affordance in the gameplay sidebar.
- Information density is preserved — anywhere the prototype's minimal sketch does not show a state the real game needs (e.g. queued-order indicator, automation badge, build queue, treaty list), the missing state borrows existing Panel / Tag vocabulary rather than inventing new visual language.

### Waiting room

- The slot list in the waiting branch of the game-detail page is restructured into a `<Panel title="Players · N/M">` containing slot rows. Each row uses `<Identity>` plus heraldic colour. Edit / invite / agent-key flows keep their existing test-ids and data-flow but render inline within the row using the same Panel idiom.
- Agent-keys, MCP-config hint, redeem-needs-signin CTA, and the slot-key copy panel become `<Panel>` instances. The "Configure your MCP client" header strip uses the accent kicker.
- Join / Leave / Start consolidate into a single `<Panel title="Actions">` row with the End-turn-style primary button.
- The seed / map dimensions / created-at strip becomes a horizontal `<StatPair>` row inside the lobby header Panel.

### Map renderer

- New prop on `<PixiMap>`: `frameVariant: 'inset' | 'parchment' | 'cartographic' | 'floating'` (default `'inset'`).
  - `inset`: 1px parchment-edge inner ring, current behaviour as the baseline.
  - `parchment`: a wider warm border with a subtle paper-grain background fill in the surrounding chrome and small SVG corner ornaments.
  - `cartographic`: hairline double border plus ruled tick marks along the inside of the frame.
  - `floating`: no border, soft drop shadow, inset 1px `border-strong`.
- New prop: `tooltipMode: 'parchment' | 'off'` (default `'parchment'`). Renders a brand tile tooltip on hover (mono `(x, y)` + owning entity), positioned above the cursor.
- Fog-of-war overlay tint changes from flat dark to a `oklch(from var(--map-void) l c h / 0.65)` mask layered with a low-opacity parchment cross-hatch SVG pattern.
- Selection / valid-move / valid-attack / queued-order ring colours move to CSS variables (`--ring-accent`, `--ring-success`, `--ring-warning`, `--ring-info`) consumed via the new `RingPalette` resolver.
- A new `<MiniMap>` React component wraps PixiMap at very low zoom with `frameVariant="floating"`. It overlays a viewport rectangle that tracks the parent map's zoom + pan, dispatches click-to-pan events back to the parent, and is consumed in the gameplay left rail and the observation map panel.
- The marketing-side decorative map on the landing page and sign-in page is not migrated to PixiMap (those pages have no Pixi dependency); they keep their static SVG decorative renderer but gain the same frame-variant chrome via a thin shared wrapper component.

### Observation view

- The status strip extends with a small per-turn unit/city delta indicator in mono.
- Below the map, a new `<Scrubber>` Panel is added: range slider with event ticks coloured by event kind, current-turn label in mono, prev / play / next controls.
- Side panel tabs change to: Prompt / JSON / Players / Events / Stats. Prompt is gated to perspectives with a recorded prompt; in god mode it renders the empty state.
- Event ticks coloured by the existing event types (move, attack, found, treaty, turn-resolved, spawn, tech).
- Scrubber state is hoisted into `useState` and drives both the map (via existing turn-snapshot endpoint) and the side panel queries (so a scrubbed turn shows that turn's prompt + diff).

### Replay route

- `/games/[id]/replay` is restructured to use the same `<Scrubber>` + prompt accordion + JSON view + Panels. The page becomes a thin wrapper around a shared `<ObservationSurface>` component used by both live observation and replay; the only difference is the TopBar's game-state tag (`replay` vs `live`).
- Existing replay-specific tests are preserved by keeping the data flows and test-ids.

### Diplomacy route

- `/games/[id]/diplomacy` rebuilds around `<Panel>` per opponent thread. Each thread Panel header carries the opponent's `<Identity>`. Proposal / respond surfaces use the prototype's Tag + Resource pill idiom for resource amounts. The unread badge uses the accent-soft Tag.

### TopBar usage on game-detail subroutes

- `<TopBar>` is split into a server-only `<TopBarServer>` (auth + signOut server action) and a client `<TopBar>` taking `email`, an imported sign-out server action, and optional `game` context. This unblocks consumption of `<TopBar>` from client-component pages (game-detail, replay, diplomacy).
- The active/ended branch of the game-detail page swaps its hand-rolled header for the client `<TopBar>`. Replay and diplomacy pages do the same with appropriate game-state tags.

### Tests

- Existing tests (lobby, gameplay-view, observation, perspective-switcher, prompt-accordion, replay) must keep passing; behaviour is unchanged. Where a test asserts on tag/badge text, the rebuild preserves the same text (e.g. "Agent vs Agent", "Resume", "Observe", "View Lobby", "Sign in to observe").
- New `<Panel>` / `<Tag>` / `<Stat>` primitives ship with smoke tests for the variants the rest of the app depends on.
- New visual smoke checks: a single in-repo gallery page (admin-only or behind a `/dev/gallery` route) renders each frame variant, each wordmark variant, the Panel and Tag tones, and the Identity treatments side by side. Not a Storybook install — just a flat React page. Verified by hand during PR review.

### Out-of-the-prototype additions

- The mini-map's viewport rectangle and click-to-pan are not in the prototype but are a natural prototype-faithful extension.
- The Prompt tab's four-section structure is from the prototype; if existing prompt-snapshot data uses a different shape, the tab maps the existing fields onto the four sections, and any section the snapshot does not carry renders an empty placeholder.

## Out of Scope

- Engine terrain enum work, map generator templates, saved maps, admin role: covered by `plans/map-system-overhaul-prd.md`. This PRD assumes that work either ships first or in parallel and that PixiMap will receive whatever terrain shape the engine eventually exposes.
- Brand kit page (`/brand` in prototype): intentionally not surfaced in production.
- Authentication / Auth.js plumbing changes (other than the TopBar split mentioned above).
- Logs / demo / debug routes (`/logs`, `/demo`): out of scope; they remain as-is until they have a real product role.
- Light/dark palette tweaks: the existing oklch palette stands; no new tokens introduced.
- Mobile-specific breakpoints beyond the existing `md:` reflows in landing and lobby. Gameplay / observation / replay / diplomacy stay desktop-first (≥1280px) per the design brief.
- New animations beyond hover/focus transitions and the existing `parley-pulse` keyframe.
- Audio / sound design.
- Pixi.js renderer rewrite. Only the chrome around the canvas and the highlight-ring palette change; sprite drawing remains as-is.
- Scrubber + prompt accordion data-source changes. This PRD assumes existing turn-snapshot and per-turn prompt endpoints are sufficient; if they are not, that gap becomes a follow-up backend ticket.
- Storybook / Chromatic / visual-regression tooling. The in-repo gallery page is the only structured visual surface added.
- Per-user customisation of frame variant or Panel density. Variant choice is per-page, not per-user.

## Further Notes

- **Prototype faithfulness vs production density.** The prototype's UnitPanel is a single-state illustration; the real game has dozens of buildable / queueable / contextual states. The rebuild keeps the prototype's *visual rank* (mono kicker, slab title, flat secondary buttons, single accent only on End Turn) but does not flatten the information density. If a state the prototype doesn't show needs a tag or callout, it borrows the same Tag / Panel vocabulary rather than inventing a new one.
- **Map chrome variants are component-level, not theme-level.** A page picks the variant at the call site; the variant does not change globally with light / dark mode. Light/dark continues to be controlled by the existing `<ThemeToggle>`.
- **Scrubber + prompt accordion will surface data quality issues.** The first time the prompt accordion points at saved prompts, gaps will likely surface (turns where reasoning was not captured, schema mismatches, length issues). These should be addressed by making the accordion gracefully degrade per-section, not by blocking the rollout.
- **Visual-only changes are the dominant test risk.** Most of this work is JSX / style. Type-check, eslint, and the existing component tests catch behaviour regressions but not visual ones. Reviewers should walk all five primary surfaces (landing, lobby, gameplay, observation, replay/diplomacy) under both `light` and `dark` themes before merging.
- **Decoupling from map-system-overhaul.** Where PixiMap changes here intersect with sprite/terrain changes there, the renderer prop additions in this PRD (`frameVariant`, `tooltipMode`, fog overlay, ring CSS vars, mini-map) are independent of the terrain enum. Both PRDs can land in either order; the consolidating PR is the one that lands second.
- **Future hooks.** A `<PromptAccordion>` that currently reads from per-turn snapshots is a natural place to later attach live in-progress reasoning streams (an agent's open-window thinking before they submit). The data shape for live and saved is identical, so wiring the live socket later is purely additive.
- **Why one PR.** The rebuild touches enough surfaces (sidebar panels + map renderer + observation tabs + replay + diplomacy + waiting room) that splitting into many small PRs risks visible "half-translated" intermediate states. A single PR landed behind a feature flag (or just landed cleanly during a quiet window) is preferable to a crawl through a dozen merges that each leave the UI partially in the old style.
