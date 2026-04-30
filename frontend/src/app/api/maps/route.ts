/**
 * BFF proxy for `GET/POST /api/v1/maps`.
 *
 * Phase 4 of the map system overhaul. Forwards the Auth.js JWT
 * (HttpOnly cookie) to FastAPI server-side. Listing is available
 * to any authenticated user (the lobby drop-down depends on it);
 * creation is gated on `is_admin` upstream.
 */
import { NextResponse } from "next/server";

import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

async function proxy(request: Request, init?: RequestInit) {
  const jwt = await readSessionJwt();
  if (!jwt) {
    return NextResponse.json(
      { detail: "Sign in to access maps." },
      { status: 401 },
    );
  }
  const upstream = await fetch(`${INTERNAL_API_URL}/api/v1/maps`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(request: Request) {
  return proxy(request, { method: "GET" });
}

export async function POST(request: Request) {
  const body = await request.text();
  return proxy(request, { method: "POST", body });
}
