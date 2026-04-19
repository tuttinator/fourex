/**
 * Server-side helper for forwarding the Auth.js JWT to FastAPI.
 *
 * Phase 2 routes `POST /games` and `POST /games/:id/join` through
 * `require_user_identity`, which expects the Auth.js-signed JWT on
 * `Authorization: Bearer`. The JWT is persisted in an HttpOnly cookie by
 * Auth.js, so we can't read it from the browser — instead, the browser hits
 * a Next.js BFF route which reads the cookie with `cookies()` and proxies
 * to FastAPI with the token attached.
 *
 * Because `auth.ts` installs a custom HS256 `jwt.encode`, the cookie value
 * IS the JWT we want; no further encoding is needed.
 */
import { cookies } from "next/headers";

const COOKIE_NAMES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
];

export async function readSessionJwt(): Promise<string | null> {
  const store = await cookies();
  for (const name of COOKIE_NAMES) {
    const c = store.get(name);
    if (c?.value) return c.value;
  }
  return null;
}
