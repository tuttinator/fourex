/**
 * Admin-only ``/maps`` placeholder page.
 *
 * Phase 3 of the map system overhaul: this page is the destination for
 * the navbar's ``Maps`` link. Phase 4 wires in the saved-map list view
 * and Phase 5 fills in the editor; for now the route exists primarily
 * to verify the admin route guard end-to-end.
 *
 * Server component so the ``is_admin`` check happens before any HTML is
 * sent to the browser. Non-admin (and signed-out) viewers are redirected
 * to ``/``.
 */
import { redirect } from "next/navigation";

import { fetchServerIdentity } from "@/lib/server-identity";

export const dynamic = "force-dynamic";

export default async function MapsPage() {
  const identity = await fetchServerIdentity();
  if (!identity?.isAdmin) {
    redirect("/");
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="font-display text-2xl text-ink">Maps</h1>
      <p className="mt-2 text-sm text-ink-muted">
        Saved-map authoring lands in a follow-up phase. This page is reachable
        only by admins; the list view and editor will appear here once they
        ship.
      </p>
    </div>
  );
}
