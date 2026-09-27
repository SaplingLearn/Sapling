/**
 * Product analytics must be INERT on the E2E stack.
 *
 * The test-profile build bakes NEXT_PUBLIC_TEST_MODE=1 and an explicitly
 * empty NEXT_PUBLIC_POSTHOG_KEY (package.json "build:test"), and
 * src/lib/analytics.ts refuses to load posthog-js under either (in an
 * analytics build it would still load only for a signed-in student whose
 * account says `analytics_opt_out: false`). This journey
 * is the browser-level proof: walk the public landing page, the authed shell
 * and a REAL client-side navigation (a click on the shell's own nav link —
 * the `history_change` path posthog-js would capture a pageview on), and
 * assert the browser never requested the /ingest proxy or any PostHog host —
 * then check the Settings → Data opt-out renders disabled, because there is
 * nothing running to opt out of.
 */
import type { Request } from "@playwright/test";

import { expect, test } from "./support/fixtures";

function isAnalyticsRequest(req: Request): boolean {
  const url = new URL(req.url());
  return url.pathname.startsWith("/ingest") || /(^|\.)posthog\.com$/.test(url.hostname);
}

test("the E2E build sends no analytics and shows the opt-out as inactive", async ({ page }) => {
  const analytics: string[] = [];
  page.on("request", (req) => {
    if (isAnalyticsRequest(req)) analytics.push(`${req.method()} ${req.url()}`);
  });

  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.goto("/dashboard");
  await expect(page.getByTestId("app-shell")).toBeVisible();

  // Client-side navigation inside the shell: a marker on `window` survives a
  // soft (history) navigation and would be wiped by a full page load.
  await page.evaluate(() => {
    (window as unknown as { __softNav?: boolean }).__softNav = true;
  });
  await page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Settings", exact: true })
    .click();
  await expect(page).toHaveURL(/\/settings$/);
  expect(await page.evaluate(() => (window as unknown as { __softNav?: boolean }).__softNav)).toBe(true);

  await page.getByTestId("settings-tab-data").click();
  const toggle = page.getByTestId("settings-analytics-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).toBeDisabled();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("settings-analytics-note")).toContainText("isn't running");
  await page.waitForLoadState("networkidle");

  // posthog-js is a lazy chunk behind the gate: it must never even load.
  expect(await page.evaluate(() => "posthog" in window || "__PosthogExtensions__" in window)).toBe(false);
  expect(analytics).toEqual([]);
});

/**
 * `skipTrailingSlashRedirect` (next.config.ts) turns Next's own slash redirect
 * off so PostHog's `/ingest/e/`-style endpoints reach the proxy; the
 * `redirects()` stand-in must keep normalising everything else, `/api/*`
 * included. And the proxy must refuse encoded traversal outright.
 */
test("trailing slashes still 308 everywhere except /ingest, which refuses traversal", async ({ page }) => {
  for (const [from, to] of [
    ["/settings/", "/settings"],
    ["/news/some-post/", "/news/some-post"],
    ["/api/auth/me/", "/api/auth/me"],
    // Encoded slugs keep their encoding (no %20 → %2520 double-encoding).
    ["/notes/a%20b/", "/notes/a%20b"],
    ["/news/caf%C3%A9/", "/news/caf%C3%A9"],
  ] as const) {
    const res = await page.request.get(from, { maxRedirects: 0 });
    expect(res.status(), from).toBe(308);
    expect(new URL(res.headers()["location"], "http://x").pathname, from).toBe(to);
  }
  const traversal = await page.request.get("/ingest/static/..%2fflags/", { maxRedirects: 0 });
  expect(traversal.status()).toBe(404);
  // Not an open relay: the flags endpoint this SDK config never uses is refused.
  expect((await page.request.post("/ingest/flags/?v=2", { data: "{}", maxRedirects: 0 })).status()).toBe(404);
});
