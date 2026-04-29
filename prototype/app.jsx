// app.jsx — shell, nav, tweaks panel, screen routing.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "mode": "light",
  "fontKey": "roboto-slab",
  "density": "regular",
  "wordmark": "flag",
  "mapFrame": "inset",
  "screen": "landing",
  "showGrid": true
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Apply theme via a <style> with CSS vars
  React.useEffect(() => {
    let el = document.getElementById('parley-theme-vars');
    if (!el) { el = document.createElement('style'); el.id = 'parley-theme-vars'; document.head.appendChild(el); }
    el.textContent = buildThemeVars(t.mode, t.fontKey, t.density);
  }, [t.mode, t.fontKey, t.density]);

  const screens = ['landing', 'lobby', 'game', 'observe', 'signin', 'brand'];
  const screenLabels = {
    landing: 'Landing', lobby: 'Lobby', game: 'Game',
    observe: 'Observation', signin: 'Sign-in', brand: 'Brand kit',
  };

  function Screen() {
    const props = { wordmarkVariant: t.wordmark, mapFrame: t.mapFrame };
    switch (t.screen) {
      case 'lobby':   return <LobbyScreen {...props} onOpenGame={() => setTweak('screen', 'game')}/>;
      case 'game':    return <GameScreen {...props}/>;
      case 'observe': return <ObservationScreen {...props}/>;
      case 'signin':  return <SignInScreen {...props} onCta={(s) => setTweak('screen', s)}/>;
      case 'brand':   return <BrandPanel {...props}/>;
      default:        return <LandingScreen {...props} onCta={(s) => setTweak('screen', s)}/>;
    }
  }

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--bg)',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Always-visible screen switcher (sticky pill, bottom-center to avoid header collision) */}
      <ScreenSwitcher screens={screens} labels={screenLabels} value={t.screen} onChange={(v) => setTweak('screen', v)} />
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <Screen/>
      </div>

      <TweaksPanel>
        <TweakSection label="Mode"/>
        <TweakRadio label="Theme" value={t.mode} options={['light', 'dark']}
          onChange={(v) => setTweak('mode', v)}/>
        <TweakRadio label="Density" value={t.density} options={['compact', 'regular', 'comfy']}
          onChange={(v) => setTweak('density', v)}/>

        <TweakSection label="Brand"/>
        <TweakSelect label="Type pairing" value={t.fontKey}
          options={Object.keys(PARLEY.fontStacks).map(k => ({ value: k, label: PARLEY.fontStacks[k].label }))}
          onChange={(v) => setTweak('fontKey', v)}/>
        <TweakSelect label="Wordmark" value={t.wordmark}
          options={['flag','monogram','stamp','plain']}
          onChange={(v) => setTweak('wordmark', v)}/>

        <TweakSection label="Map chrome"/>
        <TweakSelect label="Frame" value={t.mapFrame}
          options={['inset','parchment','cartographic','floating']}
          onChange={(v) => setTweak('mapFrame', v)}/>

        <TweakSection label="Screen"/>
        <TweakSelect label="View" value={t.screen}
          options={screens.map(s => ({ value: s, label: screenLabels[s] }))}
          onChange={(v) => setTweak('screen', v)}/>
      </TweaksPanel>
    </div>
  );
}

function ScreenSwitcher({ screens, labels, value, onChange }) {
  return (
    <div style={{
      position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      zIndex: 100, padding: 4,
      background: 'oklch(from var(--surface) l c h / 0.92)',
      border: '1px solid var(--border)',
      borderRadius: 999,
      backdropFilter: 'blur(12px)',
      boxShadow: '0 12px 32px -12px rgba(0,0,0,0.30)',
      display: 'flex', gap: 2,
    }}>
      {screens.map(s => (
        <button key={s} onClick={() => onChange(s)}
          style={{
            appearance: 'none', border: 0, cursor: 'pointer',
            padding: '6px 12px', borderRadius: 999,
            background: s === value ? 'var(--accent)' : 'transparent',
            color: s === value ? 'var(--accent-ink)' : 'var(--ink-soft)',
            fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 500,
            transition: 'all 120ms',
          }}>{labels[s]}</button>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
