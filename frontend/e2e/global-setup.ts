/**
 * Playwright global setup (#385): verify the #384 stack is up, mint an
 * authed session for the primary seeded user via the #381 test-auth seam,
 * and persist it as Playwright `storageState` so every spec starts signed in.
 *
 * POST /api/auth/test-login exists only when the backend runs with
 * `APP_ENV in {local, test}` (it 404s everywhere else) and performs no
 * credential check — the seeded `rich-*` ids are just named directly. It
 * returns the token in the JSON body precisely so a harness can inject it
 * as a cookie instead of replaying the Set-Cookie response.
 *
 * The session token is stateless HMAC (services/session_tokens.py) — no DB
 * row backs it — so the per-test TRUNCATE + re-seed cannot invalidate it:
 * the re-seed restores the same `rich-user-active` the token names.
 */
import fs from "node:fs";
import path from "node:path";

import { FRONTEND_URL, USER_ACTIVE, requireStackUp } from "./support/stack";

export const STORAGE_STATE = path.join(__dirname, ".auth", "storageState.json");

export default async function globalSetup(): Promise<void> {
  await requireStackUp();

  // Mint through the frontend origin: the /api/:path* rewrite proxies to the
  // backend, so this also proves the same-origin path the app itself uses.
  const res = await fetch(`${FRONTEND_URL}/api/auth/test-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ACTIVE }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    throw new Error(
      `POST /api/auth/test-login failed (HTTP ${res.status}). A 404 means the ` +
        "backend is not running with APP_ENV=local|test — check backend/.env " +
        "and re-run `make e2e-up`.",
    );
  }
  const body = (await res.json()) as { token?: string; expires_in?: number };
  if (!body.token) {
    throw new Error(
      `test-login returned no token: ${JSON.stringify(body).slice(0, 200)}`,
    );
  }

  // Flags: the real cookie is HttpOnly/Lax with Secure only when the backend's
  // SECURE_COOKIES is on (config.py derives it from FRONTEND_URL's scheme, so
  // it is False under the http:// local stack). We set secure:true anyway —
  // matching what an https deploy would mint — and Chromium accepts and sends
  // Secure cookies on http://localhost (a trustworthy origin;
  // docs/local-supabase.md relies on the same behavior).
  const { hostname } = new URL(FRONTEND_URL);
  const storageState = {
    cookies: [
      {
        name: "sapling_session",
        value: body.token,
        domain: hostname,
        path: "/",
        expires: Math.floor(Date.now() / 1000) + (body.expires_in ?? 3600),
        httpOnly: true,
        secure: true,
        sameSite: "Lax" as const,
      },
    ],
    // The cookie alone is not a signed-in browser: the client identity lives
    // in localStorage (`UserContext` reads `sapling_user`; only the sign-in
    // flows write it via setActiveUser). Without it every authed screen
    // renders its shell but never fetches user data — the #386 journey found
    // /dashboard stuck on its skeleton forever. Mirror exactly what
    // setActiveUser persists for the primary seeded user (name per
    // db/seed_local_rich.py).
    origins: [
      {
        origin: FRONTEND_URL,
        localStorage: [
          {
            name: "sapling_user",
            value: JSON.stringify({
              id: USER_ACTIVE,
              name: "Rich Active",
              avatar: "",
            }),
          },
        ],
      },
    ],
  };

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  fs.writeFileSync(STORAGE_STATE, JSON.stringify(storageState, null, 2));
}
