/**
 * Admin-only ``/maps`` list view.
 *
 * Phase 4 of the map system overhaul: server-rendered list of every
 * saved map with name, dimensions, spawn-zone count, and author
 * email. The full editor lands in Phase 5; for now non-admins are
 * redirected and admins see a read-only table.
 */
import { redirect } from "next/navigation";

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

function formatDate(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
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
        <p className="text-xs text-ink-muted">
          Saved-map authoring (full editor) lands in a follow-up phase.
        </p>
      </div>

      {maps.length === 0 ? (
        <p className="mt-6 text-sm text-ink-muted" data-testid="maps-empty">
          No saved maps yet. The editor in Phase 5 will let you paint and
          save the first one.
        </p>
      ) : (
        <table
          className="mt-6 w-full text-sm"
          data-testid="maps-list"
        >
          <thead>
            <tr className="border-b text-left text-xs uppercase text-ink-muted">
              <th className="py-2 pr-4">Name</th>
              <th className="py-2 pr-4">Dimensions</th>
              <th className="py-2 pr-4">Spawn zones</th>
              <th className="py-2 pr-4">Author</th>
              <th className="py-2 pr-4">Updated</th>
            </tr>
          </thead>
          <tbody>
            {maps.map((m) => (
              <tr key={m.id} className="border-b">
                <td className="py-2 pr-4 font-medium text-ink">{m.name}</td>
                <td className="py-2 pr-4 text-ink-muted">
                  {m.width} × {m.height}
                </td>
                <td className="py-2 pr-4 text-ink-muted">
                  {m.spawn_zone_count}
                </td>
                <td className="py-2 pr-4 text-ink-muted">
                  {m.creator_email ?? "—"}
                </td>
                <td className="py-2 pr-4 text-ink-muted">
                  {formatDate(m.updated_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
