/**
 * Boot Auth.js end-to-end and verify the handler doesn't throw
 * `MissingAdapter` or any other config error.
 *
 * This is the smoke test that would have caught 55d736c — vitest/eslint/tsc
 * never exercise the Auth.js request pipeline, so a missing adapter only
 * surfaced when `next dev` actually served a request.
 */

import type { NextRequest } from "next/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

process.env.AUTH_SECRET ??= "test-auth-secret-at-least-32-chars-long";
process.env.AUTH_RESEND_KEY ??= "test-resend-key";
process.env.AUTH_EMAIL_FROM ??= "test@example.com";
process.env.IDENTITY_SERVICE_SECRET ??= "test-identity-service-secret";
process.env.INTERNAL_API_URL ??= "http://localhost:8010";

// The adapter hits FastAPI over the network — mock fetch so the test is
// hermetic. The handler's `/providers` route doesn't call the adapter, but
// any adapter-touching flow should still surface config errors via this
// mock.
const fetchMock = vi.fn(async () => {
  return new Response(JSON.stringify({ id: 1, email: "x@example.com" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});

beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  fetchMock.mockClear();
});

describe("Auth.js handler boot", () => {
  it("serves /api/auth/providers without MissingAdapter", async () => {
    const { handlers } = await import("@/auth");
    const req = new Request(
      "http://localhost:3000/api/auth/providers"
    ) as unknown as NextRequest;
    const res = await handlers.GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("resend");
  });

  it("serves /api/auth/signin without a 500", async () => {
    const { handlers } = await import("@/auth");
    const req = new Request(
      "http://localhost:3000/api/auth/signin"
    ) as unknown as NextRequest;
    const res = await handlers.GET(req);
    // Auth.js may redirect to our custom /signin page; anything non-5xx is
    // proof the config passed `assertConfig`.
    expect(res.status).toBeLessThan(500);
  });
});
