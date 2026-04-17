import { describe, it, expect } from "vitest";
import { formatTokenCount } from "@/lib/api";
import type { PromptLogEntry } from "@/types/game";

const mockPrompts: PromptLogEntry[] = [
	{
		player_id: "alice",
		prompt: "What action should alice take?",
		response: "Move scout to (1,0)",
		tokens_in: 500,
		tokens_out: 50,
		latency_ms: 1200,
		llm_provider: "openai",
		llm_model: "gpt-4",
	},
	{
		player_id: "alice",
		prompt: "Follow-up for alice",
		response: "Train worker",
		tokens_in: 300,
		tokens_out: 25,
		latency_ms: 800,
		llm_provider: "openai",
		llm_model: "gpt-4",
	},
	{
		player_id: "bob",
		prompt: "What action should bob take?",
		response: "Move worker to (5,5)",
		tokens_in: 480,
		tokens_out: 45,
		latency_ms: 900,
		llm_provider: "anthropic",
		llm_model: "claude-3-opus",
	},
];

describe("prompt log: grouping by player", () => {
	it("groups prompts by player_id", () => {
		const players = ["alice", "bob", "charlie"];
		const grouped = players
			.map((player) => ({
				player,
				prompts: mockPrompts.filter((p) => p.player_id === player),
			}))
			.filter((g) => g.prompts.length > 0);

		expect(grouped).toHaveLength(2);
		expect(grouped[0].player).toBe("alice");
		expect(grouped[0].prompts).toHaveLength(2);
		expect(grouped[1].player).toBe("bob");
		expect(grouped[1].prompts).toHaveLength(1);
	});

	it("excludes players with no prompts", () => {
		const players = ["alice", "bob", "charlie"];
		const grouped = players
			.map((player) => ({
				player,
				prompts: mockPrompts.filter((p) => p.player_id === player),
			}))
			.filter((g) => g.prompts.length > 0);

		const playerNames = grouped.map((g) => g.player);
		expect(playerNames).not.toContain("charlie");
	});

	it("handles empty prompts array", () => {
		const players = ["alice", "bob"];
		const empty: PromptLogEntry[] = [];
		const grouped = players
			.map((player) => ({
				player,
				prompts: empty.filter((p) => p.player_id === player),
			}))
			.filter((g) => g.prompts.length > 0);

		expect(grouped).toHaveLength(0);
	});
});

describe("prompt log: summary statistics", () => {
	it("calculates total tokens across all prompts", () => {
		const totalTokens = mockPrompts.reduce(
			(sum, p) => sum + p.tokens_in + p.tokens_out,
			0,
		);
		expect(totalTokens).toBe(500 + 50 + 300 + 25 + 480 + 45);
	});

	it("calculates average latency", () => {
		const avgLatency =
			mockPrompts.reduce((sum, p) => sum + p.latency_ms, 0) /
			mockPrompts.length;
		expect(Math.round(avgLatency)).toBe(967);
	});

	it("collects unique providers", () => {
		const providers = Array.from(
			new Set(mockPrompts.map((p) => p.llm_provider).filter(Boolean)),
		);
		expect(providers).toContain("openai");
		expect(providers).toContain("anthropic");
		expect(providers).toHaveLength(2);
	});

	it("per-player token totals are correct", () => {
		const alicePrompts = mockPrompts.filter((p) => p.player_id === "alice");
		const aliceTotal = alicePrompts.reduce(
			(sum, p) => sum + p.tokens_in + p.tokens_out,
			0,
		);
		expect(aliceTotal).toBe(500 + 50 + 300 + 25);
	});
});

describe("prompt log: provider and model metadata", () => {
	it("includes llm_provider and llm_model fields", () => {
		const prompt = mockPrompts[0];
		expect(prompt.llm_provider).toBe("openai");
		expect(prompt.llm_model).toBe("gpt-4");
	});

	it("handles null provider/model gracefully", () => {
		const nullPrompt: PromptLogEntry = {
			player_id: "alice",
			prompt: "test",
			response: "test",
			tokens_in: 100,
			tokens_out: 10,
			latency_ms: 500,
			llm_provider: null,
			llm_model: null,
		};

		const metaParts = [nullPrompt.llm_provider, nullPrompt.llm_model].filter(
			Boolean,
		);
		expect(metaParts).toHaveLength(0);
	});

	it("formats provider/model display string", () => {
		const prompt = mockPrompts[0];
		const display = [prompt.llm_provider, prompt.llm_model]
			.filter(Boolean)
			.join(" / ");
		expect(display).toBe("openai / gpt-4");
	});

	it("formats display when only provider is set", () => {
		const prompt: PromptLogEntry = {
			...mockPrompts[0],
			llm_model: null,
		};
		const display = [prompt.llm_provider, prompt.llm_model]
			.filter(Boolean)
			.join(" / ");
		expect(display).toBe("openai");
	});
});

describe("prompt log: text truncation logic", () => {
	const PREVIEW_LENGTH = 500;

	it("short text does not need truncation", () => {
		const shortText = "Hello world";
		expect(shortText.length > PREVIEW_LENGTH).toBe(false);
	});

	it("long text exceeds preview length", () => {
		const longText = "A".repeat(600);
		expect(longText.length > PREVIEW_LENGTH).toBe(true);
	});

	it("truncated preview ends at preview length", () => {
		const longText = "A".repeat(600);
		const preview = longText.substring(0, PREVIEW_LENGTH);
		expect(preview).toHaveLength(500);
	});
});

describe("prompt log: formatTokenCount utility", () => {
	it("formats small counts as-is", () => {
		expect(formatTokenCount(500)).toBe("500");
		expect(formatTokenCount(999)).toBe("999");
	});

	it("formats thousands with K suffix", () => {
		expect(formatTokenCount(1000)).toBe("1.0K");
		expect(formatTokenCount(1500)).toBe("1.5K");
		expect(formatTokenCount(50000)).toBe("50.0K");
	});

	it("formats millions with M suffix", () => {
		expect(formatTokenCount(1000000)).toBe("1.0M");
		expect(formatTokenCount(2500000)).toBe("2.5M");
	});
});
