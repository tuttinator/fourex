import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ['class'],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      fontFamily: {
        display: ['var(--font-display)'],
        sans: ['var(--font-ui)'],
        ui: ['var(--font-ui)'],
        mono: ['var(--font-mono)'],
      },
      colors: {
        border: 'var(--border)',
        'border-strong': 'var(--border-strong)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        primary: {
          DEFAULT: 'var(--primary)',
          foreground: 'var(--primary-foreground)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          foreground: 'var(--secondary-foreground)',
        },
        destructive: {
          DEFAULT: 'var(--destructive)',
          foreground: 'var(--destructive-foreground)',
        },
        success: 'var(--success)',
        warning: 'var(--warning)',
        muted: {
          DEFAULT: 'var(--muted)',
          foreground: 'var(--muted-foreground)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--accent-foreground)',
          soft: 'var(--accent-soft)',
          hover: 'var(--accent-hover)',
          ink: 'var(--accent-ink)',
        },
        popover: {
          DEFAULT: 'var(--popover)',
          foreground: 'var(--popover-foreground)',
        },
        card: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        // Parley extended palette
        bg: 'var(--bg)',
        'bg-subtle': 'var(--bg-subtle)',
        surface: 'var(--surface)',
        'surface-alt': 'var(--surface-alt)',
        parchment: {
          DEFAULT: 'var(--parchment)',
          edge: 'var(--parchment-edge)',
        },
        ink: {
          DEFAULT: 'var(--ink)',
          soft: 'var(--ink-soft)',
          muted: 'var(--ink-muted)',
          faint: 'var(--ink-faint)',
        },
        'map-void': 'var(--map-void)',
        // Game-specific terrain colors (used as fallbacks behind sprites)
        terrain: {
          plains: '#8fbc8f',
          forest: '#228b22',
          mountain: '#696969',
          water: '#4682b4',
        },
        // 8-player heraldic palette — picked for max discriminability on
        // green/blue/gray/sand terrain and pairwise CB safety.
        player: {
          crimson: '#B5302E',
          indigo: '#3D3F8F',
          ochre: '#C49A2C',
          forest: '#2E6E4D',
          plum: '#7E2D52',
          teal: '#1F6F87',
          slate: '#4A5568',
          ember: '#C7541C',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
        'unit-move': {
          '0%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.1)', opacity: '0.8' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        'parley-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'unit-move': 'unit-move 0.2s ease-in-out',
        'parley-pulse': 'parley-pulse 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
} satisfies Config

export default config
