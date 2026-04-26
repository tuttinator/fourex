/**
 * BFF proxy for `GET /api/v1/games/:id`.
 *
 * Phase 3: routed through the BFF so the Auth.js JWT (HttpOnly
 * cookie) is forwarded to FastAPI. The backend uses the JWT to
 * resolve "is this caller the lobby's creator?" against
 * ``creator_user_identity_id`` even when the caller is an all-Agent
 * owner with no per-game API key — without that, the per-slot
 * plaintext keys would never reach the lobby UI.
 *
 * Spectators (no JWT) still get a public response — the backend
 * simply omits the creator-only fields.
 */
import { NextResponse } from "next/server";

import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const jwt = await readSessionJwt();

  const headers: HeadersInit = {};
  if (jwt) {
    headers.Authorization = `Bearer ${jwt}`;
  }

  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/games/${encodeURIComponent(id)}`,
    {
      method: "GET",
      headers,
      cache: "no-store",
    },
  );

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
