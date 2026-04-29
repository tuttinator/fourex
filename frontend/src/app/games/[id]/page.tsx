'use client'

import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { api, queryKeys, getPlayerColor } from '@/lib/api'
import { ObservationView } from '@/components/observation-view'
import { GameplayView } from '@/components/gameplay-view'
import { TopBar } from '@/components/top-bar'
import { useSessionEmail } from '@/components/session-email-provider'
import { signOutAction } from '@/lib/auth-actions'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { Tag } from '@/components/ui/tag'
import { StatPair } from '@/components/ui/stat'
import { Identity } from '@/components/brand/identity'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  Play,
  Users,
  LogIn,
  LogOut,
  Link as LinkIcon,
  Check,
  Bot,
  KeyRound,
  Copy,
  AlertTriangle,
  Pencil,
  X,
  Mail,
  Send,
  Trash2,
  Wrench,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useLobbyEvents } from '@/hooks/use-lobby-events'
import {
  clearGameCredentials,
  getGameApiKey,
  getGamePlayerId,
  setGameCredentials,
} from '@/lib/game-auth'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function GameDetailPage() {
  const { id: gameId } = useParams<{ id: string }>()
  const email = useSessionEmail()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [joinPlayerId, setJoinPlayerId] = useState('')
  const [copied, setCopied] = useState(false)
  const [apiKeyCopied, setApiKeyCopied] = useState(false)
  const [mcpConfigCopied, setMcpConfigCopied] = useState(false)
  const [copiedSlotIndex, setCopiedSlotIndex] = useState<number | null>(null)
  const [confirmRegenSlot, setConfirmRegenSlot] = useState<number | null>(null)
  // Phase 4: which slot is currently being edited (type toggle / rename),
  // and the in-progress form state. ``null`` means no edit in flight.
  const [editingSlotIndex, setEditingSlotIndex] = useState<number | null>(null)
  const [editType, setEditType] = useState<'human' | 'agent'>('human')
  const [editName, setEditName] = useState('')
  // Phase 5: which slot is currently in invite-edit mode (``email`` form),
  // and the in-progress email field. ``null`` means no invite UI open.
  const [invitingSlotIndex, setInvitingSlotIndex] = useState<number | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')

  // Per-game player id is stored in localStorage when we create/join.
  // Re-read on every render so a fresh join reflects immediately.
  const currentPlayer =
    typeof window !== 'undefined' ? getGamePlayerId(gameId) : null

  // Live lobby events: the hook invalidates the game-detail query on
  // every lobby.* broadcast. We keep a polling fallback so observers
  // without an API key (invite recipients who haven't joined yet) still
  // see the roster update, and so a WS drop degrades gracefully.
  const { status: wsStatus } = useLobbyEvents(gameId)
  const pollingInterval = wsStatus === 'open' ? 15000 : 5000

  const { data: game, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
    refetchInterval: pollingInterval,
  })

  const joinMutation = useMutation({
    mutationFn: (playerId: string) =>
      api.joinLobby(gameId, { player_id: playerId }),
    onSuccess: ({ game, api_key }) => {
      setGameCredentials(game.game_id, {
        apiKey: api_key ?? '',
        playerId: joinPlayerId.trim(),
      })
      setJoinPlayerId('')
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Joined lobby', description: `Seated as ${joinPlayerId.trim()}.` })
    },
    onError: (err) => {
      toast({ title: 'Failed to join', description: err.message, variant: 'destructive' })
    },
  })

  const leaveMutation = useMutation({
    mutationFn: () => api.leaveGame(gameId),
    onSuccess: () => {
      clearGameCredentials(gameId)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Left lobby', description: `You left ${gameId}.` })
    },
    onError: (err) => {
      toast({ title: 'Failed to leave', description: err.message, variant: 'destructive' })
    },
  })

  const startMutation = useMutation({
    mutationFn: async () => {
      // Owners running an all-Agent game have no per-game API key, so
      // ``startGame`` (per-game-key auth) won't work. The BFF-routed
      // ``startGameAsOwner`` accepts the Auth.js JWT instead. Pick the
      // right endpoint based on whether we hold a key for this game.
      const playerId = getGamePlayerId(gameId)
      const hasGameplayKey =
        playerId !== null && game?.players.includes(playerId) === true
      return hasGameplayKey
        ? api.startGame(gameId)
        : api.startGameAsOwner(gameId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      queryClient.invalidateQueries({ queryKey: ['games'] })
      toast({ title: 'Game started', description: `${gameId} is now active!` })
    },
    onError: (err) => {
      toast({ title: 'Failed to start', description: err.message, variant: 'destructive' })
    },
  })

  const reconfigureMutation = useMutation({
    mutationFn: (slots: { type: 'human' | 'agent'; name: string | null; reserved_email: string | null }[]) =>
      api.reconfigureSlots(gameId, { slots }),
    onSuccess: () => {
      setEditingSlotIndex(null)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({ title: 'Slot updated', description: 'The lobby has been reconfigured.' })
    },
    onError: (err) => {
      toast({ title: 'Reconfigure failed', description: err.message, variant: 'destructive' })
    },
  })

  const regenerateMutation = useMutation({
    mutationFn: (slotIndex: number) => api.regenerateSlotKey(gameId, slotIndex),
    onSuccess: () => {
      setConfirmRegenSlot(null)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({ title: 'Key regenerated', description: 'The previous key is now invalid.' })
    },
    onError: (err) => {
      setConfirmRegenSlot(null)
      toast({ title: 'Regenerate failed', description: err.message, variant: 'destructive' })
    },
  })

  const inviteMutation = useMutation({
    mutationFn: ({ slotIndex, email }: { slotIndex: number; email: string }) =>
      api.inviteSlot(gameId, slotIndex, email),
    onSuccess: (data) => {
      setInvitingSlotIndex(null)
      setInviteEmail('')
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({
        title: 'Invite sent',
        description: `Sent to ${data.email}. They have 24h to claim the slot.`,
      })
    },
    onError: (err) => {
      toast({ title: 'Invite failed', description: err.message, variant: 'destructive' })
    },
  })

  const clearInviteMutation = useMutation({
    mutationFn: (slotIndex: number) => api.clearSlotInvite(gameId, slotIndex),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({ title: 'Reservation cleared', description: 'Slot is now open.' })
    },
    onError: (err) => {
      toast({ title: 'Clear failed', description: err.message, variant: 'destructive' })
    },
  })

  // Phase 5 redemption: if the lobby URL carries ``?invite=<token>``,
  // attempt to redeem it as soon as the user is signed in. The
  // sign-in round-trip preserves the query string (Auth.js callbackUrl)
  // so this fires on return from the email link too.
  const router = useRouter()
  const searchParams = useSearchParams()
  const inviteToken = searchParams?.get('invite') ?? null
  const redeemAttemptedRef = useRef(false)
  const [redeemNeedsSignIn, setRedeemNeedsSignIn] = useState(false)
  const redeemMutation = useMutation({
    mutationFn: ({ token, playerId }: { token: string; playerId: string }) =>
      api.joinLobby(gameId, { player_id: playerId, invite_token: token }),
    onSuccess: ({ game: redeemedGame, api_key }, variables) => {
      setGameCredentials(redeemedGame.game_id, {
        apiKey: api_key ?? '',
        playerId: variables.playerId,
      })
      // Strip ``?invite=`` from the URL so a refresh doesn't replay
      // the (now-redeemed) token.
      router.replace(`/games/${gameId}`)
      queryClient.invalidateQueries({ queryKey: queryKeys.gameDetail(gameId) })
      toast({ title: 'Slot claimed', description: 'You are now seated in the reserved slot.' })
    },
    onError: (err) => {
      // The BFF returns 401 with "Sign in" in the body when the visitor
      // isn't signed in. Surface a CTA in that case rather than burying
      // the failure in a toast — it's the expected first-time path for
      // a recipient clicking the email link.
      const msg = err.message || ''
      if (msg.toLowerCase().includes('sign in')) {
        setRedeemNeedsSignIn(true)
        return
      }
      toast({ title: 'Redemption failed', description: msg, variant: 'destructive' })
    },
  })

  useEffect(() => {
    if (!inviteToken) return
    if (redeemAttemptedRef.current) return
    if (!game) return
    if (game.status !== 'waiting') return
    // Already seated? No need to redeem.
    if (currentPlayer && game.players.includes(currentPlayer)) {
      redeemAttemptedRef.current = true
      return
    }
    // Pick a default player_id from the reserved slot's email local
    // part (e.g. alice@x.com → "alice"), trimmed to 64 chars and
    // de-duplicated against existing names. The user can rename
    // afterwards by leaving and rejoining.
    const reservedSlot = game.slots?.find(
      (s) => s.reserved_email && !s.name && s.type === 'human',
    )
    const seedName = reservedSlot?.reserved_email?.split('@')[0] ?? 'guest'
    let candidate = seedName.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64) || 'guest'
    let suffix = 1
    while (game.players.includes(candidate)) {
      candidate = `${seedName}${suffix}`.slice(0, 64)
      suffix += 1
    }
    redeemAttemptedRef.current = true
    redeemMutation.mutate({ token: inviteToken, playerId: candidate })
  }, [inviteToken, game, currentPlayer, redeemMutation, gameId])

  const copySlotKey = async (slotIndex: number, plaintext: string) => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopiedSlotIndex(slotIndex)
      toast({
        title: `Slot ${slotIndex} key copied`,
        description: 'Paste it into your agent now — it disappears when the game starts.',
      })
      setTimeout(() => setCopiedSlotIndex((prev) => (prev === slotIndex ? null : prev)), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the key manually and copy.',
        variant: 'destructive',
      })
    }
  }

  const copyApiKey = async (apiKey: string) => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(apiKey)
      setApiKeyCopied(true)
      toast({
        title: 'API key copied',
        description: 'Paste it into your MCP-enabled agent (e.g. Claude Code).',
      })
      setTimeout(() => setApiKeyCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the key manually and copy.',
        variant: 'destructive',
      })
    }
  }

  const copyMcpConfig = async (snippet: string) => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(snippet)
      setMcpConfigCopied(true)
      toast({
        title: 'MCP config copied',
        description: 'Paste it into your MCP client config (e.g. ~/.claude.json) and restart.',
      })
      setTimeout(() => setMcpConfigCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Select the snippet manually and copy.',
        variant: 'destructive',
      })
    }
  }

  const copyInviteLink = async () => {
    if (typeof window === 'undefined') return
    const url = `${window.location.origin}/games/${gameId}`
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      toast({ title: 'Invite link copied', description: url })
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Copy the URL from your address bar.',
        variant: 'destructive',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p>Loading game...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
          <p className="text-destructive mb-4">Failed to load game: {error.message}</p>
          <div className="flex gap-2 justify-center">
            <Button variant="outline" onClick={() => refetch()}>Retry</Button>
            <Button asChild variant="outline">
              <Link href="/games">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Games
              </Link>
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (!game) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Game not found</p>
          <Button asChild variant="outline">
            <Link href="/games">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Games
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  // Active or ended: show observation view with header
  if (game.status === 'active' || game.status === 'ended') {
    return (
      <div className="h-full flex flex-col bg-bg text-ink font-ui">
        <TopBar
          email={email}
          signOutAction={signOutAction}
          game={{
            name: game.game_id,
            state: game.status === 'active' ? 'live' : 'ended',
          }}
        >
          <Button asChild variant="ghost" size="sm">
            <Link href="/games">
              <ArrowLeft className="h-4 w-4 mr-1.5" />
              Back
            </Link>
          </Button>
          {game.winner && (
            <span className="font-mono text-ink-muted" style={{ fontSize: 12 }}>
              winner · <span className="text-ink">{game.winner}</span>
              {game.victory_type && (
                <span className="text-ink-muted"> ({game.victory_type})</span>
              )}
            </span>
          )}
          <Button asChild variant="outline" size="sm">
            <Link href={`/games/${game.game_id}/diplomacy`}>
              <Users className="h-4 w-4 mr-1.5" />
              Diplomacy
            </Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link href={`/games/${game.game_id}/replay`}>
              <Play className="h-4 w-4 mr-1.5" />
              Replay
            </Link>
          </Button>
        </TopBar>

        {/* Seated players in an active game get the gameplay controls;
            observers and spectators on ended games drop to the read-only
            observation view. */}
        <div className="flex-1 overflow-hidden">
          {game.status === 'active' &&
          currentPlayer &&
          game.players.includes(currentPlayer) ? (
            <GameplayView gameId={gameId} currentPlayer={currentPlayer} />
          ) : (
            <ObservationView gameId={gameId} />
          )}
        </div>
      </div>
    )
  }

  // Waiting room view
  // ``viewer_is_creator`` is the canonical signal — the backend resolves
  // it from the caller's JWT (or per-game API key) and recognises both
  // seated creators AND unseated all-Agent owners. The localStorage
  // fallback is kept for backwards compat with response shapes that
  // predate the field, but on a fresh deploy ``viewer_is_creator`` is
  // always present.
  const isCreator =
    game.viewer_is_creator === true ||
    (currentPlayer !== null && currentPlayer === game.creator)
  const isInGame = currentPlayer !== null && game.players.includes(currentPlayer)
  // Phase 3: a slot is "ready" when it has a name (Human seated, or
  // Agent name fixed at create) AND for Agents also has a minted
  // key. That's the same check the backend's start_game guard runs.
  const slotsArr = game.slots && game.slots.length > 0 ? game.slots : []
  const allSlotsReady =
    slotsArr.length === game.player_slots &&
    slotsArr.every((s) => {
      if (!s.name) return false
      if (s.type === 'agent' && !s.player_api_key_id) return false
      return true
    })
  const isFull = slotsArr.length > 0
    ? allSlotsReady
    : game.players.length >= game.player_slots
  const canStart = isCreator && isFull && game.status === 'waiting'
  const agentSlotsWithKeys = slotsArr.filter(
    (s) => s.type === 'agent' && s.plaintext_key,
  )
  // The "Configure your MCP client" hint accompanies any agent hand-off
  // affordance — either per-slot agent keys, or the seated creator's
  // own per-game key. It's a one-time setup step the human needs to
  // complete before any agent can connect.
  const seatedCreatorHasKey =
    currentPlayer !== null &&
    game.creator === currentPlayer &&
    Boolean(
      game.api_key ||
        (typeof window !== 'undefined' ? getGameApiKey(gameId) : null),
    )
  const showMcpConfigHint =
    isCreator &&
    game.status === 'waiting' &&
    (agentSlotsWithKeys.length > 0 || seatedCreatorHasKey)
  const mcpConfigSnippet = `{
  "mcpServers": {
    "fourex-mcp": {
      "type": "http",
      "url": "https://mcp.parley.quest/"
    }
  }
}`

  return (
    <div className="container mx-auto px-4 py-8 max-w-3xl">
      <div className="mb-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/games">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Games
          </Link>
        </Button>
      </div>

      <div className="space-y-6">
        {redeemNeedsSignIn && inviteToken && (
          <Panel
            data-testid="invite-signin-cta"
            kicker="invite"
            title="You've been invited to this lobby"
          >
            <div className="space-y-2">
              <p className="flex items-center gap-2 text-sm">
                <Mail className="h-4 w-4 text-accent" />
                Sign in with the same email the invite was sent to and your
                seat will be claimed automatically.
              </p>
              <Button asChild size="sm">
                <Link
                  href={`/signin?callbackUrl=${encodeURIComponent(`/games/${gameId}?invite=${inviteToken}`)}`}
                >
                  <LogIn className="h-4 w-4 mr-2" />
                  Sign in to claim your slot
                </Link>
              </Button>
            </div>
          </Panel>
        )}

        {/* Game Header */}
        <Panel
          title={game.game_id}
          kicker={game.creator ? `created by ${game.creator}` : 'lobby'}
          action={
            <Tag tone="warning" mono>
              waiting
            </Tag>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <StatPair
                label="map"
                value={`${game.map_width}×${game.map_height}`}
              />
              <StatPair label="seed" value={game.seed} />
              <StatPair label="slots" value={game.player_slots} />
              <StatPair label="created" value={formatDate(game.created_at)} />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={copyInviteLink}
              className="w-full"
            >
              {copied ? (
                <Check className="h-4 w-4 mr-2" />
              ) : (
                <LinkIcon className="h-4 w-4 mr-2" />
              )}
              {copied ? 'Copied!' : 'Copy invite link'}
            </Button>
          </div>
        </Panel>

        {agentSlotsWithKeys.length > 0 && (
          <Panel
            data-testid="per-slot-agent-keys-panel"
            kicker="agent keys"
            title="Agent slot API keys"
            action={<Bot className="h-4 w-4 text-ink-muted" />}
          >
            <div className="space-y-3">
              <p className="text-xs text-ink-muted">
                Hand each Agent slot&apos;s key to its agent. Keys disappear from
                this page the instant you press Start — copy them now or hit
                <span className="font-medium"> Regenerate</span> to mint a fresh
                one (the previous key stops working).
              </p>
              {agentSlotsWithKeys.map((slot) => (
                <div
                  key={slot.slot_index}
                  className="space-y-2 rounded-md border border-border bg-surface p-3"
                  data-testid={`agent-slot-key-${slot.slot_index}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex flex-col gap-0.5">
                      <span
                        className="font-mono uppercase text-ink-muted"
                        style={{ fontSize: 10, letterSpacing: '0.08em' }}
                      >
                        Slot {slot.slot_index} · Agent
                      </span>
                      <p className="text-sm font-medium text-ink">{slot.name}</p>
                    </div>
                    {confirmRegenSlot === slot.slot_index ? (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfirmRegenSlot(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => regenerateMutation.mutate(slot.slot_index)}
                          disabled={regenerateMutation.isPending}
                          data-testid={`agent-slot-key-${slot.slot_index}-regenerate-confirm`}
                        >
                          {regenerateMutation.isPending ? 'Working...' : 'Confirm'}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setConfirmRegenSlot(slot.slot_index)}
                        data-testid={`agent-slot-key-${slot.slot_index}-regenerate`}
                      >
                        Regenerate
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={slot.plaintext_key ?? ''}
                      readOnly
                      onFocus={(e) => e.currentTarget.select()}
                      className="font-mono text-xs"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        slot.plaintext_key &&
                        copySlotKey(slot.slot_index, slot.plaintext_key)
                      }
                      data-testid={`agent-slot-key-${slot.slot_index}-copy`}
                    >
                      {copiedSlotIndex === slot.slot_index ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        )}

        {showMcpConfigHint && (
          <Panel
            data-testid="mcp-config-hint-panel"
            kicker="configure your mcp client"
            title="MCP client setup"
            action={<Wrench className="h-4 w-4 text-ink-muted" />}
          >
            <div className="space-y-3">
              <p className="text-xs text-ink-muted">
                Before an agent can use the keys above, its MCP client needs
                to know about{' '}
                <code className="rounded bg-bg-subtle px-1 py-0.5 text-ink">
                  https://mcp.parley.quest/
                </code>
                . For Claude Code, drop this into{' '}
                <code className="rounded bg-bg-subtle px-1 py-0.5 text-ink">
                  ~/.claude.json
                </code>{' '}
                (or a project{' '}
                <code className="rounded bg-bg-subtle px-1 py-0.5 text-ink">
                  .mcp.json
                </code>
                ) and restart the client. The{' '}
                <code className="rounded bg-bg-subtle px-1 py-0.5 text-ink">
                  /play-parley
                </code>{' '}
                skill walks through the rest of the handshake.
              </p>
              <div className="relative">
                <pre
                  className="overflow-x-auto rounded-md border border-border bg-bg-subtle p-3 font-mono text-xs"
                  data-testid="mcp-config-hint-snippet"
                >
                  {mcpConfigSnippet}
                </pre>
                <Button
                  variant="outline"
                  size="sm"
                  className="absolute top-2 right-2"
                  onClick={() => copyMcpConfig(mcpConfigSnippet)}
                  data-testid="mcp-config-hint-copy"
                >
                  {mcpConfigCopied ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                  <span className="ml-2">
                    {mcpConfigCopied ? 'Copied' : 'Copy'}
                  </span>
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {(() => {
          // Phase 1 hand-off panel for the seated creator's own
          // per-game key. The backend echoes the key on a per-game-key
          // bearer; the BFF-routed lobby fetch sends the JWT instead,
          // so we fall back to the localStorage copy stashed when this
          // user created the lobby.
          const seatedCreator =
            currentPlayer !== null && game.creator === currentPlayer
          if (!seatedCreator) return null
          const localKey =
            typeof window !== 'undefined' ? getGameApiKey(gameId) : null
          const apiKey = game.api_key || localKey || null
          if (!apiKey) return null
          return (
            <Panel
              data-testid="agent-api-key-panel"
              kicker="hand off"
              title="MCP agent setup"
              action={<Bot className="h-4 w-4 text-ink-muted" />}
            >
              <div className="space-y-3">
                <p className="text-xs text-ink-muted">
                  Point your agent at the live MCP endpoint (
                  <code className="mx-1 rounded bg-bg-subtle px-1 py-0.5 text-ink">
                    https://mcp.parley.quest/
                  </code>
                  , streamable-http) and paste this game URL plus the API key
                  below. In Claude Code, the
                  <code className="mx-1 rounded bg-bg-subtle px-1 py-0.5 text-ink">
                    /play-parley
                  </code>
                  skill walks through the handshake.
                </p>
                <div>
                  <Label
                    htmlFor="agent-api-key"
                    className="flex items-center gap-1 text-xs"
                  >
                    <KeyRound className="h-3 w-3" />
                    Per-game API key
                  </Label>
                  <div className="mt-1 flex gap-2">
                    <Input
                      id="agent-api-key"
                      value={apiKey}
                      readOnly
                      onFocus={(e) => e.currentTarget.select()}
                      className="font-mono text-xs"
                      data-testid="agent-api-key-input"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => copyApiKey(apiKey)}
                      data-testid="agent-api-key-copy"
                    >
                      {apiKeyCopied ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                      <span className="ml-2">
                        {apiKeyCopied ? 'Copied' : 'Copy'}
                      </span>
                    </Button>
                  </div>
                </div>
                <p className="flex items-start gap-1 text-xs">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-warning" />
                  <span className="text-ink-muted">
                    Copy the key now — once the game starts it disappears from
                    this page. If you lose it, you can mint a fresh lobby
                    instead.
                  </span>
                </p>
              </div>
            </Panel>
          )
        })()}

        {/* Player Slots */}
        <Panel
          title={`Players · ${game.players.length}/${game.player_slots}`}
          kicker="seats"
          action={<Users className="h-4 w-4 text-ink-muted" />}
        >
          <div className="space-y-2">
            {(() => {
                // Prefer the Phase 2 ``slots`` array — it's the canonical
                // shape and also lets us render type badges. When the
                // response predates the column (legacy server, null
                // column), synthesise an all-Human view from
                // ``players`` so the UI degrades cleanly.
                const slots: { slot_index: number; type: 'human' | 'agent'; name: string | null; reserved_email: string | null }[] =
                  game.slots && game.slots.length > 0
                    ? game.slots.map((s) => ({
                        slot_index: s.slot_index,
                        type: s.type,
                        name: s.name,
                        reserved_email: s.reserved_email ?? null,
                      }))
                    : Array.from({ length: game.player_slots }, (_, i) => ({
                        slot_index: i,
                        type: 'human' as const,
                        name: game.players[i] ?? null,
                        reserved_email: null,
                      }))

                const startEdit = (slotIndex: number) => {
                  const s = slots[slotIndex]
                  setEditingSlotIndex(slotIndex)
                  setEditType(s.type)
                  setEditName(s.name ?? '')
                }
                const saveEdit = () => {
                  if (editingSlotIndex === null) return
                  const trimmed = editName.trim()
                  if (editType === 'agent' && !trimmed) {
                    toast({
                      title: 'Agent name required',
                      description: 'Give the agent a display name.',
                      variant: 'destructive',
                    })
                    return
                  }
                  // Build the full slot array: every other slot keeps its
                  // current shape, the edited slot picks up the form state.
                  // Occupied Human slots have their existing name preserved
                  // server-side regardless of what we send, but mirroring
                  // the current value here keeps the request descriptive.
                  const payload = slots.map((s) => {
                    if (s.slot_index === editingSlotIndex) {
                      return {
                        type: editType,
                        name: editType === 'agent'
                          ? trimmed
                          : s.name,
                        reserved_email: s.reserved_email,
                      }
                    }
                    return {
                      type: s.type,
                      name: s.name,
                      reserved_email: s.reserved_email,
                    }
                  })
                  reconfigureMutation.mutate(payload)
                }

                return slots.map((slot) => {
                  const i = slot.slot_index
                  const player = slot.name
                  const occupiedHuman = slot.type === 'human' && !!player
                  const isEditing = editingSlotIndex === i
                  const canEdit = isCreator && game.status === 'waiting'

                  if (isEditing) {
                    return (
                      <div
                        key={i}
                        className="p-3 rounded-lg border space-y-3"
                        data-testid={`lobby-slot-${i}-edit`}
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: getPlayerColor(i) }}
                          />
                          <span className="text-xs text-muted-foreground">
                            Slot {i}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs items-center">
                          <Label className="mr-1">Type:</Label>
                          <Button
                            type="button"
                            size="sm"
                            variant={editType === 'human' ? 'default' : 'outline'}
                            onClick={() => setEditType('human')}
                            disabled={occupiedHuman}
                            data-testid={`lobby-slot-${i}-edit-type-human`}
                          >
                            Human
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={editType === 'agent' ? 'default' : 'outline'}
                            onClick={() => setEditType('agent')}
                            disabled={occupiedHuman}
                            data-testid={`lobby-slot-${i}-edit-type-agent`}
                          >
                            Agent
                          </Button>
                          {occupiedHuman && (
                            <span className="text-muted-foreground ml-2">
                              {player} is seated — they must leave before the
                              slot can flip to Agent.
                            </span>
                          )}
                        </div>
                        {editType === 'agent' && (
                          <div>
                            <Label htmlFor={`slot-${i}-name`} className="text-xs">
                              Agent name
                            </Label>
                            <Input
                              id={`slot-${i}-name`}
                              value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              placeholder="bot"
                              maxLength={64}
                              className="mt-1"
                              data-testid={`lobby-slot-${i}-edit-name`}
                            />
                          </div>
                        )}
                        <div className="flex justify-end gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditingSlotIndex(null)}
                            disabled={reconfigureMutation.isPending}
                          >
                            <X className="h-4 w-4 mr-1" /> Cancel
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            onClick={saveEdit}
                            disabled={reconfigureMutation.isPending}
                            data-testid={`lobby-slot-${i}-edit-save`}
                          >
                            <Check className="h-4 w-4 mr-1" />
                            {reconfigureMutation.isPending ? 'Saving...' : 'Save'}
                          </Button>
                        </div>
                      </div>
                    )
                  }

                  const reservedEmail = slot.reserved_email
                  const isReservedHuman =
                    slot.type === 'human' && !player && !!reservedEmail
                  const isOpenHuman =
                    slot.type === 'human' && !player && !reservedEmail

                  if (invitingSlotIndex === i) {
                    return (
                      <div
                        key={i}
                        className="p-3 rounded-lg border space-y-3"
                        data-testid={`lobby-slot-${i}-invite`}
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: '#6b7280' }}
                          />
                          <span className="text-xs text-muted-foreground">
                            Slot {i} · Invite a human
                          </span>
                        </div>
                        <div>
                          <Label htmlFor={`slot-${i}-email`} className="text-xs">
                            Invitee email
                          </Label>
                          <Input
                            id={`slot-${i}-email`}
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            placeholder="alice@example.com"
                            type="email"
                            maxLength={320}
                            className="mt-1"
                            data-testid={`lobby-slot-${i}-invite-email`}
                          />
                        </div>
                        <div className="flex justify-end gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setInvitingSlotIndex(null)
                              setInviteEmail('')
                            }}
                            disabled={inviteMutation.isPending}
                          >
                            <X className="h-4 w-4 mr-1" /> Cancel
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => {
                              const trimmed = inviteEmail.trim()
                              if (!trimmed) {
                                toast({
                                  title: 'Email required',
                                  description: 'Type the invitee email.',
                                  variant: 'destructive',
                                })
                                return
                              }
                              inviteMutation.mutate({
                                slotIndex: i,
                                email: trimmed,
                              })
                            }}
                            disabled={inviteMutation.isPending}
                            data-testid={`lobby-slot-${i}-invite-send`}
                          >
                            <Send className="h-4 w-4 mr-1" />
                            {inviteMutation.isPending ? 'Sending...' : 'Send invite'}
                          </Button>
                        </div>
                      </div>
                    )
                  }

                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface p-3"
                      data-testid={`lobby-slot-${i}`}
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className="font-mono uppercase text-ink-muted"
                          style={{
                            fontSize: 10,
                            letterSpacing: '0.08em',
                            minWidth: 40,
                          }}
                        >
                          slot {i}
                        </span>
                        {player ? (
                          <Identity
                            kind={slot.type === 'agent' ? 'agent' : 'human'}
                            name={player}
                            id={player}
                            color={getPlayerColor(i)}
                            size={22}
                          />
                        ) : isReservedHuman ? (
                          <div className="flex items-center gap-2">
                            <Identity
                              kind="human"
                              name="?"
                              id={reservedEmail ?? `slot-${i}`}
                              color="#6b7280"
                              size={22}
                            />
                            <div className="flex flex-col">
                              <span className="text-sm font-medium">Reserved</span>
                              <span className="flex items-center gap-1 text-xs text-ink-muted">
                                <Mail className="h-3 w-3" />
                                {reservedEmail}
                              </span>
                            </div>
                          </div>
                        ) : (
                          <span className="text-sm italic text-ink-muted">
                            Empty slot
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Tag tone={slot.type === 'agent' ? 'accent' : 'neutral'} mono>
                          {slot.type}
                        </Tag>
                        {player && i === 0 && game.creator === player && (
                          <Tag tone="accent" mono>
                            creator
                          </Tag>
                        )}
                        {canEdit && isOpenHuman && (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setInvitingSlotIndex(i)
                              setInviteEmail('')
                            }}
                            data-testid={`lobby-slot-${i}-invite-button`}
                          >
                            <Mail className="h-3 w-3 mr-1" /> Invite
                          </Button>
                        )}
                        {canEdit && isReservedHuman && (
                          <>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setInvitingSlotIndex(i)
                                setInviteEmail(reservedEmail ?? '')
                              }}
                              data-testid={`lobby-slot-${i}-resend-button`}
                            >
                              <Send className="h-3 w-3 mr-1" /> Resend
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              onClick={() => clearInviteMutation.mutate(i)}
                              disabled={clearInviteMutation.isPending}
                              data-testid={`lobby-slot-${i}-clear-invite-button`}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </>
                        )}
                        {canEdit && (
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => startEdit(i)}
                            data-testid={`lobby-slot-${i}-edit-button`}
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  )
                })
              })()}
          </div>
        </Panel>

        {/* Actions */}
        <Panel title="Actions" kicker="lobby">
          <div className="space-y-4">
            {!isInGame && !isFull && (
              <div className="space-y-3">
                <div>
                  <Label htmlFor="joinPlayerId">Your display name in this game</Label>
                  <Input
                    id="joinPlayerId"
                    value={joinPlayerId}
                    onChange={(e) => setJoinPlayerId(e.target.value)}
                    placeholder="bob"
                    className="mt-1"
                    maxLength={64}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Must be unique within this lobby and not already taken.
                  </p>
                </div>
                <Button
                  onClick={() => {
                    const trimmed = joinPlayerId.trim()
                    if (!trimmed) {
                      toast({
                        title: 'Display name required',
                        description: 'Pick a name to play under.',
                        variant: 'destructive',
                      })
                      return
                    }
                    joinMutation.mutate(trimmed)
                  }}
                  disabled={joinMutation.isPending}
                  className="w-full"
                >
                  <LogIn className="h-4 w-4 mr-2" />
                  {joinMutation.isPending ? 'Joining...' : 'Join Lobby'}
                </Button>
                <p className="text-xs text-muted-foreground text-center">
                  You must be signed in to join. If nothing happens, check you&apos;re signed in.
                </p>
              </div>
            )}

            {isInGame && (
              <div className="flex gap-2">
                {!isCreator && (
                  <Button
                    variant="outline"
                    onClick={() => leaveMutation.mutate()}
                    disabled={leaveMutation.isPending}
                    className="flex-1"
                  >
                    <LogOut className="h-4 w-4 mr-2" />
                    {leaveMutation.isPending ? 'Leaving...' : 'Leave Lobby'}
                  </Button>
                )}
                {isCreator && (
                  <Button
                    onClick={() => startMutation.mutate()}
                    disabled={!canStart || startMutation.isPending}
                    className="flex-1"
                  >
                    <Play className="h-4 w-4 mr-2" />
                    {startMutation.isPending
                      ? 'Starting...'
                      : canStart
                        ? 'Start Game'
                        : 'Waiting for slots'}
                  </Button>
                )}
              </div>
            )}

            {/* All-Agent (owner-only) creators aren't in ``players`` so the
                ``isInGame`` branch above doesn't fire — surface the Start
                control here instead. */}
            {!isInGame && isCreator && (
              <Button
                onClick={() => startMutation.mutate()}
                disabled={!canStart || startMutation.isPending}
                className="w-full"
                data-testid="owner-start-button"
              >
                <Play className="h-4 w-4 mr-2" />
                {startMutation.isPending
                  ? 'Starting...'
                  : canStart
                    ? 'Start Game'
                    : 'Waiting for slots'}
              </Button>
            )}

            {!isInGame && !isCreator && isFull && (
              <p className="text-center text-sm text-ink-muted">
                This lobby is full.
              </p>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}
