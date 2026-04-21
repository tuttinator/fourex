/**
 * Phase 4 gameplay-tracer UI tests.
 *
 * PixiMap is mocked because Pixi's WebGL init doesn't run under jsdom;
 * useLobbyEvents is mocked so tests can control the `lastEvent` value
 * and assert the turn.resolved handler's effect on queue + selection.
 */

import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { api } from "@/lib/api";
import { GameplayView } from "@/components/gameplay-view";
import type { LobbyEvent } from "@/hooks/use-lobby-events";
import type { GameState } from "@/types/game";

// ---- Mocks ---------------------------------------------------------------

let _lastEvent: LobbyEvent | null = null;

vi.mock("@/hooks/use-lobby-events", () => ({
	useLobbyEvents: () => ({ status: "open", lastEvent: _lastEvent }),
}));

// PixiMap replacement that exposes a couple of simulated clicks and
// echoes props via data attributes so tests can assert the selection /
// highlight pipeline.
type MockPixiProps = {
	onTileClick?: (tile: {
		id: number;
		loc: { x: number; y: number };
		terrain: string;
		unit_id?: number;
		city_id?: number;
	}) => void;
	selectedUnitId?: number | null;
	selectedCityId?: number | null;
	highlightedTiles?: { x: number; y: number }[];
	attackTiles?: { x: number; y: number }[];
};

vi.mock("@/components/pixi-map", () => ({
	PixiMap: ({
		onTileClick,
		selectedUnitId,
		selectedCityId,
		highlightedTiles,
		attackTiles,
	}: MockPixiProps) => (
		<div data-testid="mock-pixi">
			<span data-testid="selected-unit-id">{selectedUnitId ?? "none"}</span>
			<span data-testid="selected-city-id">{selectedCityId ?? "none"}</span>
			<span data-testid="highlight-count">
				{highlightedTiles?.length ?? 0}
			</span>
			<span data-testid="attack-count">{attackTiles?.length ?? 0}</span>
			<button
				data-testid="click-friendly-unit"
				onClick={() =>
					onTileClick?.({
						id: 0,
						loc: { x: 0, y: 0 },
						terrain: "plains",
						unit_id: 1,
					})
				}
			>
				click-unit
			</button>
			<button
				data-testid="click-highlighted-tile"
				onClick={() =>
					onTileClick?.({
						id: 2,
						loc: { x: 1, y: 0 },
						terrain: "plains",
					})
				}
			>
				click-highlight
			</button>
			<button
				data-testid="click-attack-tile"
				onClick={() =>
					onTileClick?.({
						id: 3,
						loc: { x: 2, y: 0 },
						terrain: "plains",
						unit_id: 99,
					})
				}
			>
				click-attack
			</button>
			<button
				data-testid="click-friendly-city"
				onClick={() =>
					onTileClick?.({
						id: 4,
						loc: { x: 3, y: 3 },
						terrain: "plains",
						city_id: 11,
					})
				}
			>
				click-city
			</button>
		</div>
	),
}));

// ---- Fixtures ------------------------------------------------------------

const sampleState: GameState = {
	turn: 3,
	rng_state: 0,
	map_width: 10,
	map_height: 10,
	tiles: [
		{ id: 0, loc: { x: 0, y: 0 }, terrain: "plains", unit_id: 1 },
		{ id: 1, loc: { x: 1, y: 0 }, terrain: "plains" },
		{ id: 2, loc: { x: 2, y: 0 }, terrain: "plains", unit_id: 99 },
		{ id: 3, loc: { x: 3, y: 3 }, terrain: "plains", city_id: 11 },
	],
	units: {
		1: {
			id: 1,
			owner: "alice",
			type: "worker",
			hp: 10,
			moves_left: 2,
			loc: { x: 0, y: 0 },
		},
		99: {
			id: 99,
			owner: "bob",
			type: "soldier",
			hp: 10,
			moves_left: 2,
			loc: { x: 2, y: 0 },
		},
	},
	cities: {
		11: {
			id: 11,
			owner: "alice",
			loc: { x: 3, y: 3 },
			hp: 20,
			buildings: [],
		},
	},
	players: ["alice", "bob"],
	diplomacy: {},
	stockpiles: {
		alice: { food: 50, wood: 50, ore: 10, crystal: 0 },
		bob: { food: 0, wood: 0, ore: 0, crystal: 0 },
	},
	next_unit_id: 2,
	next_city_id: 1,
	max_turns: 100,
};

function wrapper(client: QueryClient) {
	return function Wrapper({ children }: { children: ReactNode }) {
		return (
			<QueryClientProvider client={client}>{children}</QueryClientProvider>
		);
	};
}

function newClient() {
	return new QueryClient({
		defaultOptions: { queries: { retry: false, refetchInterval: false } },
	});
}

function stubTurnSubmissions(
	submitted: string[] = [],
	turn = sampleState.turn,
) {
	return vi.spyOn(api, "getTurnSubmissions").mockResolvedValue({
		game_id: "g1",
		turn,
		players: ["alice", "bob"],
		submitted_players: submitted,
	});
}

function stubMySubmission(submitted = false) {
	return vi.spyOn(api, "getMySubmission").mockResolvedValue({
		game_id: "g1",
		player: "alice",
		turn: sampleState.turn,
		submitted,
		actions: [],
	});
}

function stubDiplomacy(
	overrides: Partial<{
		discovered: string[];
		messages: Array<{
			id: number;
			sender: string;
			recipient: string;
			body: string;
			turn_sent: number;
		}>;
		relations: Array<{
			player_a: string;
			player_b: string;
			state: "peace" | "alliance" | "war";
		}>;
		pending_proposals: Array<{
			id: number;
			proposer: string;
			recipient: string;
			clauses: Array<Record<string, unknown>>;
			turn_proposed: number;
			expires_on_turn: number;
		}>;
		active_treaties: Array<{
			id: number;
			parties: [string, string];
			clauses: Array<Record<string, unknown>>;
			turn_ratified: number;
		}>;
	}> = {},
) {
	return vi.spyOn(api, "getDiplomacy").mockResolvedValue({
		game_id: "g1",
		player: "alice",
		turn: sampleState.turn,
		discovered: overrides.discovered ?? ["alice", "bob"],
		relations: overrides.relations ?? [
			{ player_a: "alice", player_b: "bob", state: "peace" },
		],
		events: [],
		messages: overrides.messages ?? [],
		// @ts-expect-error — test fixture uses open shape for clause dicts
		pending_proposals: overrides.pending_proposals ?? [],
		// @ts-expect-error — test fixture uses open shape for clause dicts
		active_treaties: overrides.active_treaties ?? [],
	});
}

function stubAffordanceQueries() {
	stubTurnSubmissions();
	stubMySubmission();
	stubDiplomacy();
	vi.spyOn(api, "getValidAttacks").mockResolvedValue({
		game_id: "g1",
		unit_id: 1,
		attack_range: 1,
		attack: 0,
		targets: [],
	});
	vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
		game_id: "g1",
		unit_id: 1,
		can_found: false,
		reason: "stub",
		cost: { food: 15 },
	});
	vi.spyOn(api, "getValidImprovements").mockResolvedValue({
		game_id: "g1",
		unit_id: 1,
		tile: { x: 0, y: 0 },
		improvements: [],
	});
	vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
		game_id: "g1",
		city_id: 11,
		units: [],
	});
	vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
		game_id: "g1",
		city_id: 11,
		buildings: [],
	});
}

beforeEach(() => {
	_lastEvent = null;
	vi.restoreAllMocks();
});

afterEach(() => {
	cleanup();
});

// ---- Tests ---------------------------------------------------------------

describe("GameplayView", () => {
	it("selecting a friendly unit fetches valid moves and highlights them", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		const validMoves = vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		// Wait for the state query to resolve so the map renders.
		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-unit"));

		await waitFor(() => expect(validMoves).toHaveBeenCalledWith("g1", 1));
		await waitFor(() =>
			expect(screen.getByTestId("selected-unit-id")).toHaveTextContent("1"),
		);
		await waitFor(() =>
			expect(screen.getByTestId("highlight-count")).toHaveTextContent("1"),
		);
	});

	it("clicking a highlighted tile queues a move; End Turn posts the whole batch", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() =>
			expect(screen.getByTestId("highlight-count")).toHaveTextContent("1"),
		);

		fireEvent.click(screen.getByTestId("click-highlighted-tile"));

		// Queue sidebar now shows the order.
		expect(screen.getByText(/Queued orders \(1\)/)).toBeInTheDocument();
		expect(screen.getByText(/Move unit #1/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));

		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0]).toEqual([
			"g1",
			[{ type: "MOVE", unit_id: 1, to: { x: 1, y: 0 } }],
		]);
	});

	it("removing a queued item before End Turn excludes it from the batch", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "0",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() =>
			expect(screen.getByTestId("highlight-count")).toHaveTextContent("1"),
		);
		fireEvent.click(screen.getByTestId("click-highlighted-tile"));

		expect(screen.getByText(/Queued orders \(1\)/)).toBeInTheDocument();
		fireEvent.click(
			screen.getByRole("button", { name: /Remove queued order/ }),
		);
		expect(screen.getByText(/Queued orders \(0\)/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([]);
	});

	it("turn.resolved clears the queue, drops selection, and invalidates state", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
		});

		const client = newClient();
		const invalidate = vi.spyOn(client, "invalidateQueries");
		const { rerender } = render(
			<GameplayView gameId="g1" currentPlayer="alice" />,
			{ wrapper: wrapper(client) },
		);

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() =>
			expect(screen.getByTestId("highlight-count")).toHaveTextContent("1"),
		);
		fireEvent.click(screen.getByTestId("click-highlighted-tile"));
		expect(screen.getByText(/Queued orders \(1\)/)).toBeInTheDocument();

		// Simulate the WebSocket handing us the canonical resolution event.
		act(() => {
			_lastEvent = {
				type: "turn.resolved",
				game_id: "g1",
				// @ts-expect-error — the hook's shape is open
				turn: 4,
			};
		});
		rerender(<GameplayView gameId="g1" currentPlayer="alice" />);

		await waitFor(() =>
			expect(screen.getByText(/Queued orders \(0\)/)).toBeInTheDocument(),
		);
		expect(screen.getByTestId("selected-unit-id")).toHaveTextContent("none");

		const invalidatedKeys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
		expect(invalidatedKeys).toEqual(
			expect.arrayContaining([
				["game", "g1", "state", "alice"],
				["game", "g1", "detail"],
			]),
		);
	});

	it("per-unit affordance queries refetch when the turn advances (no stale valid-moves across turns)", async () => {
		// Regression: the app's QueryClient uses staleTime: 5 minutes, so a
		// re-selected unit in a later turn would otherwise return the prior
		// turn's cached valid-moves, showing "9 legal moves" with highlighted
		// tiles for a unit whose moves_left has since drained to 0.
		// Keying the query on ``gameState.turn`` forces a fresh fetch.
		const client = new QueryClient({
			defaultOptions: {
				queries: {
					retry: false,
					refetchInterval: false,
					// Match production: long staleTime would mask the bug
					// without the turn-in-key fix.
					staleTime: 5 * 60 * 1000,
				},
			},
		});

		let currentTurn = sampleState.turn;
		vi.spyOn(api, "getGameState").mockImplementation(async () => ({
			...sampleState,
			turn: currentTurn,
		}));
		stubDiplomacy();
		stubTurnSubmissions();
		vi.spyOn(api, "getMySubmission").mockImplementation(async () => ({
			game_id: "g1",
			player: "alice",
			turn: currentTurn,
			submitted: false,
			actions: [],
		}));
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 1,
			attack: 0,
			targets: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: false,
			reason: "stub",
			cost: { food: 15 },
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		const validMovesSpy = vi
			.spyOn(api, "getValidMoves")
			.mockResolvedValue({
				game_id: "g1",
				unit_id: 1,
				moves_left: 2,
				moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
			});

		const { rerender } = render(
			<GameplayView gameId="g1" currentPlayer="alice" />,
			{ wrapper: wrapper(client) },
		);

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		// Turn 3: select, fetch #1.
		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() => expect(validMovesSpy).toHaveBeenCalledTimes(1));

		// Simulate turn.resolved — WS handler clears selection and
		// invalidates gameState; the new turn arrives via the refetch.
		currentTurn = sampleState.turn + 1;
		act(() => {
			_lastEvent = {
				type: "turn.resolved",
				game_id: "g1",
				// @ts-expect-error — the hook's shape is open
				turn: currentTurn,
			};
		});
		rerender(<GameplayView gameId="g1" currentPlayer="alice" />);

		await waitFor(() =>
			expect(screen.getByTestId("selected-unit-id")).toHaveTextContent(
				"none",
			),
		);

		// Re-select the same unit on the new turn. With the turn-in-key
		// fix, this causes a fresh fetch; without it, the cached turn-3
		// response would be returned and the UI would show stale moves.
		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() => expect(validMovesSpy).toHaveBeenCalledTimes(2));
	});

	it("turn rollover detected via mySubmission refetch clears stale queue when turn.resolved WS is missed", async () => {
		// Regression: if the turn.resolved WebSocket frame is missed
		// (backgrounded tab, reconnect, polling fallback), the hydration
		// effect is the only path that notices the new turn. It must mirror
		// the WS handler's state reset so the user doesn't see last turn's
		// orders still sitting in the queue.
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubDiplomacy();
		stubTurnSubmissions();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [{ x: 1, y: 0, terrain: "plains", distance: 1 }],
		});
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 1,
			attack: 0,
			targets: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: false,
			reason: "stub",
			cost: { food: 15 },
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		const mySubmissionSpy = vi
			.spyOn(api, "getMySubmission")
			.mockResolvedValue({
				game_id: "g1",
				player: "alice",
				turn: sampleState.turn,
				submitted: false,
				actions: [],
			});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		// Queue an order on the current turn.
		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() =>
			expect(screen.getByTestId("highlight-count")).toHaveTextContent("1"),
		);
		fireEvent.click(screen.getByTestId("click-highlighted-tile"));
		expect(screen.getByText(/Queued orders \(1\)/)).toBeInTheDocument();

		// Simulate a turn rollover that we learn about only through
		// mySubmission refetching with a higher turn — no turn.resolved
		// WebSocket frame arrives.
		mySubmissionSpy.mockResolvedValue({
			game_id: "g1",
			player: "alice",
			turn: sampleState.turn + 1,
			submitted: false,
			actions: [],
		});
		await act(async () => {
			await client.invalidateQueries({
				queryKey: ["game", "g1", "mySubmission"],
			});
		});

		await waitFor(() =>
			expect(screen.getByText(/Queued orders \(0\)/)).toBeInTheDocument(),
		);
		expect(screen.getByTestId("selected-unit-id")).toHaveTextContent("none");
	});

	it("clicking an attack-target tile queues an ATTACK", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubDiplomacy();
		stubMySubmission();
		stubTurnSubmissions();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: false,
			reason: "stub",
			cost: { food: 15 },
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 2,
			attack: 3,
			targets: [
				{
					target_type: "unit",
					target_id: 99,
					x: 2,
					y: 0,
					distance: 2,
					owner: "bob",
					hp: 10,
					diplomatic_state: "war",
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		await waitFor(() =>
			expect(screen.getByTestId("attack-count")).toHaveTextContent("1"),
		);

		fireEvent.click(screen.getByTestId("click-attack-tile"));
		expect(screen.getByText(/Attack unit #99/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{
				type: "ATTACK",
				attacker_id: 1,
				target_id: 99,
				target_type: "unit",
			},
		]);
	});

	it("Found City control queues a FOUND_CITY for the selected worker", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubDiplomacy();
		stubMySubmission();
		stubTurnSubmissions();
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [],
		});
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 0,
			attack: 0,
			targets: [],
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: true,
			reason: null,
			cost: { food: 15 },
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-unit"));
		const foundButton = await screen.findByRole("button", {
			name: /Found city/,
		});
		fireEvent.click(foundButton);

		expect(screen.getByText(/Found city \(worker #1\)/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{ type: "FOUND_CITY", worker_id: 1 },
		]);
	});

	it("submission roster hydrates from /turn-submissions and reflects turn.submitted events", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		// Stub everything but turn-submissions so we can assert the
		// roster's hydration + live-event path.
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 1,
			attack: 0,
			targets: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: false,
			reason: "stub",
			cost: { food: 15 },
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [],
		});
		stubMySubmission();
		stubTurnSubmissions(["bob"]);
		stubDiplomacy();

		const client = newClient();
		const { rerender } = render(
			<GameplayView gameId="g1" currentPlayer="alice" />,
			{ wrapper: wrapper(client) },
		);

		// Hydration: bob shows as submitted, alice as deciding.
		await waitFor(() =>
			expect(
				screen.getByTestId("submission-row-bob"),
			).toHaveAttribute("data-submitted", "true"),
		);
		expect(screen.getByTestId("submission-row-alice")).toHaveAttribute(
			"data-submitted",
			"false",
		);

		// Live delta: a turn.submitted event carrying both names flips
		// alice to "submitted" too.
		act(() => {
			_lastEvent = {
				type: "turn.submitted",
				game_id: "g1",
				player_id: "alice",
				turn: sampleState.turn,
				submitted_players: ["alice", "bob"],
			} as unknown as LobbyEvent;
		});
		rerender(<GameplayView gameId="g1" currentPlayer="alice" />);

		await waitFor(() =>
			expect(
				screen.getByTestId("submission-row-alice"),
			).toHaveAttribute("data-submitted", "true"),
		);
	});

	it("turn.resolved resets the submission roster for the new turn", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		vi.spyOn(api, "getValidMoves").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			moves_left: 2,
			moves: [],
		});
		vi.spyOn(api, "getValidAttacks").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			attack_range: 1,
			attack: 0,
			targets: [],
		});
		vi.spyOn(api, "getCanFoundCity").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			can_found: false,
			reason: "stub",
			cost: { food: 15 },
		});
		vi.spyOn(api, "getValidImprovements").mockResolvedValue({
			game_id: "g1",
			unit_id: 1,
			tile: { x: 0, y: 0 },
			improvements: [],
		});
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [],
		});
		vi.spyOn(api, "getBuildableBuildings").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			buildings: [],
		});
		stubMySubmission();
		stubTurnSubmissions(["alice", "bob"]);
		stubDiplomacy();

		const client = newClient();
		const { rerender } = render(
			<GameplayView gameId="g1" currentPlayer="alice" />,
			{ wrapper: wrapper(client) },
		);

		await waitFor(() =>
			expect(
				screen.getByTestId("submission-row-alice"),
			).toHaveAttribute("data-submitted", "true"),
		);

		act(() => {
			_lastEvent = {
				type: "turn.resolved",
				game_id: "g1",
				// @ts-expect-error open event shape
				turn: sampleState.turn + 1,
			};
		});
		rerender(<GameplayView gameId="g1" currentPlayer="alice" />);

		await waitFor(() =>
			expect(
				screen.getByTestId("submission-row-alice"),
			).toHaveAttribute("data-submitted", "false"),
		);
		expect(screen.getByTestId("submission-row-bob")).toHaveAttribute(
			"data-submitted",
			"false",
		);
	});

	it("clicking a friendly city opens the city panel and queues a TRAIN_UNIT", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		vi.spyOn(api, "getTrainableUnits").mockResolvedValue({
			game_id: "g1",
			city_id: 11,
			units: [
				{
					unit_type: "scout",
					cost: { food: 10, wood: 5, ore: 0, crystal: 0 },
					affordable: true,
					stats: { hp: 8, moves: 3, sight: 3, attack: 1, attack_range: 1 },
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("click-friendly-city"));
		await waitFor(() =>
			expect(screen.getByTestId("selected-city-id")).toHaveTextContent("11"),
		);

		const trainButton = await screen.findByRole("button", {
			name: /scout/,
		});
		fireEvent.click(trainButton);

		expect(screen.getByText(/Train scout @ city #11/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{ type: "TRAIN_UNIT", city_id: 11, unit_type: "scout" },
		]);
	});

	// --- Phase 7: diplomacy panel ----------------------------------------

	it("diplomacy panel lists opponents, renders the thread, and queues a SEND_MESSAGE on End Turn", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy({
			messages: [
				{
					id: 1,
					sender: "bob",
					recipient: "alice",
					body: "parley?",
					turn_sent: 2,
				},
			],
			active_treaties: [
				{
					id: 7,
					parties: ["alice", "bob"],
					clauses: [],
					turn_ratified: 1,
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);

		// Unread badge surfaces bob's prior message.
		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-unread-bob"),
			).toBeInTheDocument(),
		);

		// Opening the thread with bob clears the unread badge.
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-message-1")).toBeInTheDocument(),
		);
		expect(screen.queryByTestId("diplomacy-unread-bob")).toBeNull();

		// Compose and queue an outbound message.
		const textarea = screen.getByTestId("diplomacy-compose");
		fireEvent.change(textarea, { target: { value: "counter-offer" } });
		fireEvent.click(screen.getByTestId("diplomacy-send"));

		// The queued line is reflected both in the thread preview and in
		// the shared Queued-orders sidebar.
		expect(screen.getByTestId("diplomacy-message-queued")).toBeInTheDocument();
		expect(
			screen.getByText(/Message → bob: counter-offer/),
		).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{
				type: "SEND_MESSAGE",
				recipient: "bob",
				body: "counter-offer",
			},
		]);
	});

	it("diplomacy.message_received bumps the unread badge for the sender's thread", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		// Start with no prior messages — the delta comes from the event.
		const diplomacy = stubDiplomacy({ messages: [] });

		const client = newClient();
		const { rerender } = render(
			<GameplayView gameId="g1" currentPlayer="alice" />,
			{ wrapper: wrapper(client) },
		);

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-opponent-bob"),
			).toHaveAttribute("data-unread", "false"),
		);

		// Flip the stub to include the new message so the query
		// invalidation triggered by the event refetches the updated body.
		diplomacy.mockResolvedValue({
			game_id: "g1",
			player: "alice",
			turn: sampleState.turn,
			discovered: ["alice", "bob"],
			relations: [{ player_a: "alice", player_b: "bob", state: "peace" }],
			events: [],
			messages: [
				{
					id: 9,
					sender: "bob",
					recipient: "alice",
					body: "new intel",
					turn_sent: sampleState.turn,
				},
			],
			pending_proposals: [],
			active_treaties: [],
		});

		act(() => {
			_lastEvent = {
				type: "diplomacy.message_received",
				game_id: "g1",
				// @ts-expect-error open shape
				message: {
					id: 9,
					sender: "bob",
					recipient: "alice",
					body: "new intel",
					turn_sent: sampleState.turn,
				},
			};
		});
		rerender(<GameplayView gameId="g1" currentPlayer="alice" />);

		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-opponent-bob"),
			).toHaveAttribute("data-unread", "true"),
		);
		expect(screen.getByTestId("diplomacy-unread-bob")).toHaveTextContent("1");
	});

	// --- Phase 8: treaty lifecycle ---------------------------------------

	it("accepting an inbound proposal queues RESPOND_TO_TREATY(accept=true)", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy({
			pending_proposals: [
				{
					id: 42,
					proposer: "bob",
					recipient: "alice",
					clauses: [{ clause_type: "free_text", text: "friends?" }],
					turn_proposed: sampleState.turn,
					expires_on_turn: sampleState.turn + 3,
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-opponent-bob")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-accept-42")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("diplomacy-accept-42"));
		expect(
			screen.getByText(/Accept proposal #42/),
		).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{ type: "RESPOND_TO_TREATY", proposal_id: 42, accept: true },
		]);
	});

	it("proposing a free-text treaty queues PROPOSE_TREATY on End Turn", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy();
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-opponent-bob")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-propose-toggle")).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("diplomacy-propose-toggle"));
		fireEvent.click(screen.getByTestId("diplomacy-propose-kind-free_text"));
		fireEvent.change(screen.getByTestId("diplomacy-propose-free-text"), {
			target: { value: "let us be friends" },
		});
		fireEvent.click(screen.getByTestId("diplomacy-propose-submit"));

		expect(
			screen.getByText(/Propose treaty → bob \(free text\)/),
		).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{
				type: "PROPOSE_TREATY",
				recipient: "bob",
				clauses: [{ clause_type: "free_text", text: "let us be friends" }],
			},
		]);
	});

	it("cancelling an active treaty queues CANCEL_TREATY on End Turn", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy({
			active_treaties: [
				{
					id: 7,
					parties: ["alice", "bob"],
					clauses: [{ clause_type: "free_text", text: "nap" }],
					turn_ratified: 1,
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-opponent-bob")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-cancel-treaty-7"),
			).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("diplomacy-cancel-treaty-7"));
		expect(screen.getByText(/Cancel treaty #7/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{ type: "CANCEL_TREATY", treaty_id: 7 },
		]);
	});

	// --- Phase 9: declare war --------------------------------------------

	it("declaring war opens a confirmation and queues DECLARE_WAR on End Turn", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy({
			active_treaties: [
				{
					id: 3,
					parties: ["alice", "bob"],
					clauses: [{ clause_type: "free_text", text: "nap" }],
					turn_ratified: 1,
				},
			],
		});
		const submit = vi.spyOn(api, "submitActions").mockResolvedValue({
			status: "actions_submitted",
			count: "1",
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-opponent-bob")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-declare-war-open"),
			).toBeInTheDocument(),
		);

		fireEvent.click(screen.getByTestId("diplomacy-declare-war-open"));
		// Confirmation surface mentions the treaty-cancellation consequence.
		expect(
			screen.getByText(/1 active treaty will be cancelled/),
		).toBeInTheDocument();
		// Cancelling hides the confirmation without queuing anything.
		fireEvent.click(screen.getByTestId("diplomacy-declare-war-cancel"));
		await waitFor(() =>
			expect(
				screen.getByTestId("diplomacy-declare-war-open"),
			).toBeInTheDocument(),
		);

		// Re-open and confirm.
		fireEvent.click(screen.getByTestId("diplomacy-declare-war-open"));
		fireEvent.click(screen.getByTestId("diplomacy-declare-war-confirm"));
		expect(screen.getByText(/Declare war on bob/)).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /End Turn/ }));
		await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
		expect(submit.mock.calls[0][1]).toEqual([
			{ type: "DECLARE_WAR", target_player: "bob" },
		]);
	});

	it("the Declare War control is hidden when the relation is already war", async () => {
		vi.spyOn(api, "getGameState").mockResolvedValue(sampleState);
		stubAffordanceQueries();
		stubDiplomacy({
			relations: [{ player_a: "alice", player_b: "bob", state: "war" }],
		});

		const client = newClient();
		render(<GameplayView gameId="g1" currentPlayer="alice" />, {
			wrapper: wrapper(client),
		});

		await waitFor(() =>
			expect(screen.getByTestId("mock-pixi")).toBeInTheDocument(),
		);
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-opponent-bob")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("diplomacy-opponent-bob"));
		await waitFor(() =>
			expect(screen.getByTestId("diplomacy-thread")).toBeInTheDocument(),
		);
		expect(
			screen.queryByTestId("diplomacy-declare-war-open"),
		).not.toBeInTheDocument();
	});
});
