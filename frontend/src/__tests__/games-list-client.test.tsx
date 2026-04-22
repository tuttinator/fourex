import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// The dialog pulls in useRouter, which errors under vitest without the Next
// app-router being mounted. We don't exercise the dialog in these tests, so
// stub it with an inert stand-in.
vi.mock("@/components/create-game-dialog", () => ({
	CreateGameDialog: () => null,
}));

import { GamesListClient } from "@/components/games-list-client";
import { api } from "@/lib/api";
import type { GameSummary, GamesListResponse } from "@/types/game";

function newClient() {
	return new QueryClient({
		defaultOptions: { queries: { retry: false, refetchInterval: false } },
	});
}

function wrapper(client: QueryClient) {
	return function Wrapper({ children }: { children: ReactNode }) {
		return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
	};
}

function makeGame(overrides: Partial<GameSummary> = {}): GameSummary {
	return {
		game_id: "game_abc",
		player_slots: 2,
		players: ["alice", "bob"],
		seats: [],
		turn: 3,
		max_turns: 50,
		status: "active",
		winner: null,
		victory_type: null,
		created_at: "2026-04-20T00:00:00Z",
		updated_at: "2026-04-21T00:00:00Z",
		ended_at: null,
		...overrides,
	};
}

function stubList(games: GameSummary[]) {
	const payload: GamesListResponse = {
		games,
		total: games.length,
		offset: 0,
		limit: 12,
	};
	return vi.spyOn(api, "listGames").mockResolvedValue(payload);
}

describe("GamesListClient Phase 2 polish", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	afterEach(() => {
		cleanup();
		vi.restoreAllMocks();
	});

	it("defaults to the In progress filter (status=active)", async () => {
		const spy = stubList([]);
		render(<GamesListClient userIdentityId={null} />, { wrapper: wrapper(newClient()) });

		await waitFor(() => expect(spy).toHaveBeenCalled());
		const firstCall = spy.mock.calls[0][0];
		expect(firstCall?.status).toBe("active");
		// Wait for the loading state to resolve so the filter chips render.
		expect(
			await screen.findByRole("button", { name: "In progress" }),
		).toBeInTheDocument();
	});

	it("shows Resume when the viewer is seated in an active game", async () => {
		stubList([
			makeGame({
				seats: [
					{ player_id: "alice", user_identity_id: 42 },
					{ player_id: "bob", user_identity_id: null },
				],
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		const resume = await screen.findByRole("link", { name: /resume/i });
		expect(resume).toHaveAttribute("href", "/games/game_abc");
		expect(screen.queryByRole("link", { name: /observe/i })).toBeNull();
	});

	it("shows Observe when the viewer is signed in but not seated", async () => {
		stubList([
			makeGame({
				seats: [
					{ player_id: "alice", user_identity_id: 9 },
					{ player_id: "bob", user_identity_id: 10 },
				],
			}),
		]);
		render(<GamesListClient userIdentityId="99" />, { wrapper: wrapper(newClient()) });

		const observe = await screen.findByRole("link", { name: /observe/i });
		expect(observe).toHaveAttribute("href", "/games/game_abc/observe");
	});

	it("shows a sign-in prompt for unsigned viewers on active games", async () => {
		stubList([makeGame({ seats: [] })]);
		render(<GamesListClient userIdentityId={null} />, { wrapper: wrapper(newClient()) });

		const signin = await screen.findByRole("link", { name: /sign in to observe/i });
		expect(signin).toHaveAttribute("href", "/signin");
	});

	it("shows View for ended games", async () => {
		stubList([
			makeGame({
				status: "ended",
				winner: "alice",
				victory_type: "score",
				ended_at: "2026-04-21T10:00:00Z",
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		const view = await screen.findByRole("link", { name: /^view$/i });
		expect(view).toHaveAttribute("href", "/games/game_abc");
	});

	it("flags full agent-only rosters with an 'Agent vs Agent' badge", async () => {
		stubList([
			makeGame({
				seats: [
					{ player_id: "agent_a", user_identity_id: null },
					{ player_id: "agent_b", user_identity_id: null },
				],
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		expect(await screen.findByText(/agent vs agent/i)).toBeInTheDocument();
	});

	it("does not show the Agent badge when any seat is human or the lobby is not full", async () => {
		stubList([
			makeGame({
				game_id: "game_mixed",
				seats: [
					{ player_id: "agent_a", user_identity_id: null },
					{ player_id: "alice", user_identity_id: 5 },
				],
			}),
			makeGame({
				game_id: "game_partial",
				seats: [{ player_id: "agent_a", user_identity_id: null }],
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		await screen.findByText("game_mixed");
		await screen.findByText("game_partial");
		expect(screen.queryByText(/agent vs agent/i)).toBeNull();
	});

	it("switches filter chips back to all games when 'All' is clicked", async () => {
		const spy = stubList([]);
		render(<GamesListClient userIdentityId={null} />, { wrapper: wrapper(newClient()) });
		// Wait for the filter chips to mount (query has to resolve first).
		const allButton = await screen.findByRole("button", { name: "All" });

		fireEvent.click(allButton);
		await waitFor(() => {
			const latest = spy.mock.calls.at(-1)?.[0];
			expect(latest?.status).toBeUndefined();
		});
	});

	it("Archived chip sends include_archived=true and filters to archived rows", async () => {
		const spy = stubList([
			makeGame({
				game_id: "game_archived",
				status: "waiting",
				archived_at: "2026-04-22T00:00:00Z",
				archived_reason: "manual",
			}),
			makeGame({
				game_id: "game_active",
				status: "active",
				archived_at: null,
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });
		const archivedChip = await screen.findByRole("button", { name: "Archived" });

		fireEvent.click(archivedChip);
		await waitFor(() => {
			const latest = spy.mock.calls.at(-1)?.[0];
			expect(latest?.include_archived).toBe(true);
			expect(latest?.status).toBeUndefined();
		});

		// Only the archived row should render, not the active one.
		await screen.findByText("game_archived");
		expect(screen.queryByText("game_active")).toBeNull();
	});

	it("shows the archive icon only for games the signed-in user created", async () => {
		stubList([
			makeGame({
				game_id: "game_mine",
				creator: "alice",
				seats: [
					{ player_id: "alice", user_identity_id: 42 },
					{ player_id: "bob", user_identity_id: 10 },
				],
			}),
			makeGame({
				game_id: "game_theirs",
				creator: "bob",
				seats: [
					{ player_id: "alice", user_identity_id: 42 },
					{ player_id: "bob", user_identity_id: 10 },
				],
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		await screen.findByText("game_mine");
		await screen.findByText("game_theirs");
		// The archive button has aria-label "Archive game". Only one card
		// (game_mine) should expose it because alice is its creator.
		const archiveButtons = screen.getAllByRole("button", { name: /archive game/i });
		expect(archiveButtons).toHaveLength(1);
	});

	it("confirm dialog triggers archiveGame mutation", async () => {
		const archiveSpy = vi.spyOn(api, "archiveGame").mockResolvedValue({
			game_id: "game_mine",
			player_slots: 2,
			players: ["alice", "bob"],
			creator: "alice",
			turn: 0,
			max_turns: 50,
			map_width: 20,
			map_height: 20,
			seed: 42,
			status: "waiting",
			winner: null,
			victory_type: null,
			archived_at: "2026-04-22T00:00:00Z",
			archived_reason: "manual",
			created_at: "2026-04-20T00:00:00Z",
			updated_at: "2026-04-22T00:00:00Z",
			ended_at: null,
		});
		stubList([
			makeGame({
				game_id: "game_mine",
				creator: "alice",
				seats: [
					{ player_id: "alice", user_identity_id: 42 },
					{ player_id: "bob", user_identity_id: 10 },
				],
			}),
		]);
		render(<GamesListClient userIdentityId="42" />, { wrapper: wrapper(newClient()) });

		const button = await screen.findByRole("button", { name: /archive game/i });
		fireEvent.click(button);
		const confirm = await screen.findByRole("button", { name: /^archive$/i });
		fireEvent.click(confirm);

		await waitFor(() => expect(archiveSpy).toHaveBeenCalledWith("game_mine"));
	});
});
