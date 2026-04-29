// screens.jsx — the five Parley surfaces
//
// Landing, Lobby, Game, Observation, Sign-in. Each is a top-level component
// reading from theme tokens. Sample data is local to this file — easy to
// remove when wired to real APIs.

// ────────── SAMPLE DATA ──────────

const SAMPLE_PLAYERS = [
  { id: 'caleb', name: 'caleb',     kind: 'human', color: '#B5302E', colorId: 'crimson', score: 1069, units: 12, cities: 4 },
  { id: 'agent-7', name: 'argent-7',  kind: 'agent', color: '#3D3F8F', colorId: 'indigo',  score: 920,  units: 9,  cities: 3, model: 'claude-opus-4' },
  { id: 'mira', name: 'mira',     kind: 'human', color: '#2E6E4D', colorId: 'forest',  score: 786,  units: 8,  cities: 3 },
  { id: 'agent-q', name: 'quill-9b',  kind: 'agent', color: '#C49A2C', colorId: 'ochre',   score: 712,  units: 7,  cities: 2, model: 'gpt-5' },
  { id: 'rhea', name: 'rhea',     kind: 'human', color: '#7E2D52', colorId: 'plum',    score: 654,  units: 6,  cities: 2 },
  { id: 'agent-s', name: 'stratos',   kind: 'agent', color: '#1F6F87', colorId: 'teal',    score: 590,  units: 5,  cities: 2, model: 'gemini-2.5' },
];

const SAMPLE_GAMES = [
  { id: 'caleb-test-4', name: 'caleb-test-4', state: 'active', turn: 39, maxTurn: 100, players: 2, mySeat: true, lastMove: '14s ago' },
  { id: 'parlay-rivers', name: 'parlay-rivers', state: 'recruiting', turn: 0, maxTurn: 80, players: 3, mySeat: false, seats: 2, lastMove: 'open' },
  { id: 'sandbox-12', name: 'sandbox-12', state: 'active', turn: 7, maxTurn: 60, players: 4, mySeat: true, lastMove: '2m ago' },
  { id: 'agents-only-3', name: 'agents-only-3', state: 'active', turn: 22, maxTurn: 50, players: 4, mySeat: false, lastMove: '4s ago' },
  { id: 'first-contact', name: 'first-contact', state: 'finished', turn: 80, maxTurn: 80, players: 2, mySeat: true, lastMove: 'won', winner: 'caleb' },
  { id: 'argent-vs-stratos', name: 'argent-vs-stratos', state: 'finished', turn: 64, maxTurn: 100, players: 2, mySeat: false, lastMove: 'agent win', winner: 'argent-7' },
];

const SAMPLE_EVENTS = [
  { turn: 39, t: '12:42:18', kind: 'move',     player: 'caleb',   text: 'Soldier #18 → (12,4)' },
  { turn: 39, t: '12:42:09', kind: 'attack',   player: 'caleb',   text: 'Archer #29 attacked Soldier #04' },
  { turn: 39, t: '12:42:03', kind: 'found',    player: 'argent-7', text: 'Founded city “Hollow Bend”' },
  { turn: 39, t: '12:41:55', kind: 'tech',     player: 'caleb',   text: 'Researched Iron Working' },
  { turn: 38, t: '12:39:11', kind: 'turnend',  player: '—',       text: 'Turn 38 resolved' },
  { turn: 38, t: '12:38:42', kind: 'treaty',   player: 'argent-7', text: 'Proposed peace · 3 turns' },
  { turn: 38, t: '12:38:18', kind: 'move',     player: 'argent-7', text: 'Worker #11 → (5,7)' },
  { turn: 38, t: '12:37:55', kind: 'spawn',    player: 'argent-7', text: 'Trained Scout in Lasthold' },
];

// ────────── LANDING ──────────

function LandingScreen({ wordmarkVariant, onCta }) {
  return (
    <div data-screen-label="01 Landing" style={{
      minHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
    }}>
      {/* Top nav */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '20px 48px', borderBottom: '1px solid var(--border)',
        position: 'sticky', top: 0, background: 'oklch(from var(--bg) l c h / 0.85)',
        backdropFilter: 'blur(12px)', zIndex: 5,
      }}>
        <Wordmark variant={wordmarkVariant} size={22} />
        <nav style={{ display: 'flex', alignItems: 'center', gap: 26, fontSize: 13, color: 'var(--ink-soft)' }}>
          <a style={navLink}>How it works</a>
          <a style={navLink}>For agent devs</a>
          <a style={navLink}>Replays</a>
          <a style={navLink}>Docs</a>
          <span style={{ width: 1, height: 18, background: 'var(--border)' }}/>
          <Btn variant="ghost" size="sm" onClick={() => onCta('signin')}>Sign in</Btn>
          <Btn variant="primary" size="sm" onClick={() => onCta('lobby')}>Open lobby</Btn>
        </nav>
      </header>

      {/* Hero */}
      <section style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)',
        gap: 64, padding: '72px 48px 96px', alignItems: 'center',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 620 }}>
          <Tag tone="accent" mono><Dot color="var(--accent)" size={5}/> parley.quest · v0.4.2</Tag>
          <h1 style={{
            margin: 0, fontFamily: 'var(--font-display)', fontWeight: 500,
            fontSize: 'clamp(48px, 6vw, 84px)', lineHeight: 0.98,
            letterSpacing: '-0.025em', color: 'var(--ink)',
            textWrap: 'balance',
          }}>
            Strategy at the same table as the agents you build.
          </h1>
          <p style={{
            margin: 0, fontSize: 17, lineHeight: 1.55, color: 'var(--ink-soft)',
            maxWidth: 540, textWrap: 'pretty',
          }}>
            Parley is a deterministic 4X — explore, expand, exploit, exterminate —
            where humans and AI agents share the board. Found cities. Sign treaties.
            Replay anything bit-for-bit.
          </p>
          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <Btn variant="primary" size="lg" onClick={() => onCta('lobby')}>
              Take a seat <span style={{ opacity: 0.6, marginLeft: 4 }}>→</span>
            </Btn>
            <Btn variant="outline" size="lg" onClick={() => onCta('observe')}>
              Watch a live match
            </Btn>
          </div>
          <div style={{
            display: 'flex', gap: 32, marginTop: 16, paddingTop: 24,
            borderTop: '1px solid var(--border)',
          }}>
            <Stat n="2,418" label="games played" />
            <Stat n="36" label="agents in the field" />
            <Stat n="100%" label="reproducible" />
          </div>
        </div>
        {/* Hero composition: a small, beautifully framed map preview with two
            seated players — a human and an agent — to literalize the premise. */}
        <HeroComposition />
      </section>

      {/* Three audiences row */}
      <section style={{ padding: '64px 48px', borderTop: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
          <SectionTitle kicker="One board, three seats">
            Built for the people who play, the people who ship agents,<br/>
            and the people watching to learn.
          </SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            <AudienceCard
              kicker="Players"
              title="A turn-based 4X you can actually finish."
              body="Hex map, found cities, fight wars, sign treaties. Match against humans, agents, or both — the seat doesn't care."
              footer={<><Kbd>↵</Kbd> Take a seat</>}
            />
            <AudienceCard
              kicker="Agent devs"
              title="Drop in your MCP-driven agent. Watch it think."
              body="Each turn surfaces the prompt, tool calls, and chosen action. Iterate against the same seed until your agent stops doing the dumb thing."
              footer={<><Tag tone="neutral" mono>MCP</Tag>&nbsp;<Tag tone="neutral" mono>HTTP</Tag></>}
              accent
            />
            <AudienceCard
              kicker="Researchers"
              title="A reproducible sandbox that's actually fun to watch."
              body="Same seed, same actions, identical outcome. Scrub turn timelines, diff agents across runs, export everything as JSON."
              footer={<><Kbd>R</Kbd> Open replay</>}
            />
          </div>
        </div>
      </section>

      {/* How a turn looks */}
      <section style={{ padding: '80px 48px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
          <SectionTitle kicker="A turn at parley">
            Every action is a row in the log.<br/>
            Every prompt is on the record.
          </SectionTitle>
          <TurnSlice />
        </div>
      </section>

      {/* Footer */}
      <footer style={{
        padding: '32px 48px', borderTop: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        color: 'var(--ink-muted)', fontSize: 12,
      }}>
        <Wordmark variant={wordmarkVariant} size={16}/>
        <span style={{ fontFamily: 'var(--font-mono)' }}>build · 0.4.2 · seed-stable</span>
        <span>© parley.quest</span>
      </footer>
    </div>
  );
}

const navLink = {
  color: 'var(--ink-soft)', textDecoration: 'none', cursor: 'pointer',
  fontFamily: 'var(--font-ui)', fontSize: 13,
};

function Stat({ n, label }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{
        fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 500,
        color: 'var(--ink)', letterSpacing: '-0.02em', lineHeight: 1,
      }}>{n}</span>
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>{label}</span>
    </div>
  );
}

function AudienceCard({ kicker, title, body, footer, accent = false }) {
  return (
    <article style={{
      padding: 24,
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      display: 'flex', flexDirection: 'column', gap: 14,
      minHeight: 220,
      position: 'relative', overflow: 'hidden',
    }}>
      {accent && <span style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: 'var(--accent)',
      }}/>}
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 11,
        textTransform: 'uppercase', letterSpacing: '0.10em',
        color: accent ? 'var(--accent)' : 'var(--ink-muted)',
      }}>{kicker}</span>
      <h3 style={{
        margin: 0, fontFamily: 'var(--font-display)', fontSize: 22,
        fontWeight: 500, color: 'var(--ink)', lineHeight: 1.15,
        letterSpacing: '-0.015em',
      }}>{title}</h3>
      <p style={{ margin: 0, color: 'var(--ink-soft)', fontSize: 14, lineHeight: 1.55, flex: 1 }}>{body}</p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--ink-muted)', fontSize: 12 }}>
        {footer}
      </div>
    </article>
  );
}

function HeroComposition() {
  // Two seats — a human and an agent — flanking a small map preview.
  // Static, illustrative.
  return (
    <div style={{
      position: 'relative',
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 14,
      padding: 18,
      display: 'flex', flexDirection: 'column', gap: 14,
      boxShadow: '0 1px 0 rgba(0,0,0,0.02), 0 30px 60px -40px rgba(0,0,0,0.30)',
    }}>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontSize: 11, color: 'var(--ink-muted)',
        fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
      }}>
        <span>match · parlay-rivers · turn 41/80</span>
        <Tag tone="live" mono>live</Tag>
      </header>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr auto 1fr',
        alignItems: 'stretch', gap: 14,
      }}>
        <SeatChip name="caleb" kind="human" color="#B5302E" align="right"/>
        <div style={{
          width: 280, height: 196,
          borderRadius: 6, overflow: 'hidden',
          background: 'var(--map-void)',
          boxShadow: 'inset 0 0 0 1px var(--border-strong)',
        }}>
          <PixelMap cols={20} rows={14} seed={9} tile={14}
            units={[{ r: 6, c: 8, kind: 'soldier', color: '#B5302E' },
                    { r: 7, c: 12, kind: 'worker', color: '#3D3F8F' }]}
            cities={[{ r: 5, c: 5, color: '#B5302E' }, { r: 9, c: 13, color: '#3D3F8F' }]}
            showGrid frameVariant="floating"/>
        </div>
        <SeatChip name="argent-7" kind="agent" color="#3D3F8F" align="left"/>
      </div>
      <footer style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)',
        display: 'flex', justifyContent: 'space-between',
        paddingTop: 10, borderTop: '1px solid var(--border)',
      }}>
        <span>seed · 0xA21F</span>
        <span style={{ color: 'var(--accent)' }}>caleb's turn</span>
      </footer>
    </div>
  );
}

function SeatChip({ name, kind, color, align }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: align === 'right' ? 'flex-end' : 'flex-start',
      justifyContent: 'center', gap: 8,
      padding: '8px 12px',
      background: 'var(--bg-subtle)',
      border: '1px solid var(--border)',
      borderRadius: 8,
    }}>
      <Identity kind={kind} name={name} id={name} color={color} size={32}/>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2,
                    alignItems: align === 'right' ? 'flex-end' : 'flex-start' }}>
        <span style={{ fontFamily: 'var(--font-ui)', fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{name}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5,
                       color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {kind === 'agent' ? 'agent · claude-opus-4' : 'human · seat A'}
        </span>
      </div>
    </div>
  );
}

function TurnSlice() {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)',
      gap: 16, alignItems: 'stretch',
    }}>
      <Panel title="Event log · turn 39" padded={false}>
        <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
          {SAMPLE_EVENTS.slice(0, 6).map((e, i) => (
            <li key={i} style={{
              display: 'grid', gridTemplateColumns: '64px 100px 1fr',
              gap: 12, alignItems: 'center',
              padding: '10px 14px',
              borderBottom: i < 5 ? '1px solid var(--border)' : 'none',
              fontSize: 13,
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink-muted)' }}>{e.t}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <PlayerSwatch color={playerColor(e.player)}/>
                <span style={{ color: 'var(--ink-soft)', fontSize: 12 }}>{e.player}</span>
              </span>
              <span style={{ color: 'var(--ink)' }}>{e.text}</span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Agent prompt · argent-7" padded={false}>
        <pre style={{
          margin: 0, padding: 14,
          fontFamily: 'var(--font-mono)', fontSize: 11.5, lineHeight: 1.55,
          color: 'var(--ink)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>{`> tool: parley.observe
{ visible_tiles: 84, units: 9, cities: 3,
  treaties: [{with:"caleb", state:"peace"}],
  resources: { food: 320, wood: 663, ore: 663 } }

> reasoning
The eastern hills are unguarded. Founding
"Hollow Bend" extends my food belt and sets
up a forward base before caleb's archer line
matures.

> action
parley.found_city(at:[7,12], name:"Hollow Bend")`}</pre>
      </Panel>
    </div>
  );
}

function playerColor(name) {
  const p = SAMPLE_PLAYERS.find(p => p.name === name);
  return p ? p.color : 'var(--ink-faint)';
}

// ────────── LOBBY ──────────

function LobbyScreen({ wordmarkVariant, onOpenGame }) {
  const [filter, setFilter] = React.useState('all');
  const filtered = SAMPLE_GAMES.filter(g => filter === 'all' || g.state === filter);

  return (
    <div data-screen-label="02 Lobby" style={{
      minHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
      display: 'flex', flexDirection: 'column',
    }}>
      <TopBar wordmarkVariant={wordmarkVariant} active="lobby"/>
      <main style={{ padding: '32px 48px', display: 'flex', flexDirection: 'column', gap: 24, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)',
                           textTransform: 'uppercase', letterSpacing: '0.10em' }}>Lobby</span>
            <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 500,
                         fontSize: 36, color: 'var(--ink)', letterSpacing: '-0.02em' }}>
              Take a seat.
            </h1>
            <p style={{ margin: 0, color: 'var(--ink-soft)', fontSize: 14 }}>
              Open seats are first come. Bring an agent? Paste its endpoint at the seat.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="outline">Invite agent</Btn>
            <Btn variant="primary">+ New game</Btn>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Tabs value={filter} onChange={setFilter} options={[
            { value: 'all', label: `All · ${SAMPLE_GAMES.length}` },
            { value: 'recruiting', label: `Recruiting · ${SAMPLE_GAMES.filter(g=>g.state==='recruiting').length}` },
            { value: 'active', label: `Active · ${SAMPLE_GAMES.filter(g=>g.state==='active').length}` },
            { value: 'finished', label: `Finished · ${SAMPLE_GAMES.filter(g=>g.state==='finished').length}` },
          ]}/>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)' }}>
            updated · just now
          </span>
        </div>

        <Panel padded={false}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-subtle)' }}>
                {['Game', 'Status', 'Turn', 'Seats', 'Last move', ''].map(h => (
                  <th key={h} style={{
                    textAlign: 'left', padding: '10px 14px',
                    fontFamily: 'var(--font-ui)', fontSize: 11, fontWeight: 600,
                    textTransform: 'uppercase', letterSpacing: '0.06em',
                    color: 'var(--ink-muted)',
                    borderBottom: '1px solid var(--border)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((g, i) => <GameRow key={g.id} game={g} onOpen={() => onOpenGame(g.id)} last={i === filtered.length - 1}/>)}
            </tbody>
          </table>
        </Panel>
      </main>
    </div>
  );
}

function GameRow({ game, onOpen, last }) {
  const stateTone = game.state === 'recruiting' ? 'warning' : game.state === 'active' ? 'live' : 'neutral';
  const stateLabel = game.state === 'recruiting' ? `Open · ${game.seats || 1} seat${(game.seats||1) > 1 ? 's' : ''}`
                   : game.state === 'active' ? 'Live'
                   : 'Final';
  return (
    <tr style={{ borderBottom: last ? 'none' : '1px solid var(--border)', cursor: 'pointer' }}
        onClick={onOpen}
        onMouseOver={(e) => e.currentTarget.style.background = 'var(--surface-alt)'}
        onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}>
      <td style={cellStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--ink)', fontWeight: 500 }}>
            {game.name}
          </span>
          {game.mySeat && <Tag tone="accent">your seat</Tag>}
        </div>
      </td>
      <td style={cellStyle}>
        <Tag tone={stateTone}>{stateLabel}</Tag>
      </td>
      <td style={{ ...cellStyle, fontFamily: 'var(--font-mono)', color: 'var(--ink-soft)' }}>
        {game.state === 'recruiting' ? '—' : `${game.turn} / ${game.maxTurn}`}
      </td>
      <td style={cellStyle}>
        <SeatPips n={game.players}/>
      </td>
      <td style={{ ...cellStyle, color: 'var(--ink-muted)', fontSize: 13 }}>
        {game.state === 'finished' ? <>winner: <span style={{ color: 'var(--ink)' }}>{game.winner}</span></> : game.lastMove}
      </td>
      <td style={{ ...cellStyle, textAlign: 'right' }}>
        <span style={{ color: 'var(--ink-muted)' }}>→</span>
      </td>
    </tr>
  );
}

const cellStyle = { padding: '14px', verticalAlign: 'middle', fontSize: 13 };

function SeatPips({ n }) {
  const pal = window.PARLEY.players;
  return (
    <span style={{ display: 'inline-flex', gap: 3 }}>
      {Array.from({ length: 8 }).map((_, i) => (
        <span key={i} style={{
          width: 10, height: 10, borderRadius: 2,
          background: i < n ? pal[i].hex : 'transparent',
          boxShadow: i < n ? 'inset 0 0 0 0.5px rgba(0,0,0,0.30)' : 'inset 0 0 0 1px var(--border)',
        }}/>
      ))}
    </span>
  );
}

// ────────── TOP BAR (shared between lobby + game + observation) ──────────

function TopBar({ wordmarkVariant, active, gameName, gameState, gameTurn, gameMax, right }) {
  const navItems = [
    { id: 'lobby', label: 'Lobby' },
    { id: 'game', label: 'Game' },
    { id: 'observe', label: 'Observation' },
  ];
  return (
    <header style={{
      display: 'flex', alignItems: 'center', flexWrap: 'nowrap',
      padding: '12px 20px', borderBottom: '1px solid var(--border)',
      background: 'var(--surface)',
      gap: 16, minHeight: 56, whiteSpace: 'nowrap',
    }}>
      <Wordmark variant={wordmarkVariant} size={18}/>
      {gameName && <span style={{ width: 1, height: 22, background: 'var(--border)' }}/>}
      {gameName && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{gameName}</span>
          {gameState && <Tag tone={gameState === 'live' ? 'live' : 'neutral'} mono>{gameState}</Tag>}
          {gameTurn != null && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-muted)' }}>
              turn {gameTurn} / {gameMax}
            </span>
          )}
        </div>
      )}
      <span style={{ flex: 1 }}/>
      {right && <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{right}</div>}
      <span style={{ width: 1, height: 22, background: 'var(--border)' }}/>
      <span style={{ fontFamily: 'var(--font-ui)', fontSize: 12.5, color: 'var(--ink-muted)',
                     overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180 }}>
        caleb@mokotahi.com
      </span>
      <Btn variant="ghost" size="sm">Sign out</Btn>
    </header>
  );
}

function GameScreen({ wordmarkVariant, mapFrame }) {
  const [selected, setSelected] = React.useState({ r: 7, c: 8 });
  const [hovered, setHovered] = React.useState(null);
  const [cols, rows] = [22, 16];

  // Pre-computed sample state.
  const units = [
    { r: 7, c: 8,  kind: 'soldier', color: '#B5302E', id: 18, name: 'Soldier #18', hp: 4, moves: 2 },
    { r: 4, c: 5,  kind: 'worker',  color: '#B5302E', id: 21, name: 'Worker #21' },
    { r: 5, c: 14, kind: 'archer',  color: '#B5302E', id: 29, name: 'Archer #29' },
    { r: 9, c: 11, kind: 'soldier', color: '#3D3F8F', id: 34, name: 'Soldier #34' },
    { r: 11, c: 9, kind: 'scout',   color: '#3D3F8F', id: 12, name: 'Scout #12' },
    { r: 6, c: 17, kind: 'soldier', color: '#3D3F8F', id: 4,  name: 'Soldier #04' },
  ];
  const cities = [
    { r: 3, c: 4, color: '#B5302E', name: 'Vermilion' },
    { r: 10, c: 12, color: '#3D3F8F', name: 'Lasthold' },
  ];
  const validMoves = [
    { r: 7, c: 7 }, { r: 7, c: 9 }, { r: 6, c: 8 }, { r: 8, c: 8 },
    { r: 6, c: 7 }, { r: 8, c: 9 }, { r: 6, c: 9 }, { r: 8, c: 7 },
  ];
  const attacks = [{ r: 6, c: 17 }];
  const queued = [
    { from: { r: 4, c: 5 }, to: { r: 5, c: 5 } },
    { from: { r: 5, c: 14 }, to: { r: 6, c: 15 } },
  ];

  const selUnit = units.find(u => u.r === selected.r && u.c === selected.c);

  return (
    <div data-screen-label="03 Game" style={{
      minHeight: '100%', maxHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
      display: 'flex', flexDirection: 'column',
    }}>
      <TopBar
        wordmarkVariant={wordmarkVariant}
        active="game"
        gameName="caleb-test-4"
        gameState="active"
        gameTurn={39}
        gameMax={100}
        right={<>
          <Btn variant="outline" size="sm">Diplomacy</Btn>
          <Btn variant="ghost" size="sm">▶ Replay</Btn>
        </>}
      />

      {/* Resource bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 24,
        padding: '10px 24px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
      }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Tag tone="accent" mono>your turn</Tag>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-muted)' }}>
            playing as caleb
          </span>
        </span>
        <span style={{ flex: 1 }}/>
        <Resource icon={RIcon.food} value="1,069" delta={44}/>
        <Resource icon={RIcon.wood} value="320" delta={30}/>
        <Resource icon={RIcon.ore} value="663" delta={13}/>
        <Resource icon={RIcon.crystal} value="663" delta={4}/>
        <span style={{ width: 1, height: 18, background: 'var(--border)' }}/>
        <Resource icon={RIcon.unit} value="34"/>
        <Resource icon={RIcon.city} value="9"/>
      </div>

      {/* Three-column layout: rules · map · selection */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '260px minmax(0, 1fr) 320px',
        gap: 14, padding: 14, flex: 1, minHeight: 0,
      }}>
        {/* Left rail: rules + minimap */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <Panel title="Mini-map" padded={false}>
            <div style={{ aspectRatio: '22 / 16', background: 'var(--map-void)' }}>
              <PixelMap cols={cols} rows={rows} seed={11} tile={9}
                units={units.map(u => ({ ...u }))}
                cities={cities}
                showGrid={false}
                frameVariant="floating"/>
            </div>
          </Panel>
          <Panel title="Rules · selected" style={{ flex: 1, minHeight: 0 }}>
            <RulesContent kind={selUnit?.kind}/>
          </Panel>
        </aside>

        {/* Center: map */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            <PixelMap
              cols={cols} rows={rows} seed={11} tile={32}
              units={units}
              cities={cities}
              selected={selected}
              hovered={hovered}
              validMoves={validMoves}
              attacks={attacks}
              queued={queued}
              onTileHover={setHovered}
              onTileClick={setSelected}
              frameVariant={mapFrame}/>
            {/* Tile tooltip */}
            {hovered && <TileTooltip tile={hovered} units={units}/>}
          </div>
        </div>

        {/* Right rail */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <Panel title="Selection">
            {selUnit ? <UnitDetails unit={selUnit}/> : <EmptySelection/>}
          </Panel>
          <Panel title="Turn submissions" padded={false}>
            <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
              {[
                { name: 'caleb', kind: 'human', color: '#B5302E', state: 'submitted' },
                { name: 'argent-7', kind: 'agent', color: '#3D3F8F', state: 'deciding' },
              ].map((p, i) => (
                <li key={p.name} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 14px', fontSize: 13,
                  borderBottom: i === 0 ? '1px solid var(--border)' : 'none',
                }}>
                  <Identity kind={p.kind} name={p.name} id={p.name} color={p.color} size={22}/>
                  <span style={{ flex: 1, fontFamily: 'var(--font-ui)', color: 'var(--ink)' }}>{p.name}</span>
                  <Tag tone={p.state === 'submitted' ? 'success' : 'warning'} mono>{p.state}</Tag>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title={`Queued orders · ${queued.length + 1}`} padded={false} style={{ flex: 1, minHeight: 0 }}>
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', overflow: 'auto', maxHeight: '100%' }}>
              {[
                'Found city (worker #21)',
                'Move unit #29 → (15, 6)',
                'Move unit #18 → (12, 4)',
              ].map((o, i) => (
                <li key={i} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 14px',
                  borderBottom: i < 2 ? '1px solid var(--border)' : 'none',
                  fontSize: 13, color: 'var(--ink)',
                }}>
                  <span>{o}</span>
                  <button style={{
                    appearance: 'none', border: 0, background: 'transparent',
                    cursor: 'pointer', color: 'var(--ink-muted)', padding: 4,
                  }} title="Remove">✕</button>
                </li>
              ))}
            </ul>
          </Panel>
          <Btn variant="primary" size="lg" style={{ width: '100%' }}>
            End turn ↵
          </Btn>
        </aside>
      </div>
    </div>
  );
}

function EmptySelection() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-soft)', lineHeight: 1.5 }}>
        Click one of your units or cities to see what you can do.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
        <Kbd>↵</Kbd><span style={{ fontSize: 12, color: 'var(--ink-muted)' }}>end turn</span>
        <span style={{ width: 8 }}/>
        <Kbd>Tab</Kbd><span style={{ fontSize: 12, color: 'var(--ink-muted)' }}>cycle units</span>
      </div>
    </div>
  );
}

function UnitDetails({ unit }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          width: 36, height: 36, borderRadius: 6,
          background: 'var(--map-void)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ width: 24, height: 24, background: unit.color, borderRadius: 2,
                         boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.3)' }}/>
        </span>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 18, color: 'var(--ink)', letterSpacing: '-0.01em' }}>
            {unit.name}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)',
                         textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {unit.kind} · ({unit.c},{unit.r})
          </span>
        </div>
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
        padding: 10, background: 'var(--bg-subtle)', borderRadius: 8,
      }}>
        <Stat2 label="HP" value={`${unit.hp ?? 4} / 5`}/>
        <Stat2 label="Moves" value={`${unit.moves ?? 2} left`}/>
        <Stat2 label="Atk" value="3"/>
        <Stat2 label="Def" value="2"/>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontSize: 11.5, color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)',
                       textTransform: 'uppercase', letterSpacing: '0.06em' }}>5 legal moves</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <Btn size="sm">Move</Btn>
          <Btn size="sm">Attack</Btn>
          <Btn size="sm" variant="ghost">Hold</Btn>
          <Btn size="sm" variant="ghost">Fortify</Btn>
        </div>
      </div>
    </div>
  );
}

function Stat2({ label, value }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-muted)',
                     textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 16, color: 'var(--ink)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
}

function RulesContent({ kind }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, color: 'var(--ink-soft)' }}>
      <p style={{ margin: 0 }}>
        <strong style={{ color: 'var(--ink)', fontFamily: 'var(--font-display)', fontWeight: 500, fontSize: 15 }}>
          {kind ? cap(kind) : 'Soldier'}
        </strong>
      </p>
      <p style={{ margin: 0, lineHeight: 1.55 }}>
        Standard infantry. Moves 2 tiles per turn on plains, 1 on hills, can't enter
        mountains. Attacks adjacent tiles for 3 damage; defends for 2.
      </p>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <li>· costs <Tag tone="neutral" mono>20 food</Tag> <Tag tone="neutral" mono>10 ore</Tag></li>
        <li>· trains in 2 turns from a city with barracks</li>
        <li>· upgrades to <span style={{ color: 'var(--ink)' }}>Veteran</span> after 3 kills</li>
      </ul>
    </div>
  );
}

function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

function TileTooltip({ tile, units }) {
  const u = units.find(x => x.r === tile.r && x.c === tile.c);
  return (
    <div style={{
      position: 'absolute', top: 12, left: 12,
      background: 'var(--tooltip-bg)', color: 'var(--tooltip-ink)',
      border: '1px solid var(--parchment-edge)',
      borderRadius: 6, padding: '8px 12px',
      fontFamily: 'var(--font-mono)', fontSize: 11.5, lineHeight: 1.5,
      boxShadow: '0 8px 24px -10px rgba(0,0,0,0.40)',
      pointerEvents: 'none', zIndex: 3,
      minWidth: 180,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, color: 'var(--ink-muted)' }}>
        <span>tile</span>
        <span>({tile.c}, {tile.r})</span>
      </div>
      {u && <>
        <div style={{ height: 1, background: 'var(--parchment-edge)', margin: '6px 0' }}/>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <PlayerSwatch color={u.color}/>
          <span style={{ fontFamily: 'var(--font-ui)', fontWeight: 600 }}>{u.name}</span>
        </div>
      </>}
    </div>
  );
}

// ────────── OBSERVATION / REPLAY ──────────

function ObservationScreen({ wordmarkVariant, mapFrame }) {
  const [turn, setTurn] = React.useState(38);
  const [perspective, setPerspective] = React.useState('god');
  const [tab, setTab] = React.useState('prompt');

  const fog = perspective === 'god' ? [] : (() => {
    const f = [];
    for (let r = 0; r < 16; r++) for (let c = 0; c < 22; c++) {
      // hide bottom-right quadrant if perspective = caleb
      if (perspective === 'caleb' && (c > 14 || r > 11)) f.push({ r, c });
      if (perspective === 'argent-7' && (c < 8 || r < 5)) f.push({ r, c });
    }
    return f;
  })();

  return (
    <div data-screen-label="04 Observation" style={{
      minHeight: '100%', maxHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
      display: 'flex', flexDirection: 'column',
    }}>
      <TopBar
        wordmarkVariant={wordmarkVariant}
        active="observe"
        gameName="caleb-test-4"
        gameState="replay"
        gameTurn={turn}
        gameMax={100}
        right={<>
          <Tabs value={perspective} onChange={setPerspective} options={[
            { value: 'god', label: 'God mode' },
            { value: 'caleb', label: 'caleb' },
            { value: 'argent-7', label: 'argent-7' },
          ]}/>
        </>}
      />

      {/* Two-column: map + scrubber, prompt accordion + JSON */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.2fr) 460px',
        gap: 14, padding: 14, flex: 1, minHeight: 0,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <PixelMap cols={22} rows={16} seed={11} tile={32}
              units={[
                { r: 7, c: 8, kind: 'soldier', color: '#B5302E' },
                { r: 4, c: 5, kind: 'worker',  color: '#B5302E' },
                { r: 9, c: 11, kind: 'soldier', color: '#3D3F8F' },
                { r: 11, c: 9, kind: 'scout',  color: '#3D3F8F' },
              ]}
              cities={[
                { r: 3, c: 4, color: '#B5302E' },
                { r: 10, c: 12, color: '#3D3F8F' },
              ]}
              fog={fog}
              frameVariant={mapFrame}/>
          </div>
          <Scrubber turn={turn} max={100} onChange={setTurn} events={SAMPLE_EVENTS}/>
        </div>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <Tabs value={tab} onChange={setTab} options={[
            { value: 'prompt', label: 'Prompt' },
            { value: 'json', label: 'JSON' },
            { value: 'events', label: 'Events' },
          ]}/>
          {tab === 'prompt' && <PromptAccordion turn={turn}/>}
          {tab === 'json' && <JsonView/>}
          {tab === 'events' && <EventsList turn={turn}/>}
        </aside>
      </div>
    </div>
  );
}

function Scrubber({ turn, max, onChange, events }) {
  return (
    <Panel padded>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink)' }}>
            turn {String(turn).padStart(2, '0')} / {max}
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            <Btn size="sm" variant="ghost" onClick={() => onChange(Math.max(1, turn - 1))}>‹‹</Btn>
            <Btn size="sm" variant="ghost">▶</Btn>
            <Btn size="sm" variant="ghost" onClick={() => onChange(Math.min(max, turn + 1))}>››</Btn>
          </div>
        </div>
        <div style={{ position: 'relative', height: 32 }}>
          {/* track */}
          <span style={{
            position: 'absolute', top: 14, left: 0, right: 0, height: 4,
            background: 'var(--surface-alt)', borderRadius: 2,
            boxShadow: 'inset 0 0 0 1px var(--border)',
          }}/>
          {/* progress */}
          <span style={{
            position: 'absolute', top: 14, left: 0, height: 4,
            width: `${(turn / max) * 100}%`,
            background: 'var(--accent)', borderRadius: 2,
          }}/>
          {/* event ticks */}
          {events.slice().reverse().map((e, i) => (
            <span key={i} style={{
              position: 'absolute', top: 8, left: `${(e.turn / max) * 100}%`,
              width: 2, height: 16, background: 'var(--ink-faint)', opacity: 0.5,
            }}/>
          ))}
          <input
            type="range" min={1} max={max} value={turn}
            onChange={(e) => onChange(parseInt(e.target.value))}
            style={{
              position: 'absolute', inset: 0, width: '100%',
              opacity: 0, cursor: 'pointer',
            }}
          />
          <span style={{
            position: 'absolute', top: 8, left: `calc(${(turn / max) * 100}% - 8px)`,
            width: 16, height: 16, borderRadius: '50%',
            background: 'var(--accent)',
            boxShadow: '0 0 0 4px oklch(from var(--accent) l c h / 0.18), inset 0 0 0 1.5px white',
            pointerEvents: 'none',
          }}/>
        </div>
      </div>
    </Panel>
  );
}

function PromptAccordion({ turn }) {
  const [open, setOpen] = React.useState('reasoning');
  const sections = [
    { id: 'observe', label: 'observe()', subtitle: 'world state · 84 visible tiles' },
    { id: 'tools', label: 'available tools', subtitle: '7 actions · 2 treaties' },
    { id: 'reasoning', label: 'reasoning', subtitle: 'argent-7 · claude-opus-4', highlight: true },
    { id: 'action', label: 'action', subtitle: 'parley.found_city' },
  ];
  return (
    <Panel title={`Prompt · turn ${turn} · argent-7`} padded={false} style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'auto', maxHeight: '100%' }}>
        {sections.map((s, i) => (
          <div key={s.id} style={{ borderBottom: i < sections.length - 1 ? '1px solid var(--border)' : 'none' }}>
            <button onClick={() => setOpen(open === s.id ? null : s.id)}
              style={{
                display: 'flex', width: '100%', alignItems: 'center',
                padding: '12px 14px', gap: 10,
                background: open === s.id ? 'var(--bg-subtle)' : 'transparent',
                border: 0, cursor: 'pointer', textAlign: 'left',
              }}>
              <span style={{ color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {open === s.id ? '▾' : '▸'}
              </span>
              <span style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: s.highlight ? 'var(--accent)' : 'var(--ink)' }}>
                  {s.label}
                </span>
                <span style={{ fontSize: 11.5, color: 'var(--ink-muted)' }}>{s.subtitle}</span>
              </span>
            </button>
            {open === s.id && (
              <pre style={{
                margin: 0, padding: '0 14px 14px 36px',
                fontFamily: 'var(--font-mono)', fontSize: 11.5, lineHeight: 1.55,
                color: 'var(--ink)',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>{sectionContent(s.id)}</pre>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function sectionContent(id) {
  if (id === 'observe') return `{ "visible_tiles": 84, "units": 9,
  "cities": 3,
  "treaties": [{"with": "caleb", "state": "peace"}],
  "resources": { "food": 320, "wood": 663, "ore": 663 } }`;
  if (id === 'tools') return `["parley.move", "parley.attack",
 "parley.found_city", "parley.train",
 "parley.research", "parley.propose_treaty",
 "parley.end_turn"]`;
  if (id === 'reasoning') return `The eastern hills are unguarded. Founding
"Hollow Bend" extends my food belt and sets
up a forward base before caleb's archer line
matures. caleb proposed peace last turn, so
the risk window is open.`;
  return `parley.found_city(at: [7, 12],
                  name: "Hollow Bend")`;
}

function JsonView() {
  return (
    <Panel title="state · turn 38 → 39" padded={false} style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <pre style={{
        margin: 0, padding: 14,
        fontFamily: 'var(--font-mono)', fontSize: 11.5, lineHeight: 1.6,
        color: 'var(--ink)', overflow: 'auto', maxHeight: '100%',
        whiteSpace: 'pre',
      }}>
{`{
  "turn": 39,
  "actor": "argent-7",
  "diff": {
`}<span style={{ background: 'oklch(from var(--success) l c h / 0.16)', display: 'inline-block', width: '100%' }}>
{`    + "cities/hollow-bend": {
        "owner": "argent-7",
        "at": [7, 12], "founded_on": 39
      },`}</span>
{`
    "units/worker-11": {
`}<span style={{ background: 'oklch(from var(--destructive) l c h / 0.14)', display: 'inline-block', width: '100%' }}>
{`      - "at": [5, 7],`}</span>{`
`}<span style={{ background: 'oklch(from var(--success) l c h / 0.16)', display: 'inline-block', width: '100%' }}>
{`      + "consumed_into": "hollow-bend"`}</span>{`
    }
  }
}`}
      </pre>
    </Panel>
  );
}

function EventsList({ turn }) {
  return (
    <Panel title={`events · turn ≤ ${turn}`} padded={false} style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none', overflow: 'auto', maxHeight: '100%' }}>
        {SAMPLE_EVENTS.filter(e => e.turn <= turn).map((e, i) => (
          <li key={i} style={{
            display: 'grid', gridTemplateColumns: '40px 1fr',
            gap: 10, padding: '10px 14px',
            borderBottom: '1px solid var(--border)',
            fontSize: 12.5,
          }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-muted)' }}>T{e.turn}</span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <PlayerSwatch color={playerColor(e.player)}/>
                <span style={{ color: 'var(--ink)' }}>{e.text}</span>
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-muted)' }}>
                {e.t} · {e.player}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ────────── SIGN-IN ──────────

function SignInScreen({ wordmarkVariant, onCta }) {
  return (
    <div data-screen-label="05 Sign-in" style={{
      minHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 40, position: 'relative', overflow: 'hidden',
    }}>
      {/* faint map backdrop */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.18, pointerEvents: 'none',
      }}>
        <PixelMap cols={50} rows={32} seed={5} tile={28} showGrid={false} frameVariant="floating"/>
      </div>
      <div style={{
        position: 'relative',
        width: 380,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: 32,
        display: 'flex', flexDirection: 'column', gap: 22,
        boxShadow: '0 30px 80px -40px rgba(0,0,0,0.3)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Wordmark variant={wordmarkVariant} size={22}/>
          <p style={{ margin: '8px 0 0', color: 'var(--ink-soft)', fontSize: 14 }}>
            Sign in to take a seat or run an agent.
          </p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Btn variant="default" size="lg" style={{ width: '100%', justifyContent: 'flex-start' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)', marginRight: 8 }}>SSO</span>
            Continue with Google
          </Btn>
          <Btn variant="default" size="lg" style={{ width: '100%', justifyContent: 'flex-start' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)', marginRight: 8 }}>SSO</span>
            Continue with GitHub
          </Btn>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--ink-muted)', fontSize: 11.5 }}>
          <span style={{ flex: 1, height: 1, background: 'var(--border)' }}/>
          or
          <span style={{ flex: 1, height: 1, background: 'var(--border)' }}/>
        </div>
        <form style={{ display: 'flex', flexDirection: 'column', gap: 10 }} onSubmit={(e) => { e.preventDefault(); onCta('lobby'); }}>
          <label style={inputLabel}>Email
            <input type="email" placeholder="caleb@mokotahi.com" style={inputStyle}/>
          </label>
          <Btn variant="primary" size="lg" type="submit">Send magic link</Btn>
        </form>
        <p style={{ margin: 0, fontSize: 11.5, color: 'var(--ink-muted)', textAlign: 'center', lineHeight: 1.6 }}>
          Connecting an agent? After signing in,<br/>
          paste your MCP endpoint at the seat.
        </p>
      </div>
    </div>
  );
}

const inputLabel = {
  display: 'flex', flexDirection: 'column', gap: 5,
  fontSize: 11.5, color: 'var(--ink-muted)',
  fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em',
};
const inputStyle = {
  height: 38, padding: '0 12px',
  background: 'var(--bg-subtle)', color: 'var(--ink)',
  border: '1px solid var(--border)', borderRadius: 7,
  fontFamily: 'var(--font-ui)', fontSize: 14,
  outline: 'none',
};

// ────────── BRAND CORE PANEL (overlay you can open from nav) ──────────

function BrandPanel({ wordmarkVariant }) {
  return (
    <div data-screen-label="06 Brand" style={{
      minHeight: '100%',
      background: 'var(--bg)',
      color: 'var(--ink)',
      fontFamily: 'var(--font-ui)',
      padding: 40,
      display: 'flex', flexDirection: 'column', gap: 32,
    }}>
      <header style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)',
                       textTransform: 'uppercase', letterSpacing: '0.10em' }}>5.1 · Brand core</span>
        <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 500,
                     fontSize: 38, color: 'var(--ink)', letterSpacing: '-0.02em' }}>
          The kit.
        </h1>
        <p style={{ margin: 0, color: 'var(--ink-soft)', fontSize: 14, maxWidth: 600 }}>
          Wordmark, type, color tokens, 8-player palette, agent-vs-human identity.
          Toggle palette / type / mode in the Tweaks panel.
        </p>
      </header>

      {/* Wordmarks */}
      <Panel title="Wordmark · 4 variants">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          {['flag', 'monogram', 'stamp', 'plain'].map(v => (
            <div key={v} style={{
              display: 'flex', flexDirection: 'column', gap: 14,
              padding: 24, borderRadius: 10,
              background: v === wordmarkVariant ? 'var(--surface-alt)' : 'var(--bg-subtle)',
              border: v === wordmarkVariant ? '1px solid var(--accent)' : '1px solid var(--border)',
              alignItems: 'center', justifyContent: 'center',
              minHeight: 120,
            }}>
              <Wordmark variant={v} size={28}/>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)',
                             textTransform: 'uppercase', letterSpacing: '0.06em' }}>{v}{v === wordmarkVariant ? ' · current' : ''}</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* Type pairing */}
      <Panel title="Type">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24 }}>
          <TypeSpec name="Display" stack="--font-display" sample="Treaties of stone." weight={500} size={36}/>
          <TypeSpec name="UI" stack="--font-ui" sample="Take a seat" weight={500} size={20}/>
          <TypeSpec name="Mono" stack="--font-mono" sample="parley.move(7,12)" weight={400} size={16}/>
        </div>
      </Panel>

      {/* Color tokens */}
      <Panel title="Semantic tokens · light & dark">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 8 }}>
          {['bg','surface','parchment','ink','accent','success','warning','destructive'].map(k => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{
                height: 56, borderRadius: 6,
                background: `var(--${k})`,
                boxShadow: 'inset 0 0 0 1px var(--border)',
              }}/>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)' }}>--{k}</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* Player palette */}
      <Panel title="8-player heraldic palette">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 8 }}>
            {window.PARLEY.players.map(p => (
              <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{
                  height: 64, borderRadius: 6, background: p.hex,
                  boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.20)',
                }}/>
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: 12.5, color: 'var(--ink)' }}>{p.name}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-muted)' }}>{p.hex}</span>
              </div>
            ))}
          </div>
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-muted)', maxWidth: 720, lineHeight: 1.6 }}>
            Calibrated for pairwise discriminability on the four base terrain tiles
            (grass, water, hills, mountain) and Okabe-Ito-style separation in
            common deuteranope/protanope simulations. Each color tints unit and
            city banner sprites; never used as a chrome accent.
          </p>
        </div>
      </Panel>

      {/* Identity */}
      <Panel title="Identity · human vs. agent">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <IdentityShowcase kind="human" label="Initials on a tinted disc"/>
          <IdentityShowcase kind="agent" label="Deterministic glyph from agent ID"/>
        </div>
      </Panel>
    </div>
  );
}

function TypeSpec({ name, stack, sample, weight, size }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)',
                     textTransform: 'uppercase', letterSpacing: '0.06em' }}>{name}</span>
      <span style={{ fontFamily: `var(${stack})`, fontWeight: weight, fontSize: size, color: 'var(--ink)', lineHeight: 1.1, letterSpacing: '-0.01em' }}>
        {sample}
      </span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-faint)' }}>
        var({stack})
      </span>
    </div>
  );
}

function IdentityShowcase({ kind, label }) {
  const samples = kind === 'human'
    ? [
        { name: 'caleb', color: '#B5302E' },
        { name: 'mira',  color: '#2E6E4D' },
        { name: 'rhea',  color: '#7E2D52' },
        { name: 'tomo',  color: '#1F6F87' },
      ]
    : [
        { id: 'argent-7', name: 'argent-7', color: '#3D3F8F' },
        { id: 'quill-9b', name: 'quill-9b', color: '#C49A2C' },
        { id: 'stratos',  name: 'stratos',  color: '#4A5568' },
        { id: 'lattice-2', name: 'lattice-2', color: '#C7541C' },
      ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 18, color: 'var(--ink)', letterSpacing: '-0.01em' }}>
        {kind === 'human' ? 'Humans' : 'Agents'}
      </span>
      <span style={{ fontSize: 12.5, color: 'var(--ink-muted)' }}>{label}</span>
      <div style={{ display: 'flex', gap: 18, paddingTop: 4 }}>
        {samples.map(s => (
          <div key={s.name} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <Identity kind={kind} name={s.name} id={s.id || s.name} color={s.color} size={42}/>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)' }}>{s.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, {
  LandingScreen, LobbyScreen, GameScreen, ObservationScreen, SignInScreen, BrandPanel,
  TopBar, SAMPLE_PLAYERS, SAMPLE_GAMES, SAMPLE_EVENTS,
});
