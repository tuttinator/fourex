import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";

import { useLobbyEvents } from "@/hooks/use-lobby-events";

type WsHandler = ((event: { data: string }) => void) | null;

class FakeWebSocket {
	static lastInstance: FakeWebSocket | null = null;
	static openInstances = 0;

	readyState = 0;
	onopen: (() => void) | null = null;
	onmessage: WsHandler = null;
	onclose: (() => void) | null = null;
	onerror: (() => void) | null = null;
	url: string;

	constructor(url: string) {
		this.url = url;
		FakeWebSocket.lastInstance = this;
		FakeWebSocket.openInstances += 1;
	}

	close() {
		FakeWebSocket.openInstances -= 1;
		this.onclose?.();
	}
}

beforeEach(() => {
	FakeWebSocket.lastInstance = null;
	FakeWebSocket.openInstances = 0;
	// @ts-expect-error - override DOM type with a controllable fake.
	global.WebSocket = FakeWebSocket;
	localStorage.clear();
});

function wrapper(client: QueryClient) {
	return function Wrapper({ children }: { children: ReactNode }) {
		return createElement(QueryClientProvider, { client }, children);
	};
}

describe("useLobbyEvents", () => {
	it("stays idle when no api key is stored for the game", () => {
		const client = new QueryClient();
		const { result } = renderHook(() => useLobbyEvents("g1"), {
			wrapper: wrapper(client),
		});
		expect(result.current.status).toBe("idle");
		expect(FakeWebSocket.lastInstance).toBeNull();
	});

	it("opens an authenticated socket when a key is stored", () => {
		localStorage.setItem("parley.gamekey.g1", "fx_test");
		const client = new QueryClient();
		renderHook(() => useLobbyEvents("g1"), { wrapper: wrapper(client) });
		expect(FakeWebSocket.lastInstance).not.toBeNull();
		expect(FakeWebSocket.lastInstance!.url).toContain("game_id=g1");
		expect(FakeWebSocket.lastInstance!.url).toContain("api_key=fx_test");
		expect(FakeWebSocket.lastInstance!.url.startsWith("ws")).toBe(true);
	});

	it("invalidates game-detail query on lobby.* events", async () => {
		localStorage.setItem("parley.gamekey.g1", "fx_test");
		const client = new QueryClient();
		const invalidate = vi.spyOn(client, "invalidateQueries");
		renderHook(() => useLobbyEvents("g1"), { wrapper: wrapper(client) });

		act(() => {
			FakeWebSocket.lastInstance!.onmessage?.({
				data: JSON.stringify({
					type: "lobby.player_joined",
					game_id: "g1",
					player_id: "bob",
					players: ["alice", "bob"],
				}),
			});
		});

		await waitFor(() => {
			expect(invalidate).toHaveBeenCalledWith({
				queryKey: ["game", "g1", "detail"],
			});
		});
	});

	it("closes the socket when the component unmounts", () => {
		localStorage.setItem("parley.gamekey.g1", "fx_test");
		const client = new QueryClient();
		const { unmount } = renderHook(() => useLobbyEvents("g1"), {
			wrapper: wrapper(client),
		});
		expect(FakeWebSocket.openInstances).toBe(1);
		unmount();
		expect(FakeWebSocket.openInstances).toBe(0);
	});
});
