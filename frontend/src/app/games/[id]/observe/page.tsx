"use client";

import { useParams } from "next/navigation";
import { useEffect } from "react";
import { EventLog } from "@/components/event-log";
import { GameToolbar } from "@/components/game-toolbar";
import { MapCanvas } from "@/components/map-canvas";
import { PlayerList } from "@/components/player-list";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	selectCurrentGameState,
	selectIsLive,
	useGameStore,
} from "@/store/game-store";

export default function ObservePage() {
	const { id: gameId } = useParams<{ id: string }>();

	const connectToGame = useGameStore((state) => state.connectToGame);
	const gameState = useGameStore(selectCurrentGameState);
	const isLive = useGameStore(selectIsLive);
	const connectionStatus = useGameStore((state) => state.connectionStatus);
	const selectedPlayer = useGameStore((state) => state.selectedPlayer);
	const fogOfWarEnabled = useGameStore((state) => state.fogOfWarEnabled);
	const setSelectedPlayer = useGameStore((state) => state.setSelectedPlayer);
	const toggleFogOfWar = useGameStore((state) => state.toggleFogOfWar);
	const isLoading = useGameStore((state) => state.isLoading);
	const error = useGameStore((state) => state.error);

	useEffect(() => {
		if (gameId) {
			connectToGame(gameId).catch(console.error);
		}
	}, [gameId, connectToGame]);

	if (isLoading) {
		return (
			<div className="flex items-center justify-center h-screen">
				<div className="text-center">
					<div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4"></div>
					<p>Connecting to game...</p>
				</div>
			</div>
		);
	}

	if (error) {
		return (
			<div className="flex items-center justify-center h-screen">
				<div className="text-center text-red-500">
					<p>Failed to connect to game: {error}</p>
				</div>
			</div>
		);
	}

	if (!gameState) {
		return (
			<div className="flex items-center justify-center h-screen">
				<p>No game state available</p>
			</div>
		);
	}

	return (
		<div className="h-screen flex flex-col">
			{/* Header */}
			<div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="container mx-auto px-4 py-3 flex items-center justify-between">
					<div className="flex items-center gap-4">
						<h1 className="text-xl font-semibold">Game: {gameId}</h1>
						<Badge variant={isLive ? "default" : "secondary"}>
							{isLive ? "Live" : "Historical"}
						</Badge>
						<Badge
							variant={connectionStatus === "open" ? "default" : "destructive"}
						>
							{typeof connectionStatus === "string"
								? connectionStatus
								: "unknown"}
						</Badge>
					</div>
					<div className="text-sm text-muted-foreground">
						Turn {gameState.turn} / {gameState.max_turns}
					</div>
				</div>
			</div>

			{/* Toolbar */}
			<GameToolbar />

			{/* Main Content */}
			<div className="flex-1 flex overflow-hidden">
				{/* Map Area */}
				<div className="flex-1 relative">
					<MapCanvas
						gameState={gameState}
						selectedPlayer={selectedPlayer || undefined}
						fogOfWarEnabled={fogOfWarEnabled}
					/>
				</div>

				{/* Sidebar */}
				<div className="w-80 border-l bg-background/95 backdrop-blur">
					<Tabs defaultValue="players" className="h-full flex flex-col">
						<TabsList className="grid w-full grid-cols-3">
							<TabsTrigger value="players">Players</TabsTrigger>
							<TabsTrigger value="events">Events</TabsTrigger>
							<TabsTrigger value="stats">Stats</TabsTrigger>
						</TabsList>

						<TabsContent value="players" className="flex-1 overflow-hidden">
							<PlayerList
								players={gameState.players}
								gameState={gameState}
								selectedPlayer={selectedPlayer || undefined}
								onPlayerSelect={setSelectedPlayer}
								onFogToggle={toggleFogOfWar}
							/>
						</TabsContent>

						<TabsContent value="events" className="flex-1 overflow-hidden">
							<EventLog />
						</TabsContent>

						<TabsContent value="stats" className="flex-1 overflow-hidden p-4">
							<Card>
								<CardHeader>
									<CardTitle>Game Statistics</CardTitle>
								</CardHeader>
								<CardContent>
									<div className="space-y-2 text-sm">
										<div className="flex justify-between">
											<span>Total Units:</span>
											<span>{Object.keys(gameState.units).length}</span>
										</div>
										<div className="flex justify-between">
											<span>Total Cities:</span>
											<span>{Object.keys(gameState.cities).length}</span>
										</div>
										<div className="flex justify-between">
											<span>Map Size:</span>
											<span>
												{gameState.map_width}×{gameState.map_height}
											</span>
										</div>
									</div>
								</CardContent>
							</Card>
						</TabsContent>
					</Tabs>
				</div>
			</div>
		</div>
	);
}
