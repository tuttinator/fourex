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
import { Tag } from "@/components/ui/tag";
import { api, queryKeys } from "@/lib/api";

export default function ReplayPage() {
  const { id: gameId } = useParams<{ id: string }>();
  const email = useSessionEmail();

  const { data: gameDetail } = useQuery({
    queryKey: queryKeys.gameDetail(gameId),
    queryFn: () => api.getGameDetail(gameId),
  });

  return (
    <div className="flex h-screen flex-col">
      <TopBar
        email={email}
        signOutAction={signOutAction}
        game={{
          name: gameId,
          state: "replay",
        }}
      >
        <Button asChild variant="ghost" size="sm">
          <Link href={`/games/${gameId}`}>
            <ArrowLeft className="h-4 w-4 mr-1.5" />
            Back
          </Link>
        </Button>
        {gameDetail?.status === "ended" && gameDetail.winner && (
          <Tag tone="success" mono>
            winner · {gameDetail.winner}
          </Tag>
        )}
      </TopBar>
      <div className="flex-1 overflow-hidden">
        <ObservationSurface gameId={gameId} mode="replay" />
      </div>
    </div>
  );
}
