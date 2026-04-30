/**
 * Phase 5 (map system overhaul): admin-only blank-canvas editor.
 *
 * Server-rendered guard via fetchServerIdentity; non-admins are
 * redirected to /. The editor itself is a client component because it
 * owns canvas state + pointer handling.
 */
import { redirect } from "next/navigation";

import { MapEditor } from "@/components/map-editor";
import { fetchServerIdentity } from "@/lib/server-identity";

export const dynamic = "force-dynamic";

export default async function NewMapPage() {
  const identity = await fetchServerIdentity();
  if (!identity?.isAdmin) {
    redirect("/");
  }
  return <MapEditor />;
}
