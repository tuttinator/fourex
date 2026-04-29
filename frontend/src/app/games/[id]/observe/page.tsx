"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { ObservationSurface } from "@/components/observation-surface";
import { TopBar } from "@/components/top-bar";
import { useSessionEmail } from "@/components/session-email-provider";
import { signOutAction } from "@/lib/auth-actions";
import { Button } from "@/components/ui/button";
import { api, queryKeys } from "@/lib/api";

export default function ObservePage() {
  const { id: gameId } = useParams<{ id: string }>();
  const email = useSessionEmail();

  const { data: gameDetail } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
  });

  const topBarState: "live" | "ended" | "waiting" =
    gameDetail?.status === "active"
      ? "live"
      : gameDetail?.status === "ended"
        ? "ended"
        : "waiting";

  return (
    <div className="flex h-full flex-col">
      <TopBar
        email={email}
        signOutAction={signOutAction}
        game={{
          name: gameId,
          state: topBarState,
        }}
      >
        <Button asChild variant="ghost" size="sm">
          <Link href={`/games/${gameId}`}>
            <ArrowLeft className="h-4 w-4 mr-1.5" />
            Back
          </Link>
        </Button>
      </TopBar>
      <div className="flex-1 overflow-hidden">
        <ObservationSurface gameId={gameId} mode="live" />
      </div>
    </div>
  );
}
