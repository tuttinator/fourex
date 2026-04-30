/**
 * Phase 5 (map system overhaul): admin-only edit-existing-map page.
 *
 * Server-rendered guard + server-side fetch of the saved map via the
 * same JWT path the rest of the /maps surface uses. The full payload
 * (tiles + spawn zones) is hydrated into the client editor as its
 * `initial` prop.
 */
import { notFound, redirect } from "next/navigation";

import { MapEditor } from "@/components/map-editor";
import { readSessionJwt } from "@/lib/server-jwt";
import { fetchServerIdentity } from "@/lib/server-identity";
import type { SavedMap } from "@/types/game";

export const dynamic = "force-dynamic";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

async function fetchSavedMapServerSide(id: number): Promise<SavedMap | null> {
  const jwt = await readSessionJwt();
  if (!jwt) return null;
  const response = await fetch(`${INTERNAL_API_URL}/api/v1/maps/${id}`, {
    headers: { Authorization: `Bearer ${jwt}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as SavedMap;
}

interface RouteParams {
  params: Promise<{ id: string }>;
}

export default async function EditMapPage({ params }: RouteParams) {
  const identity = await fetchServerIdentity();
  if (!identity?.isAdmin) {
    redirect("/");
  }
  const { id } = await params;
  const numericId = Number.parseInt(id, 10);
  if (!Number.isFinite(numericId)) {
    notFound();
  }
  const map = await fetchSavedMapServerSide(numericId);
  if (!map) {
    notFound();
  }
  return <MapEditor initial={map} />;
}
