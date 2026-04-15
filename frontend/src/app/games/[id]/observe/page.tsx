"use client";

import { useParams } from "next/navigation";
import { useEffect } from "react";
import Link from "next/link";
import { EventLog } from "@/components/event-log";
import { MapCanvas } from "@/components/map-canvas";
import { PlayerList } from "@/components/player-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	selectCurrentGameState,
	useGameStore,
} from "@/store/game-store";
import { AlertCircle, ArrowLeft, Loader2 } from "lucide-react";

export default function ObservePage() {
	const { id: gameId } = useParams<{ id: string }>();

	const loadGameState = useGameStore((state) => state.loadGameState);
	const reset = useGameStore((state) => state.reset);
	const gameState = useGameStore(selectCurrentGameState);
	const selectedPlayer = useGameStore((state) => state.selectedPlayer);
	const fogOfWarEnabled = useGameStore((state) => state.fogOfWarEnabled);
	const setSelectedPlayer = useGameStore((state) => state.setSelectedPlayer);
	const toggleFogOfWar = useGameStore((state) => state.toggleFogOfWar);
	const isLoading = useGameStore((state) => state.isLoading);
	const error = useGameStore((state) => state.error);

	useEffect(() => {
		if (gameId) {
			loadGameState(gameId).catch(console.error);
		}
		return () => {
			reset();
		};
	}, [gameId, loadGameState, reset]);

	if (isLoading) {
		return (
			<div className="flex items-center justify-center h-screen">
				<div className="text-center">
					<Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
					<p>Loading game state...</p>
				</div>
			</div>
		);
	}

	if (error) {
		return (
			<div className="flex items-center justify-center h-screen">
				<div className="text-center">
					<AlertCircle className="h-12 w-12 mx-auto mb-4 text-destructive" />
					<p className="text-destructive mb-4">Failed to load game: {error}</p>
					<Button asChild variant="outline">
						<Link href="/games">
							<ArrowLeft className="h-4 w-4 mr-2" />
							Back to Games
						</Link>
					</Button>
				</div>
			</div>
		);
	}

	if (!gameState) {
		return (
			<div className="flex items-center justify-center h-screen">
				<div className="text-center">
					<p className="text-muted-foreground mb-4">No game state available</p>
					<Button asChild variant="outline">
						<Link href="/games">
							<ArrowLeft className="h-4 w-4 mr-2" />
							Back to Games
						</Link>
					</Button>
				</div>
			</div>
		);
	}

	return (
		<div className="h-screen flex flex-col">
			{/* Header */}
			<div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="container mx-auto px-4 py-3 flex items-center justify-between">
					<div className="flex items-center gap-4">
						<Button asChild variant="ghost" size="sm">
							<Link href="/games">
								<ArrowLeft className="h-4 w-4 mr-2" />
								Back
							</Link>
						</Button>
						<h1 className="text-xl font-semibold">Game: {gameId}</h1>
						<Badge variant="secondary">Snapshot</Badge>
					</div>
					<div className="text-sm text-muted-foreground">
						Turn {gameState.turn} / {gameState.max_turns}
					</div>
				</div>
			</div>

			{/* Main Content */}
			<div className="flex-1 flex overflow-hidden">
				{/* Map Area */}
				<div className="flex-1 relative">
					<MapCanvas
						gameState={gameState}
						selectedPlayer={selectedPlayer ?? undefined}
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
								selectedPlayer={selectedPlayer ?? undefined}
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
												{gameState.map_width}x{gameState.map_height}
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
