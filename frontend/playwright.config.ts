/**
 * Playwright harness for the browser E2E lane (#385).
 *
 * Lives in frontend/ (not the repo root) because Playwright is a frontend
 * devDependency: `npx playwright test` run from frontend/ resolves the local
 * binary, node_modules, and TS setup without any root-level tooling. Specs
 * live in frontend/e2e/ per the issue layout.
 *
 * The config points at an ALREADY-BOOTED stack — `make e2e-up` (#384) owns
 * the boot contract (Supabase :54321/:54322 → migrate → seed → uvicorn :5000
 * → test-profile Next build on :3000). There is deliberately no `webServer`
 * block: booting servers here would duplicate (and drift from) #384's
 * scripts. global-setup health-checks the stack instead and fails with the
 * exact fix ("run `make e2e-up`") when it is down.
 *
 * Determinism: the test-profile build bakes NEXT_PUBLIC_TEST_MODE=1 (#383) —
 * seeded PRNG, frozen clock at 2026-03-11T12:00:00Z. Local-time-rendered copy
 * (the dashboard greeting, calendar "today") depends on the browser timezone,
 * so `timezoneId` is pinned below (America/New_York — BU context): frozen
 * noon UTC renders as 8:00 AM Eastern ("Good morning").
 */
import { defineConfig, devices } from "@playwright/test";

import { FRONTEND_URL } from "./e2e/support/stack";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,

  // Serial to start (#385): parallelism is a later optimization, and the
  // per-test TRUNCATE + re-seed isolation (support/db.ts) assumes a single
  // writer against the one local database.
  fullyParallel: false,
  workers: 1,

  // Retries in CI only. The JSON report (below) records every retry per test
  // in machine-readable form — the feed for #390 flake tracking.
  retries: process.env.CI ? 2 : 0,
  forbidOnly: !!process.env.CI,

  reporter: [
    ["list"],
    ["json", { outputFile: "e2e/results/last-run.json" }],
  ],

  globalSetup: "./e2e/global-setup.ts",

  use: {
    baseURL: FRONTEND_URL,
    // The authed session minted by global-setup via POST /api/auth/test-login
    // (#381). Specs import the fixture-extended `test` from
    // e2e/support/fixtures.ts, which layers per-test DB isolation on top.
    storageState: "e2e/.auth/storageState.json",
    // Debuggability on failure only — keeps green runs fast and artifact-free.
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    // Pin the timezone so the frozen test-mode clock renders identical local
    // times everywhere (see header). Locale pinned for the same reason.
    timezoneId: "America/New_York",
    locale: "en-US",
  },

  projects: [
    // Chromium only for now (#385) — install via `npx playwright install chromium`.
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
