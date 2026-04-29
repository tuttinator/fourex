"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Bot,
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PLAYER_PALETTE } from "@/components/brand/palette";
import { CreateGameDialog } from "@/components/create-game-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { api, queryKeys } from "@/lib/api";
import type { GameSummary, GamesListParams, SeatSummary } from "@/types/game";

type StatusFilterValue = GamesListParams["status"] | "in_progress" | "archived";

interface StatusOption {
  value: StatusFilterValue | undefined;
  label: string;
}

const STATUS_OPTIONS: StatusOption[] = [
  { value: "in_progress", label: "In progress" },
  { value: "waiting", label: "Waiting" },
  { value: "ended", label: "Ended" },
  { value: "archived", label: "Archived" },
  { value: undefined, label: "All" },
];

const SORT_OPTIONS = [
  { value: "created_at", label: "Created" },
  { value: "turn", label: "Turn" },
  { value: "status", label: "Status" },
] as const;

const PAGE_SIZE = 12;

// ──────────────── helpers ────────────────

function formatRelative(iso: string): string {
  const ts = new Date(iso).getTime();
  const diff = Date.now() - ts;
  if (diff < 60_000) return `${Math.max(0, Math.round(diff / 1000))}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function isAgentVsAgent(seats: SeatSummary[], playerSlots: number): boolean {
  if (seats.length < playerSlots) return false;
  if (seats.length < 2) return false;
  return seats.every((s) => s.user_identity_id === null);
}

function viewerIsSeated(
  seats: SeatSummary[],
  userIdentityId: string | null,
): boolean {
  if (!userIdentityId) return false;
  return seats.some(
    (s) =>
      s.user_identity_id !== null &&
      String(s.user_identity_id) === userIdentityId,
  );
}

function viewerIsCreator(
  game: GameSummary,
  userIdentityId: string | null,
): boolean {
  if (!userIdentityId) return false;
  if (!game.creator) return false;
  const seats = game.seats ?? [];
  const mySeat = seats.find(
    (s) =>
      s.user_identity_id !== null &&
      String(s.user_identity_id) === userIdentityId,
  );
  return mySeat !== undefined && mySeat.player_id === game.creator;
}

// ──────────────── presentation ────────────────

function StatusTag({ game }: { game: GameSummary }) {
  const isArchived = Boolean(game.archived_at);
  if (isArchived) return <Tag tone="neutral">Archived</Tag>;
  if (game.status === "active") return <Tag tone="live">Live</Tag>;
  if (game.status === "waiting") {
    const open = game.player_slots - game.players.length;
    return (
      <Tag tone="warning">
        {open > 0 ? `Open · ${open} seat${open !== 1 ? "s" : ""}` : "Waiting"}
      </Tag>
    );
  }
  if (game.status === "ended") return <Tag tone="neutral">Final</Tag>;
  return <Tag tone="neutral">{game.status}</Tag>;
}

type Tone = "neutral" | "accent" | "success" | "warning" | "live";

function Tag({
  tone,
  children,
  mono = false,
}: {
  tone: Tone;
  children: React.ReactNode;
  mono?: boolean;
}) {
  const tones: Record<Tone, { bg: string; fg: string; bd: string }> = {
    neutral: {
      bg: "var(--surface-alt)",
      fg: "var(--ink-soft)",
      bd: "var(--border)",
    },
    accent: {
      bg: "var(--accent-soft)",
      fg: "var(--accent)",
      bd: "var(--accent-soft)",
    },
    success: {
      bg: "oklch(from var(--success) l c h / 0.12)",
      fg: "var(--success)",
      bd: "oklch(from var(--success) l c h / 0.20)",
    },
    warning: {
      bg: "oklch(from var(--warning) l c h / 0.14)",
      fg: "oklch(from var(--warning) calc(l - 0.10) c h)",
      bd: "oklch(from var(--warning) l c h / 0.30)",
    },
    live: {
      bg: "var(--accent-soft)",
      fg: "var(--accent)",
      bd: "transparent",
    },
  };
  const t = tones[tone];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5"
      style={{
        background: t.bg,
        color: t.fg,
        boxShadow: `inset 0 0 0 1px ${t.bd}`,
        fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)",
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: mono ? "0.02em" : "0.005em",
        lineHeight: 1.5,
      }}
    >
      {tone === "live" && (
        <span
          className="inline-block animate-parley-pulse"
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "var(--accent)",
          }}
        />
      )}
      {children}
    </span>
  );
}

function SeatPips({ filled, total }: { filled: number; total: number }) {
  return (
    <span className="inline-flex gap-[3px]" aria-label={`${filled} of ${total} seats taken`}>
      {Array.from({ length: Math.max(total, 8) }).map((_, i) => {
        const taken = i < filled;
        const slot = i < total;
        return (
          <span
            key={i}
            className="inline-block"
            style={{
              width: 10,
              height: 10,
              borderRadius: 2,
              background: taken
                ? PLAYER_PALETTE[i % PLAYER_PALETTE.length].hex
                : "transparent",
              boxShadow: taken
                ? "inset 0 0 0 0.5px rgba(0,0,0,0.30)"
                : slot
                  ? "inset 0 0 0 1px var(--border)"
                  : "inset 0 0 0 1px var(--border)",
              opacity: slot ? 1 : 0.3,
            }}
          />
        );
      })}
    </span>
  );
}

// ──────────────── per-row action ────────────────

interface RowActionProps {
  game: GameSummary;
  userIdentityId: string | null;
  seated: boolean;
}

function RowAction({ game, userIdentityId, seated }: RowActionProps) {
  const isActive = game.status === "active";
  const isWaiting = game.status === "waiting";
  const isArchived = Boolean(game.archived_at);

  if (isArchived) {
    return (
      <Button asChild size="sm" variant="outline">
        <Link href={`/games/${game.game_id}`}>
          <Eye className="mr-1.5 h-3.5 w-3.5" />
          View
        </Link>
      </Button>
    );
  }

  if (!userIdentityId) {
    if (isActive) {
      return (
        <Button asChild size="sm" variant="outline">
          <Link href="/signin">Sign in to observe</Link>
        </Button>
      );
    }
    return (
      <Button asChild size="sm" variant="outline">
        <Link href={`/games/${game.game_id}`}>
          <Eye className="mr-1.5 h-3.5 w-3.5" />
          {isWaiting ? "View Lobby" : "View Game"}
        </Link>
      </Button>
    );
  }

  if (seated && isActive) {
    return (
      <Button asChild size="sm">
        <Link href={`/games/${game.game_id}`}>Resume</Link>
      </Button>
    );
  }

  if (!seated && isActive) {
    return (
      <Button asChild size="sm" variant="outline">
        <Link href={`/games/${game.game_id}/observe`}>
          <Eye className="mr-1.5 h-3.5 w-3.5" />
          Observe
        </Link>
      </Button>
    );
  }

  if (isWaiting) {
    return (
      <Button asChild size="sm" variant={seated ? "default" : "outline"}>
        <Link href={`/games/${game.game_id}`}>View Lobby</Link>
      </Button>
    );
  }

  return (
    <Button asChild size="sm" variant="outline">
      <Link href={`/games/${game.game_id}`}>
        <Eye className="mr-1.5 h-3.5 w-3.5" />
        View
      </Link>
    </Button>
  );
}

// ──────────────── archive button ────────────────

function ArchiveToggleButton({ game }: { game: GameSummary }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const isArchived = Boolean(game.archived_at);

  const mutation = useMutation({
    mutationFn: () =>
      isArchived ? api.unarchiveGame(game.game_id) : api.archiveGame(game.game_id),
    onSuccess: () => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["games"] });
    },
  });

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={isArchived ? "Unarchive game" : "Archive game"}
        title={isArchived ? "Unarchive game" : "Archive game"}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {isArchived ? (
          <ArchiveRestore className="h-4 w-4" />
        ) : (
          <Archive className="h-4 w-4" />
        )}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isArchived ? "Restore this game?" : "Archive this game?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isArchived
                ? "Restoring moves the game back into the default list. Its snapshots and history are unchanged."
                : "Archiving hides the game from your default list. Turn snapshots are preserved and you can restore it later."}
              {mutation.isError && (
                <span className="mt-2 block text-destructive">
                  {mutation.error instanceof Error
                    ? mutation.error.message
                    : "Action failed. Try again."}
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={mutation.isPending}
              onClick={(e) => {
                e.preventDefault();
                mutation.mutate();
              }}
            >
              {mutation.isPending
                ? isArchived
                  ? "Restoring…"
                  : "Archiving…"
                : isArchived
                  ? "Unarchive"
                  : "Archive"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// ──────────────── filter tabs ────────────────

function FilterTabs({
  value,
  onChange,
  counts,
}: {
  value: StatusFilterValue | undefined;
  onChange: (v: StatusFilterValue | undefined) => void;
  counts?: Record<string, number>;
}) {
  return (
    <div
      className="inline-flex gap-0.5 rounded-lg p-0.5"
      style={{
        background: "var(--surface-alt)",
        boxShadow: "inset 0 0 0 1px var(--border)",
      }}
    >
      {STATUS_OPTIONS.map((opt) => {
        const active = value === opt.value;
        const key = opt.value ?? "__all";
        const count = counts?.[key];
        return (
          <button
            key={opt.label}
            type="button"
            onClick={() => onChange(opt.value)}
            className="font-ui transition-colors"
            style={{
              padding: "5px 12px",
              borderRadius: 6,
              border: 0,
              cursor: "pointer",
              background: active ? "var(--surface)" : "transparent",
              color: active ? "var(--ink)" : "var(--ink-muted)",
              boxShadow: active
                ? "inset 0 0 0 1px var(--border), 0 1px 0 rgba(0,0,0,0.02)"
                : "none",
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            {opt.label}
            {typeof count === "number" && (
              <span
                className="ml-1.5 font-mono text-ink-muted"
                style={{ fontSize: 11 }}
              >
                · {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ──────────────── row ────────────────

interface GameRowProps {
  game: GameSummary;
  userIdentityId: string | null;
  isLast: boolean;
}

function GameRow({ game, userIdentityId, isLast }: GameRowProps) {
  const seats = game.seats ?? [];
  const seated = viewerIsSeated(seats, userIdentityId);
  const agentVsAgent = isAgentVsAgent(seats, game.player_slots);
  const ownsGame = viewerIsCreator(game, userIdentityId);
  const filledSeats = game.players.length;
  const lastMoveLabel =
    game.status === "ended" && game.winner ? (
      <>
        <span className="text-ink-muted">winner: </span>
        <span className="font-medium text-ink">{game.winner}</span>
      </>
    ) : (
      <span className="text-ink-muted">{formatRelative(game.updated_at)}</span>
    );

  return (
    <tr
      className="group transition-colors hover:bg-surface-alt"
      style={{ borderBottom: isLast ? "none" : "1px solid var(--border)" }}
    >
      {/* Game name + tags */}
      <td className="px-3.5 py-3.5 align-middle">
        <div className="flex items-center gap-2.5">
          <Link
            href={`/games/${game.game_id}`}
            className="font-mono font-medium text-ink hover:text-accent"
            style={{ fontSize: 13 }}
          >
            {game.game_id}
          </Link>
          {seated && <Tag tone="accent">your seat</Tag>}
          {agentVsAgent && (
            <Tag tone="neutral">
              <Bot className="h-3 w-3" />
              Agent vs Agent
            </Tag>
          )}
        </div>
      </td>

      {/* Status */}
      <td className="px-3.5 py-3.5 align-middle">
        <StatusTag game={game} />
      </td>

      {/* Turn */}
      <td
        className="px-3.5 py-3.5 align-middle font-mono text-ink-soft"
        style={{ fontSize: 13 }}
      >
        {game.status === "waiting" ? "—" : `${game.turn} / ${game.max_turns}`}
      </td>

      {/* Seats */}
      <td className="px-3.5 py-3.5 align-middle">
        <SeatPips filled={filledSeats} total={game.player_slots} />
      </td>

      {/* Last move / winner */}
      <td
        className="px-3.5 py-3.5 align-middle"
        style={{ fontSize: 13 }}
      >
        {lastMoveLabel}
      </td>

      {/* Actions */}
      <td className="px-3.5 py-3.5 align-middle text-right">
        <div className="flex items-center justify-end gap-2">
          <RowAction
            game={game}
            userIdentityId={userIdentityId}
            seated={seated}
          />
          {ownsGame && <ArchiveToggleButton game={game} />}
        </div>
      </td>
    </tr>
  );
}

// ──────────────── shell ────────────────

export function GamesListClient({
  userIdentityId,
}: {
  userIdentityId: string | null;
}) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<
    StatusFilterValue | undefined
  >("in_progress");
  const [sortBy, setSortBy] = useState<GamesListParams["sort_by"]>("created_at");
  const [sortOrder, setSortOrder] =
    useState<GamesListParams["sort_order"]>("desc");
  const [page, setPage] = useState(0);

  const isArchivedFilter = statusFilter === "archived";
  const backendStatus: GamesListParams["status"] = isArchivedFilter
    ? undefined
    : statusFilter === "in_progress"
      ? "active"
      : statusFilter;

  const params: GamesListParams = {
    status: backendStatus,
    sort_by: sortBy,
    sort_order: sortOrder,
    offset: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    include_archived: isArchivedFilter,
  };

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.games(params),
    queryFn: () => api.listGames(params),
    refetchInterval: 10000,
  });

  const games = (data?.games ?? []).filter((g) =>
    isArchivedFilter ? Boolean(g.archived_at) : true,
  );
  const totalDisplay = isArchivedFilter ? games.length : (data?.total ?? 0);
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Action bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <FilterTabs
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(0);
            }}
          />
          <div className="flex items-center gap-1.5">
            <span
              className="font-mono uppercase text-ink-muted"
              style={{ fontSize: 11, letterSpacing: "0.06em" }}
            >
              sort
            </span>
            <select
              className="rounded-md border border-border bg-surface px-2 py-1 text-[12px] text-ink"
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value as GamesListParams["sort_by"]);
                setPage(0);
              }}
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setSortOrder(sortOrder === "desc" ? "asc" : "desc")
              }
              aria-label="Toggle sort order"
            >
              {sortOrder === "desc" ? "↓" : "↑"}
            </Button>
          </div>
          {data && (
            <span
              className="font-mono text-ink-muted"
              style={{ fontSize: 11 }}
            >
              {totalDisplay} game{totalDisplay !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled>
            Invite agent
          </Button>
          <Button size="sm" onClick={() => setCreateDialogOpen(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New game
          </Button>
        </div>
      </div>

      {/* Body */}
      {isLoading ? (
        <Panel>
          <div className="flex h-48 items-center justify-center text-ink-muted">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Loading games…
          </div>
        </Panel>
      ) : error ? (
        <Panel>
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <AlertCircle className="h-10 w-10 text-destructive" />
            <p className="text-destructive">
              Failed to load games: {error.message}
            </p>
            <Button variant="outline" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        </Panel>
      ) : games.length === 0 ? (
        <Panel>
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <p className="text-ink-soft">
              {statusFilter === "in_progress"
                ? "No games in progress."
                : statusFilter === "archived"
                  ? "No archived games."
                  : statusFilter
                    ? `No ${statusFilter} games.`
                    : "No games yet."}
            </p>
            <Button
              variant="outline"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              Create your first game
            </Button>
          </div>
        </Panel>
      ) : (
        <Panel padded={false}>
          <table className="w-full border-collapse">
            <thead>
              <tr style={{ background: "var(--bg-subtle)" }}>
                {["Game", "Status", "Turn", "Seats", "Last move", ""].map(
                  (h) => (
                    <th
                      key={h || "actions"}
                      className="border-b border-border px-3.5 py-2.5 text-left font-ui font-semibold uppercase text-ink-muted"
                      style={{
                        fontSize: 11,
                        letterSpacing: "0.06em",
                      }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {games.map((g, i) => (
                <GameRow
                  key={g.game_id}
                  game={g}
                  userIdentityId={userIdentityId}
                  isLast={i === games.length - 1}
                />
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft className="mr-1 h-4 w-4" />
            Previous
          </Button>
          <span className="font-mono text-ink-muted" style={{ fontSize: 12 }}>
            page {page + 1} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages - 1}
            onClick={() => setPage(page + 1)}
          >
            Next
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      )}

      <CreateGameDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </div>
  );
}

function Panel({
  children,
  padded = true,
}: {
  children: React.ReactNode;
  padded?: boolean;
}) {
  return (
    <section
      className="flex flex-col overflow-hidden rounded-[10px] border border-border bg-surface"
      style={{ boxShadow: "0 1px 0 rgba(0,0,0,0.02)" }}
    >
      <div className={padded ? "p-3.5" : ""}>{children}</div>
    </section>
  );
}
