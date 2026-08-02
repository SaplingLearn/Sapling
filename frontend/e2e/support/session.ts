/**
 * Per-test session minting for ADDITIONAL seeded users (#394).
 *
 * global-setup mints exactly one storageState (USER_ACTIVE) that every spec
 * starts from. Multi-user journeys need a second signed-in browser context,
 * so this helper repeats the same #381 test-login flow in-process and returns
 * a Playwright `storageState` OBJECT (not a file) for
 * `browser.newContext({ storageState })`.
 *
 * Kept deliberately in lock-step with e2e/global-setup.ts:
 *   - mint through the frontend origin (proves the same-origin /api proxy);
 *   - cookie flags mirror the real `sapling_session` (HttpOnly/Lax, and
 *     secure:true — Chromium accepts Secure cookies on http://localhost);
 *   - the cookie alone WAS not a signed-in browser before #430: client
 *     identity lived only in localStorage (`UserContext` reads
 *     `sapling_user`, written only by the sign-in flows' setActiveUser) —
 *     without it authed screens rendered their shell but never fetched user
 *     data (found by the #386 journey), so the storageState carries the same
 *     origins entry global-setup writes by DEFAULT;
 *   - #430 taught UserContext to fall back to cookie-authenticated
 *     GET /api/auth/me when localStorage has no `sapling_user` entry, so
 *     `omitLocalStorage` (below) now mints a deliberately cookie-ONLY
 *     storageState to exercise that fallback (frontend/e2e/auth-session.spec.ts)
 *     — every other caller keeps the default (cookie + localStorage) exactly
 *     as before;
 *   - the token is stateless HMAC, so the per-test TRUNCATE + re-seed can
 *     never invalidate it — the re-seed restores the same rich-* user row.
 */
import { FRONTEND_URL } from "./stack";

type StorageState = {
  cookies: Array<{
    name: string;
    value: string;
    domain: string;
    path: string;
    expires: number;
    httpOnly: boolean;
    secure: boolean;
    sameSite: "Strict" | "Lax" | "None";
  }>;
  origins: Array<{
    origin: string;
    localStorage: Array<{ name: string; value: string }>;
  }>;
};

/** Mint a session for a seeded rich-* user and return it as storageState.
 * `displayName` mirrors what setActiveUser would persist after a real
 * sign-in (the user's profile name per db/seed_local_rich.py).
 *
 * `opts.omitLocalStorage` deliberately leaves out the `sapling_user`
 * localStorage entry, minting a cookie-ONLY storageState — the shape a real
 * browser has when a valid `sapling_session` cookie outlives cleared site
 * data (#430). Defaults to false so every existing caller is unaffected. */
export async function mintStorageState(
  userId: string,
  displayName: string,
  opts?: { omitLocalStorage?: boolean },
): Promise<StorageState> {
  const res = await fetch(`${FRONTEND_URL}/api/auth/test-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    throw new Error(
      `POST /api/auth/test-login failed for ${userId} (HTTP ${res.status}). ` +
        "A 404 means the backend is not running with APP_ENV=local|test — " +
        "check backend/.env and re-run `make e2e-up`.",
    );
  }
  const body = (await res.json()) as { token?: string; expires_in?: number };
  if (!body.token) {
    throw new Error(
      `test-login returned no token for ${userId}: ` +
        JSON.stringify(body).slice(0, 200),
    );
  }

  const { hostname } = new URL(FRONTEND_URL);
  return {
    cookies: [
      {
        name: "sapling_session",
        value: body.token,
        domain: hostname,
        path: "/",
        expires: Math.floor(Date.now() / 1000) + (body.expires_in ?? 3600),
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      },
    ],
    origins: opts?.omitLocalStorage
      ? []
      : [
          {
            origin: FRONTEND_URL,
            localStorage: [
              {
                name: "sapling_user",
                value: JSON.stringify({
                  id: userId,
                  name: displayName,
                  avatar: "",
                }),
              },
            ],
          },
        ],
  };
}
