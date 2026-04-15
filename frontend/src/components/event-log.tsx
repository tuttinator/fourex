"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function EventLog() {
	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-3">
				<CardTitle className="text-sm">Event Log</CardTitle>
			</CardHeader>
			<CardContent className="flex-1">
				<div className="text-center text-muted-foreground py-8">
					<p className="text-sm">No events available</p>
					<p className="text-xs mt-2">
						Event streaming will be available in a future update
					</p>
				</div>
			</CardContent>
		</Card>
	);
}
