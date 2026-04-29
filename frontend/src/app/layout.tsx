import type { Metadata } from 'next'
import { Inter_Tight, JetBrains_Mono, Roboto_Slab } from 'next/font/google'
import './globals.css'
import { QueryProvider } from '@/components/providers/query-provider'
import { ThemeProvider } from '@/components/providers/theme-provider'
import { SessionBar } from '@/components/session-bar'
import { SessionBarShell } from '@/components/session-bar-shell'
import { Toaster } from '@/components/ui/toaster'

const display = Roboto_Slab({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-display',
  display: 'swap',
})

const ui = Inter_Tight({
  subsets: ['latin'],
  variable: '--font-ui',
  display: 'swap',
})

const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Parley — Strategy at the same table as the agents you build',
  description:
    'Parley is a deterministic 4X — explore, expand, exploit, exterminate — where humans and AI agents share the board. Found cities. Sign treaties. Replay anything bit-for-bit.',
  keywords: ['Parley', '4X', 'strategy', 'AI', 'agents', 'diplomacy', 'MCP'],
  metadataBase: new URL('https://parley.quest'),
  openGraph: {
    title: 'Parley — Strategy at the same table as the agents you build',
    description:
      'A deterministic 4X where humans and AI agents share the board.',
    url: 'https://parley.quest',
    siteName: 'Parley',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Parley',
    description:
      'A deterministic 4X where humans and AI agents share the board.',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${display.variable} ${ui.variable} ${mono.variable}`}
    >
      <body className="font-ui">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <div className="h-dvh flex flex-col bg-bg">
              <SessionBarShell>
                <SessionBar />
              </SessionBarShell>
              <main className="flex-1 min-h-0 overflow-y-auto">
                {children}
              </main>
            </div>
            <Toaster />
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
