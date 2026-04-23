/**
 * HTTP-backed Auth.js adapter that delegates persistence to the FastAPI
 * identity router (`/api/v1/identities/*`).
 *
 * The Resend email provider needs an adapter to fulfil `createVerificationToken`,
 * `useVerificationToken`, and `getUserByEmail`. Without one Auth.js throws a
 * `MissingAdapter: Email login requires an adapter` at request time. Because
 * Parley stores user identities in the backend (alongside game data), we cross
 * the process boundary over HTTP rather than pulling a database driver into
 * the Next.js runtime.
 *
 * The `X-Identity-Service-Secret` header authenticates every call; see
 * `backend/src/api/identities.py`. Env vars are validated at adapter
 * construction so misconfiguration surfaces at boot instead of on the first
 * sign-in request.
 */

import type { Adapter, AdapterUser } from "next-auth/adapters";

type AdapterUserRow = { id: number; email: string };

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`HttpIdentityAdapter: missing required env var ${name}`);
  }
  return value;
}

export function HttpIdentityAdapter(): Adapter {
  // Env vars are read lazily — if we read them at construction time, Next.js
  // 16's Turbopack "collecting page data" step (which evaluates route modules
  // during ``next build``) crashes before any secret has been injected into
  // the build environment. Reading on first use still fails fast at runtime
  // on the first ``/api/auth/*`` request, but lets the production image
  // build without requiring the secret to be present at build time.
  const getBaseUrl = () =>
    process.env.INTERNAL_API_URL ?? "http://localhost:8010";
  const getHeaders = () =>
    ({
      "Content-Type": "application/json",
      "X-Identity-Service-Secret": requiredEnv("IDENTITY_SERVICE_SECRET"),
    }) as const;

  async function getByEmail(email: string): Promise<AdapterUserRow | null> {
    const url = new URL(`${getBaseUrl()}/api/v1/identities/by-email`);
    url.searchParams.set("email", email);
    const resp = await fetch(url, { headers: getHeaders(), method: "GET" });
    if (resp.status === 404) return null;
    if (!resp.ok) {
      throw new Error(
        `HttpIdentityAdapter.getByEmail failed: ${resp.status} ${await resp.text()}`
      );
    }
    return (await resp.json()) as AdapterUserRow;
  }

  async function getById(id: string): Promise<AdapterUserRow | null> {
    const url = new URL(`${getBaseUrl()}/api/v1/identities/by-id`);
    url.searchParams.set("id", id);
    const resp = await fetch(url, { headers: getHeaders(), method: "GET" });
    if (resp.status === 404) return null;
    if (!resp.ok) {
      throw new Error(
        `HttpIdentityAdapter.getById failed: ${resp.status} ${await resp.text()}`
      );
    }
    return (await resp.json()) as AdapterUserRow;
  }

  async function upsertByEmail(email: string): Promise<AdapterUserRow> {
    const resp = await fetch(`${getBaseUrl()}/api/v1/identities/upsert`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({ email }),
    });
    if (!resp.ok) {
      throw new Error(
        `HttpIdentityAdapter.upsert failed: ${resp.status} ${await resp.text()}`
      );
    }
    return (await resp.json()) as AdapterUserRow;
  }

  function toAdapterUser(row: AdapterUserRow): AdapterUser {
    return {
      id: String(row.id),
      email: row.email,
      emailVerified: null,
    };
  }

  return {
    async getUserByEmail(email) {
      const row = await getByEmail(email);
      return row ? toAdapterUser(row) : null;
    },

    async getUser(id) {
      const row = await getById(id);
      return row ? toAdapterUser(row) : null;
    },

    async createUser(user) {
      if (!user.email) {
        throw new Error("HttpIdentityAdapter.createUser requires an email");
      }
      const row = await upsertByEmail(user.email);
      return toAdapterUser(row);
    },

    async updateUser(user) {
      // UserIdentity stores only (id, email); we have no mutable fields to
      // persist. Re-hydrate the row so Auth.js gets a complete AdapterUser
      // back (it calls updateUser with just {id, emailVerified}).
      const row = await getById(user.id);
      if (!row) {
        throw new Error(
          `HttpIdentityAdapter.updateUser: identity ${user.id} not found`
        );
      }
      return toAdapterUser(row);
    },

    async createVerificationToken({ identifier, token, expires }) {
      const resp = await fetch(
        `${getBaseUrl()}/api/v1/identities/verification-tokens`,
        {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify({
            identifier,
            token,
            expires: expires.toISOString(),
          }),
        }
      );
      if (!resp.ok) {
        throw new Error(
          `HttpIdentityAdapter.createVerificationToken failed: ${resp.status} ${await resp.text()}`
        );
      }
      const data = (await resp.json()) as {
        identifier: string;
        token: string;
        expires: string;
      };
      return {
        identifier: data.identifier,
        token: data.token,
        expires: new Date(data.expires),
      };
    },

    async useVerificationToken({ identifier, token }) {
      const resp = await fetch(
        `${getBaseUrl()}/api/v1/identities/verification-tokens/consume`,
        {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify({ identifier, token }),
        }
      );
      if (resp.status === 404) return null;
      if (!resp.ok) {
        throw new Error(
          `HttpIdentityAdapter.useVerificationToken failed: ${resp.status} ${await resp.text()}`
        );
      }
      const data = (await resp.json()) as {
        identifier: string;
        token: string;
        expires: string;
      };
      return {
        identifier: data.identifier,
        token: data.token,
        expires: new Date(data.expires),
      };
    },
  };
}
