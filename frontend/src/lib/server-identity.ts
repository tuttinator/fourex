/**
 * Server-side helper that fetches the authenticated caller's identity
 * (including the ``is_admin`` flag) from FastAPI's ``/api/v1/me``.
 *
 * Phase 3 of the map system overhaul gates the admin-only ``Maps`` link
 * and the ``/maps`` route on this flag. Because the JWT lives in an
 * HttpOnly cookie, only server components / route handlers can read it;
 * client components that need the flag should hit a BFF wrapper or read
 * it from a parent server component.
 */
import { readSessionJwt } from "@/lib/server-jwt";

export interface ServerIdentity {
  id: number;
  email: string | null;
  isAdmin: boolean;
}

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function fetchServerIdentity(): Promise<ServerIdentity | null> {
  const jwt = await readSessionJwt();
  if (!jwt) return null;

  const resp = await fetch(`${INTERNAL_API_URL}/api/v1/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${jwt}` },
    cache: "no-store",
  });
  if (!resp.ok) return null;
  const data = (await resp.json()) as {
    id: number;
    email: string | null;
    is_admin: boolean;
  };
  return { id: data.id, email: data.email, isAdmin: data.is_admin };
}
