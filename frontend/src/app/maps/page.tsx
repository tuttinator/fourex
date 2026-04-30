/**
 * Admin-only ``/maps`` list view.
 *
 * Phase 4 of the map system overhaul shipped this as a read-only table.
 * Phase 5 grows it: a "New map" affordance to enter the editor, and per
 * row Edit/Delete actions wired through the BFF. Server-side admin
 * guard remains so non-admins can't reach the page even by URL.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { MapsListClient } from "@/components/maps-list-client";
import { Button } from "@/components/ui/button";
import { fetchServerIdentity } from "@/lib/server-identity";
import { readSessionJwt } from "@/lib/server-jwt";
import type { SavedMapSummary } from "@/types/game";

export const dynamic = "force-dynamic";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

async function fetchSavedMapsServerSide(): Promise<SavedMapSummary[]> {
  const jwt = await readSessionJwt();
  if (!jwt) return [];
  const response = await fetch(`${INTERNAL_API_URL}/api/v1/maps`, {
    headers: { Authorization: `Bearer ${jwt}` },
    cache: "no-store",
  });
  if (!response.ok) return [];
  return (await response.json()) as SavedMapSummary[];
}

export default async function MapsPage() {
  const identity = await fetchServerIdentity();
  if (!identity?.isAdmin) {
    redirect("/");
  }

  const maps = await fetchSavedMapsServerSide();

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-2xl text-ink">Maps</h1>
        {maps.length > 0 ? (
          <Button asChild>
            <Link href="/maps/new" data-testid="maps-new-link">
              New map
            </Link>
          </Button>
        ) : null}
      </div>

      <MapsListClient maps={maps} />
    </div>
  );
}
