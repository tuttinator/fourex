"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ObservationView } from "@/components/observation-view";
import { Button } from "@/components/ui/button";

export default function ObservePage() {
	const { id: gameId } = useParams<{ id: string }>();

	return (
		<div className="h-full flex flex-col">
			{/* Header */}
			<div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="container mx-auto px-4 py-3 flex items-center gap-4">
					<Button asChild variant="ghost" size="sm">
						<Link href={`/games/${gameId}`}>
							<ArrowLeft className="h-4 w-4 mr-2" />
							Back
						</Link>
					</Button>
					<h1 className="text-xl font-semibold">Game: {gameId}</h1>
				</div>
			</div>

			{/* Observation view fills remaining space */}
			<div className="flex-1 overflow-hidden">
				<ObservationView gameId={gameId} />
			</div>
		</div>
	);
}
