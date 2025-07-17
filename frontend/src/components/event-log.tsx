"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatRelativeTime } from "@/lib/utils";
import { useGameStore } from "@/store/game-store";
import type { UIGameEvent } from "@/types/game";

export function EventLog() {
	const events = useGameStore((state) => state.events);

	const getSeverityColor = (severity: UIGameEvent["severity"]) => {
		switch (severity) {
			case "info":
				return "default";
			case "warning":
				return "secondary";
			case "error":
				return "destructive";
			default:
				return "default";
		}
	};

	const getTypeIcon = (type: UIGameEvent["type"]) => {
		switch (type) {
			case "turn_start":
				return "▶️";
			case "turn_end":
				return "⏹️";
			case "combat":
				return "⚔️";
			case "diplomacy":
				return "🤝";
			case "city_founded":
				return "🏛️";
			case "unit_trained":
				return "👥";
			case "player_action":
				return "⚡";
			case "game_info":
				return "ℹ️";
			default:
				return "ℹ️";
		}
	};

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-3">
				<CardTitle className="text-sm">Event Log</CardTitle>
			</CardHeader>
			<CardContent className="flex-1 p-0">
				<ScrollArea className="h-full px-4 pb-4">
					<div className="space-y-3">
						{events.length === 0 ? (
							<div className="text-center text-muted-foreground py-8">
								<p className="text-sm">No events yet...</p>
								<p className="text-xs mt-2">
									Events will appear here as the game progresses
								</p>
							</div>
						) : (
							events.map((event) => (
								<div
									key={event.id}
									className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 hover:bg-muted/80 transition-colors"
								>
									<span className="text-sm">{getTypeIcon(event.type)}</span>
									<div className="flex-1 min-w-0">
										<div className="flex items-center gap-2 mb-1">
											<Badge
												variant={getSeverityColor(event.severity)}
												className="text-xs"
											>
												{event.type.replace("_", " ")}
											</Badge>
											<span className="text-xs text-muted-foreground">
												{formatRelativeTime(event.timestamp)}
											</span>
											{event.turn !== undefined && (
												<span className="text-xs text-muted-foreground">
													T{event.turn}
												</span>
											)}
										</div>
										<p className="text-sm text-foreground break-words">
											{event.message}
										</p>
										{event.playerId && (
											<p className="text-xs text-muted-foreground mt-1">
												Player: {event.playerId}
											</p>
										)}
									</div>
								</div>
							))
						)}
					</div>
				</ScrollArea>
			</CardContent>
		</Card>
	);
}
