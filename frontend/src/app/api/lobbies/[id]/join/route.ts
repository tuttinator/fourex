/**
 * BFF proxy for `POST /api/v1/games/:id/join`.
 *
 * See `../route.ts` for the reasoning — same JWT-forwarding pattern.
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { detail: "Sign in to join a lobby." },
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
    `${INTERNAL_API_URL}/api/v1/games/${encodeURIComponent(id)}/join`,
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
