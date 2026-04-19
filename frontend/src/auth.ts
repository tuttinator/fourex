/**
 * Auth.js (NextAuth v5) configuration for Parley.
 *
 * Magic-link sign-in via the Resend provider, JWT session strategy, and an
 * HS256 JWS encoding override so the FastAPI side (`backend/src/identity.py`)
 * can verify tokens with PyJWT. Auth.js defaults to A256CBC-HS512 JWE, which
 * PyJWT cannot read without pulling in jwcrypto — the override keeps the
 * backend dependency surface minimal.
 *
 * Persistence for users and magic-link verification tokens is delegated to
 * `HttpIdentityAdapter`, which calls the FastAPI identity router. The adapter
 * returns `UserIdentity.id` as the canonical user id, which the `jwt`
 * callback pins as the JWT `sub` claim that `verify_auth_jwt` expects.
 *
 * Environment variables:
 *   AUTH_SECRET              — shared HS256 secret (FastAPI also reads it).
 *   AUTH_RESEND_KEY          — Resend API key. Auth.js auto-picks this up for
 *                              the Resend provider.
 *   AUTH_EMAIL_FROM          — verified sender on parley.quest (e.g.
 *                              `hello@parley.quest`).
 *   INTERNAL_API_URL         — FastAPI base URL for server-to-server calls
 *                              (defaults to `http://localhost:8010`).
 *   IDENTITY_SERVICE_SECRET  — shared secret for the identity endpoints.
 */

import NextAuth from "next-auth";
import Resend from "next-auth/providers/resend";
import { SignJWT, jwtVerify } from "jose";

import { HttpIdentityAdapter } from "./auth-adapter";

const HS256_ALG = "HS256";
const DEFAULT_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var ${name}`);
  }
  return value;
}

function secretBytes(): Uint8Array {
  return new TextEncoder().encode(requireEnv("AUTH_SECRET"));
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: HttpIdentityAdapter(),
  providers: [
    Resend({
      from: process.env.AUTH_EMAIL_FROM ?? "onboarding@resend.dev",
    }),
  ],
  pages: {
    signIn: "/signin",
    verifyRequest: "/signin/check-email",
    error: "/signin",
  },
  session: {
    strategy: "jwt",
    maxAge: DEFAULT_MAX_AGE_SECONDS,
  },
  jwt: {
    // Override the default JWE encoding with HS256 JWS so the FastAPI
    // verifier can read tokens with PyJWT.
    async encode({ token, maxAge }): Promise<string> {
      const payload = token ?? {};
      const now = Math.floor(Date.now() / 1000);
      const expSeconds = maxAge ?? DEFAULT_MAX_AGE_SECONDS;
      return await new SignJWT(payload as Record<string, unknown>)
        .setProtectedHeader({ alg: HS256_ALG })
        .setIssuedAt(now)
        .setExpirationTime(now + expSeconds)
        .sign(secretBytes());
    },
    async decode({ token }) {
      if (!token) return null;
      try {
        const { payload } = await jwtVerify(token, secretBytes(), {
          algorithms: [HS256_ALG],
        });
        return payload as Record<string, unknown> as import("next-auth/jwt").JWT;
      } catch {
        return null;
      }
    },
  },
  callbacks: {
    async jwt({ token, user }) {
      // On first sign-in the adapter has already resolved UserIdentity.id as
      // `user.id`. Pin it as `sub` so `verify_auth_jwt` can key off it.
      if (user?.id) {
        token.sub = user.id;
      }
      if (user?.email) {
        token.email = user.email;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub && session.user) {
        session.user.id = token.sub;
      }
      if (token.email && session.user) {
        session.user.email = token.email as string;
      }
      return session;
    },
  },
});

declare module "next-auth" {
  interface Session {
    user: {
      id?: string;
      email?: string | null;
      name?: string | null;
      image?: string | null;
    };
  }
}
