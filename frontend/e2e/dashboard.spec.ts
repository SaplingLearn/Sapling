/**
 * Journey #386 — seeded session → dashboard. The smallest journey in the
 * chapter-1 lane and the known-good base every other journey builds on:
 * inject the session cookie (storageState minted by global-setup) → land on
 * /dashboard → assert a known seeded course is visible. Deliberately nothing
 * else is asserted — smoke.spec.ts already owns the URL/shell proof.
 *
 * The course: `rich-course-math210` (MATH210 — "Linear Algebra") from
 * db/seed_local_rich.py, which rich-user-active takes via the spring-2026
 * offering. Spring 2026 is the current term under the frozen test-mode clock
 * (2026-03-11), so the enrollment always sits in the current (not Archive)
 * bucket of the "My courses" key on the default sidebar dashboard layout.
 * The key starts collapsed; its toggle is reached by accessible name and the
 * course by seeded text — the dashboard is not a #382 testid surface, and
 * per the issue a seeded-data text/role assertion is preferred over minting
 * one for it.
 */
import { expect, test } from "./support/fixtures";

test("seeded session lands on dashboard with a seeded course visible", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // Expand the "My courses" key overlay (collapsed by default). The button
  // only mounts once enrollments have loaded, so Playwright's auto-wait on
  // the click doubles as the "dashboard data arrived" gate.
  await page.getByRole("button", { name: "Expand courses key" }).click();

  // The row label renders the seeded course_code (course_code wins over
  // course_name throughout the dashboard). Exact match keeps the locator
  // unique: the "Where you left off" panel mentions MATH210 too, but only
  // inside a longer "MATH210 · expository · …" string.
  await expect(page.getByText("MATH210", { exact: true })).toBeVisible();
});
