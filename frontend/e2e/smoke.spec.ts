/**
 * Harness smoke proof (#385) — deliberately NOT a user journey (those are
 * #386–#395). One spec proving the foundation end-to-end:
 *
 *   stack up (#384) → storageState session minted via test-login (#381) →
 *   per-test truncate + re-seed baseline (support/db.ts) → an authed,
 *   middleware-gated shell route renders its known data-testid (#382).
 *
 * /dashboard is middleware-protected: without a valid session cookie the
 * middleware redirects to `${BACKEND_URL}/api/auth/google` (BACKEND_URL is
 * always set under start:test), i.e. clean off :3000 into the OAuth flow —
 * so `app-shell` becoming visible at /dashboard proves the session, the
 * approval gate (the seeded rich-user-active is approved), and the
 * Next → FastAPI proxy in one go.
 */
import { expect, test } from "./support/fixtures";

test("authed dashboard shell renders from storageState session", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // Not bounced by the auth middleware (unauthed → the backend's
  // /api/auth/google; unapproved → /pending).
  await expect(page).toHaveURL(/\/dashboard$/);

  // The authed app shell mounted (data-testid per the #382 convention).
  await expect(page.getByTestId("app-shell")).toBeVisible();
});
