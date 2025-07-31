"use client";

import {
	AlertTriangle,
	Brain,
	CheckCircle,
	ChevronDown,
	ChevronRight,
	Clock,
	DollarSign,
	Target,
	User,
	XCircle,
} from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { JsonViewer } from "./json-viewer";

interface TurnLogData {
	turn_number: number;
	player_id: string;
	game_id: string;
	timestamp: number;
	duration_ms: number;
	success: boolean;
	error_message?: string;
	game_state_summary?: {
		turn: number;
		max_turns: number;
		my_units: number;
		my_cities: number;
		my_resources: Record<string, number>;
	};
	system_prompt: string;
	user_prompt: string;
	llm_response?: {
		content: string;
		thinking?: string;
		tokens_in: number;
		tokens_out: number;
		latency_ms: number;
		model: string;
		provider: string;
	};
	actions?: Array<{
		type: string;
		reasoning: string;
		[key: string]: unknown;
	}>;
	strategic_analysis?: string;
	priorities?: string[];
}

interface GameLogData {
	config: {
		game_id: string;
		players: string[];
		personalities?: Record<string, string>;
		max_turns: number;
	};
	turn_logs: Array<{
		turn: number;
		player_actions: Record<
			string,
			{
				success: boolean;
				duration: number;
				plan?: string;
			}
		>;
		turn_start_time: number;
		turn_end_time: number;
	}>;
}

interface LogViewerProps {
	data: unknown;
	filename: string;
}

export function LogViewer({ data, filename }: LogViewerProps) {
	// Determine log type and parse accordingly
	const isTurnLog = filename.includes("turn_");
	const isGameLog = filename.includes("game_log_");

	if (isTurnLog) {
		return <TurnLogViewer data={data as TurnLogData} filename={filename} />;
	} else if (isGameLog) {
		return <GameLogViewer data={data as GameLogData} filename={filename} />;
	} else {
		// Fallback to generic JSON viewer
		return <JsonViewer data={data} />;
	}
}

function TurnLogViewer({
	data,
	filename,
}: {
	data: TurnLogData;
	filename: string;
}) {
	const [expandedSections, setExpandedSections] = useState<Set<string>>(
		new Set(["overview"]),
	);

	const toggleSection = (section: string) => {
		const newExpanded = new Set(expandedSections);
		if (newExpanded.has(section)) {
			newExpanded.delete(section);
		} else {
			newExpanded.add(section);
		}
		setExpandedSections(newExpanded);
	};

	const formatDuration = (ms: number) => {
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	};

	const formatTimestamp = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	return (
		<div className="space-y-6">
			{/* Header */}
			<Card>
				<CardHeader>
					<div className="flex items-center justify-between">
						<div>
							<CardTitle className="flex items-center gap-2">
								<User className="w-5 h-5" />
								{data.player_id} - Turn {data.turn_number}
							</CardTitle>
							<CardDescription>{filename}</CardDescription>
						</div>
						<div className="flex items-center gap-2">
							{data.success ? (
								<Badge className="bg-green-500">
									<CheckCircle className="w-3 h-3 mr-1" />
									Success
								</Badge>
							) : (
								<Badge variant="destructive">
									<XCircle className="w-3 h-3 mr-1" />
									Failed
								</Badge>
							)}
							<Badge variant="outline">
								<Clock className="w-3 h-3 mr-1" />
								{formatDuration(data.duration_ms)}
							</Badge>
						</div>
					</div>
				</CardHeader>
			</Card>

			{/* Overview */}
			<Card>
				<CardHeader
					className="cursor-pointer"
					onClick={() => toggleSection("overview")}
				>
					<CardTitle className="flex items-center gap-2">
						{expandedSections.has("overview") ? (
							<ChevronDown className="w-4 h-4" />
						) : (
							<ChevronRight className="w-4 h-4" />
						)}
						Game State Overview
					</CardTitle>
				</CardHeader>
				{expandedSections.has("overview") && (
					<CardContent>
						<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
							<div>
								<div className="text-sm text-muted-foreground">Turn</div>
								<div className="text-lg font-semibold">
									{data.game_state_summary.turn} /{" "}
									{data.game_state_summary.max_turns}
								</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">Units</div>
								<div className="text-lg font-semibold">
									{data.game_state_summary.my_units}
								</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">Cities</div>
								<div className="text-lg font-semibold">
									{data.game_state_summary.my_cities}
								</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">Timestamp</div>
								<div className="text-sm">{formatTimestamp(data.timestamp)}</div>
							</div>
						</div>

						<div className="mt-4">
							<div className="text-sm text-muted-foreground mb-2">
								Resources
							</div>
							<div className="flex flex-wrap gap-2">
								{Object.entries(data.game_state_summary.my_resources).map(
									([resource, amount]) => (
										<Badge
											key={resource}
											variant="outline"
											className="flex items-center gap-1"
										>
											<DollarSign className="w-3 h-3" />
											{resource}: {amount}
										</Badge>
									),
								)}
							</div>
						</div>
					</CardContent>
				)}
			</Card>

			{/* LLM Performance */}
			<Card>
				<CardHeader
					className="cursor-pointer"
					onClick={() => toggleSection("llm")}
				>
					<CardTitle className="flex items-center gap-2">
						{expandedSections.has("llm") ? (
							<ChevronDown className="w-4 h-4" />
						) : (
							<ChevronRight className="w-4 h-4" />
						)}
						<Brain className="w-4 h-4" />
						LLM Performance
					</CardTitle>
				</CardHeader>
				{expandedSections.has("llm") && (
					<CardContent>
						<div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
							<div>
								<div className="text-sm text-muted-foreground">Model</div>
								<div className="font-medium">{data.llm_response.model}</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">Provider</div>
								<div className="font-medium">{data.llm_response.provider}</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">
									Tokens In/Out
								</div>
								<div className="font-medium">
									{data.llm_response.tokens_in} / {data.llm_response.tokens_out}
								</div>
							</div>
							<div>
								<div className="text-sm text-muted-foreground">Latency</div>
								<div className="font-medium">
									{formatDuration(data.llm_response.latency_ms)}
								</div>
							</div>
						</div>

						{data.strategic_analysis && (
							<div className="mt-4">
								<div className="text-sm text-muted-foreground mb-2">
									Strategic Analysis
								</div>
								<p className="text-sm bg-muted p-3 rounded">
									{data.strategic_analysis}
								</p>
							</div>
						)}

						{data.priorities && data.priorities.length > 0 && (
							<div className="mt-4">
								<div className="text-sm text-muted-foreground mb-2">
									Priorities
								</div>
								<div className="flex flex-wrap gap-1">
									{data.priorities.map((priority) => (
										<Badge key={priority} variant="secondary">
											{priority}
										</Badge>
									))}
								</div>
							</div>
						)}
					</CardContent>
				)}
			</Card>

			{/* Actions */}
			{data.actions && data.actions.length > 0 && (
				<Card>
					<CardHeader
						className="cursor-pointer"
						onClick={() => toggleSection("actions")}
					>
						<CardTitle className="flex items-center gap-2">
							{expandedSections.has("actions") ? (
								<ChevronDown className="w-4 h-4" />
							) : (
								<ChevronRight className="w-4 h-4" />
							)}
							<Target className="w-4 h-4" />
							Actions ({data.actions.length})
						</CardTitle>
					</CardHeader>
					{expandedSections.has("actions") && (
						<CardContent>
							<div className="space-y-3">
								{data.actions.map((action) => (
									<Card
										key={`${action.type}-${action.reasoning.substring(0, 20)}`}
										className="bg-muted/50"
									>
										<CardContent className="pt-4">
											<div className="flex items-center justify-between mb-2">
												<Badge className="font-mono">{action.type}</Badge>
											</div>
											<p className="text-sm text-muted-foreground">
												{action.reasoning}
											</p>
										</CardContent>
									</Card>
								))}
							</div>
						</CardContent>
					)}
				</Card>
			)}

			{/* Error Message */}
			{!data.success && data.error_message && (
				<Card className="border-destructive">
					<CardHeader>
						<CardTitle className="flex items-center gap-2 text-destructive">
							<AlertTriangle className="w-4 h-4" />
							Error Details
						</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-sm bg-destructive/10 p-3 rounded border border-destructive/20">
							{data.error_message}
						</p>
					</CardContent>
				</Card>
			)}

			{/* Raw Data */}
			<Card>
				<CardHeader
					className="cursor-pointer"
					onClick={() => toggleSection("raw")}
				>
					<CardTitle className="flex items-center gap-2">
						{expandedSections.has("raw") ? (
							<ChevronDown className="w-4 h-4" />
						) : (
							<ChevronRight className="w-4 h-4" />
						)}
						Raw JSON Data
					</CardTitle>
				</CardHeader>
				{expandedSections.has("raw") && (
					<CardContent>
						<JsonViewer data={data} />
					</CardContent>
				)}
			</Card>
		</div>
	);
}

function GameLogViewer({
	data,
	filename,
}: {
	data: GameLogData;
	filename: string;
}) {
	const [selectedTurn, setSelectedTurn] = useState<number>(0);

	return (
		<div className="space-y-6">
			{/* Header */}
			<Card>
				<CardHeader>
					<CardTitle>Game Log: {data.config.game_id}</CardTitle>
					<CardDescription>{filename}</CardDescription>
					<div className="flex flex-wrap gap-2 mt-2">
						<Badge>Players: {data.config.players.length}</Badge>
						<Badge>Max Turns: {data.config.max_turns}</Badge>
						<Badge>Logged Turns: {data.turn_logs.length}</Badge>
					</div>
				</CardHeader>
			</Card>

			{/* Players */}
			<Card>
				<CardHeader>
					<CardTitle>Players</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
						{data.config.players.map((player) => (
							<Card key={player} className="bg-muted/50">
								<CardContent className="pt-4">
									<div className="font-medium">{player}</div>
									{data.config.personalities?.[player] && (
										<Badge variant="outline" className="mt-2">
											{data.config.personalities[player]}
										</Badge>
									)}
								</CardContent>
							</Card>
						))}
					</div>
				</CardContent>
			</Card>

			{/* Turn Browser */}
			<Card>
				<CardHeader>
					<CardTitle>Turn Timeline</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="flex gap-2 flex-wrap mb-4">
						{data.turn_logs.map((turn) => (
							<Button
								key={turn.turn}
								variant={selectedTurn === turn.turn ? "default" : "outline"}
								size="sm"
								onClick={() => setSelectedTurn(turn.turn)}
							>
								Turn {turn.turn}
							</Button>
						))}
					</div>

					{data.turn_logs[selectedTurn] && (
						<div className="space-y-4">
							<div className="text-sm text-muted-foreground">
								Turn {data.turn_logs[selectedTurn].turn} - Duration:{" "}
								{formatDuration(
									data.turn_logs[selectedTurn].turn_end_time -
										data.turn_logs[selectedTurn].turn_start_time,
								)}
							</div>

							<div className="grid gap-4">
								{Object.entries(
									data.turn_logs[selectedTurn].player_actions,
								).map(([player, action]) => (
									<Card key={player} className="bg-muted/50">
										<CardContent className="pt-4">
											<div className="flex items-center justify-between mb-2">
												<div className="font-medium">{player}</div>
												<div className="flex items-center gap-2">
													{action.success ? (
														<Badge className="bg-green-500">Success</Badge>
													) : (
														<Badge variant="destructive">Failed</Badge>
													)}
													<Badge variant="outline">
														{formatDuration(action.duration)}
													</Badge>
												</div>
											</div>
											{action.plan && (
												<p className="text-sm text-muted-foreground">
													{action.plan.substring(0, 200)}...
												</p>
											)}
										</CardContent>
									</Card>
								))}
							</div>
						</div>
					)}
				</CardContent>
			</Card>

			{/* Raw Data */}
			<Card>
				<CardHeader>
					<CardTitle>Raw JSON Data</CardTitle>
				</CardHeader>
				<CardContent>
					<JsonViewer data={data} />
				</CardContent>
			</Card>
		</div>
	);

	function formatDuration(ms: number) {
		if (ms < 1000) return `${Math.round(ms)}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	}
}
