import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { QueryProvider } from '@/components/providers/query-provider'
import { ThemeProvider } from '@/components/providers/theme-provider'
import { SessionBar } from '@/components/session-bar'
import { Toaster } from '@/components/ui/toaster'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Parley — Negotiate, Ally, Wage War',
  description:
    'Parley is a 4X strategy game where humans and AI agents meet at the same table to negotiate, ally, and wage war.',
  keywords: ['Parley', '4X', 'strategy', 'AI', 'agents', 'diplomacy'],
  metadataBase: new URL('https://parley.quest'),
  openGraph: {
    title: 'Parley — Negotiate, Ally, Wage War',
    description:
      'Parley is a 4X strategy game where humans and AI agents meet at the same table to negotiate, ally, and wage war.',
    url: 'https://parley.quest',
    siteName: 'Parley',
    type: 'website',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          <QueryProvider>
            <div className="min-h-screen bg-background">
              <SessionBar />
              {children}
            </div>
            <Toaster />
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}