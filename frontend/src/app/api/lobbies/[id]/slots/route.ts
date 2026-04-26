/**
 * BFF proxy for `PUT /api/v1/games/:id/slots`.
 *
 * Phase 4: routed through the BFF so the Auth.js JWT (HttpOnly
 * cookie) reaches FastAPI. The upstream `require_creator_auth`
 * accepts the JWT for all-Agent owners as well as the per-game key
 * the seated creator already has — the BFF only forwards the JWT
 * here because the page-level mutation always has it available;
 * a seated creator running through this BFF still authorises via
 * the JWT path on the backend.
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { detail: "Sign in to reconfigure slots." },
      { status: 401 },
    );
  }

  const jwt = await readSessionJwt();
  if (!jwt) {
    return NextResponse.json(
      { detail: "Session token missing. Sign in again." },
      { status: 401 },
    );
  }

  const { id } = await params;
  const body = await request.text();

  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/games/${encodeURIComponent(id)}/slots`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
      },
      body,
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
