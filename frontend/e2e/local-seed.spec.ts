/**
 * Journey #715 — a NEW Google account on a local stack gets the sample data.
 *
 * On a developer's local backend (APP_ENV local|test + loopback Supabase —
 * which the E2E stack is), services/local_seed_watcher.py copies the rich
 * sample dataset onto every live `user_<google id>` account that has not
 * onboarded yet, and the seed completes onboarding as its last write. The
 * post-sign-in routing (lib/localSeed.ts) asks GET /api/auth/local-seed and
 * sends a seeding account to the /setting-up hold screen instead of an empty
 * /onboarding; the hold screen polls until `ready`, then the dashboard.
 *
 * Real Google OAuth cannot be driven headlessly, so the journey starts where
 * the OAuth redirect would leave a first sign-in: a fresh users row
 * (support/db.ts::insertGoogleAccount) and a session token minted through
 * test-login, handed to the same-tab /auth/callback as `auth_token`.
 *
 * Timing-robust by design: the watcher idles on a 30s poll but every
 * `pending` status answer nudges it awake, so it can finish the seed before
 * the callback even asks (then the callback goes straight to /dashboard) or
 * after (then the hold screen shows first). Either path passes; what must
 * hold is that it ends on the dashboard with the data in the database, and
 * never detours through an empty /onboarding.
 *
 * Other journeys are unaffected: every seeded fixture account is `rich-*`,
 * never `user_*`, so the watcher has nothing else to seed. The per-test
 * reset truncates `users`, which removes this account and everything the
 * seed hung off it before the next test. The test ends only once the seed
 * has completed (onboarding_completed is its last write), so no seed is
 * still writing when that reset runs.
 */
import { randomUUID } from "node:crypto";

import { expect, test } from "./support/fixtures";
import { insertGoogleAccount, queryRaw } from "./support/db";
import { mintSessionToken } from "./support/session";
import { FRONTEND_URL } from "./support/stack";

test("a new local Google account is seeded with the sample data and lands on the dashboard (#715)", async ({
  browser,
}) => {
  // The seed is a few hundred PostgREST round trips; give it room.
  test.setTimeout(120_000);

  const googleId = `e2e${randomUUID().replace(/-/g, "")}`;
  const userId = `user_${googleId}`;
  await insertGoogleAccount(userId, googleId);
  const { token } = await mintSessionToken(userId);

  // A clean browser: not the USER_ACTIVE storageState every spec starts from.
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  const visited: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) visited.push(new URL(frame.url()).pathname);
  });

  try {
    const callback = new URL("/auth/callback", FRONTEND_URL);
    callback.searchParams.set("user_id", userId);
    callback.searchParams.set("is_approved", "true");
    callback.searchParams.set("auth_token", token);
    await page.goto(callback.toString());

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 90_000 });
    await expect(page.getByTestId("app-shell")).toBeVisible();

    expect(
      visited.filter((path) => path.startsWith("/onboarding")),
      "a seeding local account must wait on /setting-up, never an empty /onboarding",
    ).toEqual([]);

    const [user] = await queryRaw(
      "SELECT onboarding_completed FROM users WHERE id = $1",
      [userId],
    );
    expect(user?.onboarding_completed, "the seed completes onboarding last").toBe(true);

    const [counts] = await queryRaw(
      `SELECT
         (SELECT count(*)::int FROM enrollments WHERE user_id = $1) AS enrollments,
         (SELECT count(*)::int FROM graph_nodes WHERE user_id = $1) AS graph_nodes,
         (SELECT count(*)::int FROM documents WHERE user_id = $1) AS documents,
         (SELECT count(*)::int FROM feedback WHERE user_id = $1) AS feedback,
         (SELECT count(*)::int FROM issue_reports WHERE user_id = $1) AS issue_reports,
         (SELECT count(*)::int FROM user_roles WHERE user_id = $1) AS user_roles`,
      [userId],
    );
    // The owner seed's copy of db/seed_local_rich.py's USER_ACTIVE dataset
    // (backend/tests/test_seed_local_rich.py pins the same numbers).
    expect(counts).toEqual({
      enrollments: 5,
      graph_nodes: 13,
      documents: 3,
      // Never copied onto a real account: sample submissions and admin rights.
      feedback: 0,
      issue_reports: 0,
      user_roles: 0,
    });
  } finally {
    await context.close();
  }
});
