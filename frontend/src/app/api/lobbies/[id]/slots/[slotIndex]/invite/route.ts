/**
 * BFF proxy for `POST /api/v1/games/:id/slots/:slot_index/invite`.
 *
 * Phase 5: (re)send a Resend-delivered invite for a Human slot
 * reservation. Forwards the Auth.js JWT so the backend's
 * ``require_creator_auth`` dependency recognises the caller as the
 * lobby's creator (seated or all-Agent owner).
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; slotIndex: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { detail: "Sign in to send an invite." },
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

  const { id, slotIndex } = await params;
  const slotIndexNumber = Number.parseInt(slotIndex, 10);
  if (!Number.isFinite(slotIndexNumber)) {
    return NextResponse.json(
      { detail: "slot_index must be an integer" },
      { status: 400 },
    );
  }

  const body = await request.text();

  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/games/${encodeURIComponent(id)}/slots/${slotIndexNumber}/invite`,
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
