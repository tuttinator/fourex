/**
 * BFF proxy for `POST /api/v1/games`.
 *
 * The upstream endpoint is guarded by the Auth.js JWT verifier
 * (`require_user_identity`). Auth.js stores the JWT in an HttpOnly
 * cookie so the browser can't read it directly; this route reads the
 * cookie server-side and forwards it as `Authorization: Bearer`.
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { detail: "Sign in to create a lobby." },
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

  const url = new URL(request.url);
  const gameId = url.searchParams.get("game_id");
  if (!gameId) {
    return NextResponse.json({ detail: "game_id required" }, { status: 400 });
  }

  const body = await request.text();

  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/games?game_id=${encodeURIComponent(gameId)}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${jwt}`,
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
