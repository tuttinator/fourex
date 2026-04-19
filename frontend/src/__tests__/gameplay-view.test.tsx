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
	}) => void;
	selectedUnitId?: number | null;
	highlightedTiles?: { x: number; y: number }[];
};

vi.mock("@/components/pixi-map", () => ({
	PixiMap: ({
		onTileClick,
		selectedUnitId,
		highlightedTiles,
	}: MockPixiProps) => (
		<div data-testid="mock-pixi">
			<span data-testid="selected-unit-id">{selectedUnitId ?? "none"}</span>
			<span data-testid="highlight-count">
				{highlightedTiles?.length ?? 0}
			</span>
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
	},
	cities: {},
	players: ["alice", "bob"],
	diplomacy: {},
	stockpiles: {
		alice: { food: 0, wood: 0, ore: 0, crystal: 0 },
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
});
