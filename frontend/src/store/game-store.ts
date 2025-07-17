import React from "react";
import { create } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { api, GameWebSocket } from "@/lib/api";
import type {
	CombatEvent,
	DiplomacyEvent,
	GameInfoEvent,
	GameState,
	GameStore,
	PlayerId,
	PromptLog,
	TurnEndEvent,
	TurnStartEvent,
	UIGameEvent,
} from "@/types/game";

// Utility function to convert WebSocket events to UI events
function createUIEvent(
	type: UIGameEvent["type"],
	rawEvent: unknown,
	message: string,
	severity: UIGameEvent["severity"] = "info",
	playerId?: string,
): UIGameEvent {
	return {
		id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
		type,
		timestamp: new Date(),
		message,
		severity,
		playerId,
		turn:
			typeof rawEvent === "object" &&
			rawEvent !== null &&
			"turn" in rawEvent &&
			typeof rawEvent.turn === "number"
				? rawEvent.turn
				: undefined,
		rawEvent: rawEvent as Record<string, unknown>,
	};
}

interface GameStoreActions {
	setGameId: (gameId: string) => void;
	setGameState: (turn: number, state: GameState) => void;
	setSelectedTurn: (turn: number) => void;
	setSelectedPlayer: (player: PlayerId | null) => void;
	toggleFogOfWar: () => void;
	toggleDiffMode: () => void;
	setConnectionStatus: (status: GameStore["connectionStatus"]) => void;
	setPrompts: (turn: number, prompts: PromptLog[]) => void;
	setLoading: (loading: boolean) => void;
	setError: (error: string | null) => void;
	addEvent: (event: UIGameEvent) => void;
	clearEvents: () => void;

	// Actions
	connectToGame: (gameId: string) => Promise<void>;
	loadSnapshot: (turn: number) => Promise<void>;
	loadPrompts: (turn: number) => Promise<void>;
	seekToTurn: (turn: number) => Promise<void>;
	disconnect: () => void;

	// WebSocket
	ws: GameWebSocket | null;
}

export const useGameStore = create<GameStore & GameStoreActions>()(
	devtools(
		subscribeWithSelector((set, get) => ({
			// State
			gameId: null,
			turns: {},
			latestTurn: 0,
			selectedTurn: 0,
			prompts: {},
			events: [],
			connectionStatus: "closed",
			selectedPlayer: null,
			fogOfWarEnabled: true,
			diffMode: false,
			autoZoom: true,
			isLoading: false,
			error: null,
			ws: null,

			// Actions
			setGameId: (gameId) => set({ gameId }),

			setGameState: (turn, state) =>
				set((prev) => ({
					turns: { ...prev.turns, [turn]: state },
					latestTurn: Math.max(prev.latestTurn, turn),
				})),

			setSelectedTurn: (turn) => set({ selectedTurn: turn }),

			setSelectedPlayer: (player) => set({ selectedPlayer: player }),

			toggleFogOfWar: () =>
				set((prev) => ({
					fogOfWarEnabled: !prev.fogOfWarEnabled,
				})),

			toggleDiffMode: () =>
				set((prev) => ({
					diffMode: !prev.diffMode,
				})),

			setConnectionStatus: (status) => set({ connectionStatus: status }),

			setPrompts: (turn, prompts) =>
				set((prev) => ({
					prompts: { ...prev.prompts, [turn]: prompts },
				})),

			setLoading: (loading) => set({ isLoading: loading }),

			setError: (error) => set({ error }),

			addEvent: (event) =>
				set((prev) => ({
					events: [event, ...prev.events].slice(0, 100), // Keep only the last 100 events
				})),

			clearEvents: () => set({ events: [] }),

			// Complex actions
			connectToGame: async (gameId: string) => {
				const state = get();

				try {
					set({ isLoading: true, error: null, gameId });

					// Clear previous events when connecting to a new game
					get().clearEvents();

					// Get initial game state
					const gameState = await api.getGameState(gameId);
					set((prev) => ({
						turns: { ...prev.turns, [gameState.turn]: gameState },
						latestTurn: gameState.turn,
						selectedTurn: gameState.turn,
					}));

					// Set up WebSocket connection
					if (state.ws) {
						state.ws.disconnect();
					}

					const ws = new GameWebSocket(gameId);
					set({ ws });

					// WebSocket event handlers
					ws.on("connection", (status: string) => {
						console.log("WebSocket connection status:", status);
						set({ connectionStatus: status as GameStore["connectionStatus"] });
					});

					ws.on(
						"connected",
						(event: { type: string; status: string; game_id: string }) => {
							console.log("Received connected event:", event);
							// Connected event means we're successfully connected
							set({ connectionStatus: "open" });
						},
					);

					ws.on("game_info", (event: GameInfoEvent) => {
						console.log("Received game info:", event);
						// Game info means we're successfully connected (redundant but safe)
						set({ connectionStatus: "open" });

						// Add connection event to UI
						const uiEvent = createUIEvent(
							"game_info",
							event,
							`Connected to game: ${event.message}`,
							"info",
						);
						get().addEvent(uiEvent);
					});

					ws.on("turn_end", (event: TurnEndEvent) => {
						const { turn, game_id } = event;

						// Add turn end event to UI
						const uiEvent = createUIEvent(
							"turn_end",
							event,
							`Turn ${turn} ended`,
							"info",
						);
						get().addEvent(uiEvent);

						// Load the new game state
						api
							.getGameState(game_id)
							.then((newState) => {
								set((prev) => ({
									turns: { ...prev.turns, [turn]: newState },
									latestTurn: Math.max(prev.latestTurn, turn),
								}));
							})
							.catch(console.error);
					});

					ws.on("turn_start", (event: TurnStartEvent) => {
						console.log("Turn started:", event);

						// Add turn start event to UI
						const uiEvent = createUIEvent(
							"turn_start",
							event,
							`Turn ${event.turn} started`,
							"info",
						);
						get().addEvent(uiEvent);
					});

					ws.on("diplomacy", (event: DiplomacyEvent) => {
						console.log("Diplomacy event:", event);

						// Add diplomacy event to UI
						const message = `${event.from_player} changed diplomatic stance with ${event.to_player} to ${event.new_state}`;
						const severity =
							event.new_state === "war"
								? "error"
								: event.new_state === "alliance"
									? "info"
									: "warning";
						const uiEvent = createUIEvent(
							"diplomacy",
							event,
							message,
							severity,
							event.from_player,
						);
						get().addEvent(uiEvent);
					});

					ws.on("combat", (event: CombatEvent) => {
						console.log("Combat event:", event);

						// Add combat event to UI
						const message = `Unit ${event.attacker_id} attacks Unit ${event.target_id} for ${event.damage} damage (${event.result})`;
						const uiEvent = createUIEvent("combat", event, message, "warning");
						get().addEvent(uiEvent);
					});

					// Handle player actions
					ws.on("player_action", (event: Record<string, unknown>) => {
						console.log("Player action:", event);

						if (event.player_id && event.action) {
							const actionType =
								typeof event.action === "object" &&
								event.action !== null &&
								"type" in event.action
									? event.action.type
									: "unknown";
							const message = `${event.player_id} performed action: ${actionType}`;
							const uiEvent = createUIEvent(
								"player_action",
								event,
								message,
								"info",
								event.player_id as string,
							);
							get().addEvent(uiEvent);
						}
					});

					await ws.connect();
				} catch (error) {
					const message =
						error instanceof Error
							? error.message
							: "Failed to connect to game";
					set({ error: message, connectionStatus: "error" });
					throw error;
				} finally {
					set({ isLoading: false });
				}
			},

			loadSnapshot: async (turn: number) => {
				const state = get();
				if (!state.gameId) return;

				// Return cached version if available
				if (state.turns[turn]) return;

				try {
					set({ isLoading: true });
					const snapshot = await api.getSnapshot(state.gameId, turn);
					set((prev) => ({
						turns: { ...prev.turns, [turn]: snapshot },
					}));
				} catch (error) {
					const message =
						error instanceof Error ? error.message : "Failed to load snapshot";
					set({ error: message });
					throw error;
				} finally {
					set({ isLoading: false });
				}
			},

			loadPrompts: async (turn: number) => {
				const state = get();
				if (!state.gameId) return;

				// Return cached version if available
				if (state.prompts[turn]) return;

				try {
					const prompts = await api.getPrompts(state.gameId, turn);
					set((prev) => ({
						prompts: { ...prev.prompts, [turn]: prompts },
					}));
				} catch (error) {
					console.error("Failed to load prompts:", error);
					// Don't throw for prompts as they're not critical
				}
			},

			seekToTurn: async (turn: number) => {
				const state = get();

				set({ selectedTurn: turn });

				// Load snapshot if not cached
				if (!state.turns[turn]) {
					await get().loadSnapshot(turn);
				}

				// Load prompts for the turn
				get().loadPrompts(turn);
			},

			disconnect: () => {
				const state = get();
				if (state.ws) {
					state.ws.disconnect();
				}
				set({
					ws: null,
					connectionStatus: "closed",
					gameId: null,
					turns: {},
					prompts: {},
					selectedTurn: 0,
					latestTurn: 0,
				});
			},
		})),
		{ name: "game-store" },
	),
);

// Selectors for performance
export const selectCurrentGameState = (state: GameStore) =>
	state.turns[state.selectedTurn];

export const selectLatestGameState = (state: GameStore) =>
	state.turns[state.latestTurn];

export const selectCurrentPrompts = (state: GameStore) =>
	state.prompts[state.selectedTurn] || [];

export const selectIsLive = (state: GameStore) =>
	state.selectedTurn === state.latestTurn;

export const selectTurnRange = (state: GameStore) => ({
	min: Math.min(...Object.keys(state.turns).map(Number)),
	max: Math.max(...Object.keys(state.turns).map(Number)),
});

// Hook for connecting to a game with cleanup
export function useGameConnection(gameId: string | null) {
	const connectToGame = useGameStore((state) => state.connectToGame);
	const disconnect = useGameStore((state) => state.disconnect);

	React.useEffect(() => {
		if (gameId) {
			connectToGame(gameId).catch(console.error);
		}

		return () => {
			disconnect();
		};
	}, [gameId, connectToGame, disconnect]);
}
