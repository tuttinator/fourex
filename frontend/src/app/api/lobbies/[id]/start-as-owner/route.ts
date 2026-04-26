/**
 * BFF proxy for `POST /api/v1/games/:id/start-as-owner`.
 *
 * Phase 3: lets the (unseated) creator of an all-Agent game start
 * the lobby. The owner has no per-game API key, so the BFF forwards
 * the Auth.js JWT — the upstream `require_creator_auth` accepts that
 * via the `creator_user_identity_id` column.
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { detail: "Sign in to start a lobby." },
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

  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/games/${encodeURIComponent(id)}/start-as-owner`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
      },
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
