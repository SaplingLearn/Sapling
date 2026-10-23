/**
 * Journey #430 — cookie-only session hydrates the dashboard.
 *
 * Bug: a browser holding a valid `sapling_session` cookie but no
 * `sapling_user` localStorage entry (cleared site data, another profile, a
 * stale-cookie flow) loads /dashboard, middleware admits the request on the
 * cookie alone, but `UserContext` bootstrapped identity ONLY from
 * localStorage — `userId` never got set, so Dashboard's
 * `if (userReady && userId) load()` effect never fired and the loading
 * skeleton (`loading` starts `true`) spun forever.
 *
 * Fix (frontend/src/context/UserContext.tsx): when bootstrap finds no
 * `sapling_user` in localStorage, fall back to cookie-authenticated
 * GET /api/auth/me — on 200 it hydrates the context and write-throughs
 * `setActiveUser` (so the *next* load takes the fast synchronous path); on
 * 401 it settles into the existing signed-out state instead of hanging.
 *
 * This journey mints a deliberately cookie-ONLY storageState via
 * `support/session.ts::mintStorageState(..., { omitLocalStorage: true })` —
 * every other journey keeps minting cookie + localStorage together (the
 * pre-#430 workaround, still the default) — then proves /dashboard hydrates
 * instead of spinning: the same seeded-course assertion `dashboard.spec.ts`
 * (#386) uses, which only renders once `userId` resolved and the course
 * fetch completed. A regression back to the old bootstrap-only-from-
 * localStorage behavior would leave `dashboard-courses-key-toggle` unmounted
 * forever and this test would time out on the click below.
 */
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE } from "./support/stack";

test("cookie-only session hydrates the dashboard via the /api/auth/me fallback", async ({
  browser,
}) => {
  const context = await browser.newContext({
    storageState: await mintStorageState(USER_ACTIVE, "Rich Active", {
      omitLocalStorage: true,
    }),
  });
  try {
    const page = await context.newPage();
    await page.goto("/dashboard");

    // Middleware admits the request on the cookie alone — not bounced to
    // sign-in or /pending.
    await expect(page).toHaveURL(/\/dashboard$/);

    // The "My courses" key toggle only mounts once enrollments have loaded
    // (dashboard.spec.ts's same gate) — auto-waiting on the click doubles as
    // the "dashboard data arrived, skeleton resolved" assertion. Before the
    // #430 fix this timed out: userId never resolved, so `load()` never ran
    // and the skeleton never left.
    await page.getByTestId("dashboard-courses-key-toggle").click();

    // Seeded, user-specific data rendering proves identity actually
    // resolved to rich-user-active (not just that the shell mounted):
    // rich-course-math210 ("MATH210") is this user's seeded enrollment.
    await expect(
      page.getByTestId("dashboard-course-code").filter({ hasText: "MATH210" }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});
