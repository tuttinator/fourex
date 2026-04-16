"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { GameState } from "@/types/game";
import { PLAYER_COLORS } from "@/types/game";

interface EventLogProps {
	gameState?: GameState;
}

export function EventLog({ gameState }: EventLogProps) {
	if (!gameState) {
		return (
			<Card className="h-full flex flex-col">
				<CardHeader className="pb-3">
					<CardTitle className="text-sm">Event Log</CardTitle>
				</CardHeader>
				<CardContent className="flex-1">
					<div className="text-center text-muted-foreground py-8">
						<p className="text-sm">No events available</p>
					</div>
				</CardContent>
			</Card>
		);
	}

	const playerSummaries = gameState.players.map((player, index) => {
		const units = Object.values(gameState.units).filter(
			(u) => u.owner === player,
		);
		const cities = Object.values(gameState.cities).filter(
			(c) => c.owner === player,
		);
		const resources = gameState.stockpiles[player];
		const territory = gameState.tiles.filter(
			(t) => t.owner === player,
		).length;

		return {
			player,
			index,
			unitCount: units.length,
			cityCount: cities.length,
			territory,
			totalResources: resources
				? resources.food + resources.wood + resources.ore + resources.crystal
				: 0,
		};
	});

	return (
		<div className="p-4 space-y-4">
			<Card>
				<CardHeader className="pb-3">
					<CardTitle className="text-sm">
						Turn {gameState.turn} Summary
					</CardTitle>
				</CardHeader>
				<CardContent className="space-y-3">
					{playerSummaries.map(
						({
							player,
							index,
							unitCount,
							cityCount,
							territory,
							totalResources,
						}) => (
							<div key={player} className="space-y-1">
								<div className="flex items-center gap-2">
									<div
										className="w-2.5 h-2.5 rounded-full"
										style={{
											backgroundColor:
												PLAYER_COLORS[index] ?? "#888",
										}}
									/>
									<span className="text-sm font-medium">
										{player}
									</span>
								</div>
								<div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-muted-foreground ml-4">
									<span>Units: {unitCount}</span>
									<span>Cities: {cityCount}</span>
									<span>Territory: {territory}</span>
									<span>Resources: {totalResources}</span>
								</div>
							</div>
						),
					)}
				</CardContent>
			</Card>

			<Card>
				<CardHeader className="pb-3">
					<CardTitle className="text-sm">Turn Actions</CardTitle>
				</CardHeader>
				<CardContent>
					<p className="text-xs text-muted-foreground text-center py-4">
						Detailed action results will be available with turn
						replay (Phase 7).
					</p>
				</CardContent>
			</Card>
		</div>
	);
}
