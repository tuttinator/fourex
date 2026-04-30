/**
 * BFF proxy for `GET/PATCH/DELETE /api/v1/maps/{id}`.
 *
 * Phase 4 of the map system overhaul. Forwards the Auth.js JWT
 * (HttpOnly cookie) to FastAPI server-side. Read is open to any
 * authenticated user; mutating verbs are admin-gated upstream.
 */
import { NextResponse } from "next/server";

import { readSessionJwt } from "@/lib/server-jwt";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8010";

async function proxy(id: string, init: RequestInit) {
  const jwt = await readSessionJwt();
  if (!jwt) {
    return NextResponse.json(
      { detail: "Sign in to access maps." },
      { status: 401 },
    );
  }
  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/v1/maps/${encodeURIComponent(id)}`,
    {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${jwt}`,
        ...(init.headers ?? {}),
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

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(_request: Request, { params }: RouteParams) {
  const { id } = await params;
  return proxy(id, { method: "GET" });
}

export async function PATCH(request: Request, { params }: RouteParams) {
  const { id } = await params;
  const body = await request.text();
  return proxy(id, { method: "PATCH", body });
}

export async function DELETE(_request: Request, { params }: RouteParams) {
  const { id } = await params;
  return proxy(id, { method: "DELETE" });
}
