/**
 * Product analytics must be INERT on the E2E stack.
 *
 * The test-profile build bakes NEXT_PUBLIC_TEST_MODE=1 and an explicitly
 * empty NEXT_PUBLIC_POSTHOG_KEY (package.json "build:test"), and
 * src/lib/analytics.ts refuses to load posthog-js under either. This journey
 * is the browser-level proof: walk the public landing page, the authed shell
 * and a client-side navigation, and assert the browser never requested the
 * /ingest proxy or any PostHog host — then check the Settings → Data opt-out
 * renders disabled, because there is nothing running to opt out of.
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

  await page.goto("/settings");
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
