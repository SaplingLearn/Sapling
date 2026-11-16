/**
 * Journey #386 — seeded session → dashboard. The smallest journey in the
 * chapter-1 lane and the known-good base every other journey builds on:
 * inject the session cookie (storageState minted by global-setup) → land on
 * /dashboard → assert a known seeded course is visible. Deliberately nothing
 * else is asserted — smoke.spec.ts already owns the URL/shell proof.
 *
 * Selectors anchor on the `dashboard` testid surface (docs/frontend-testids.md,
 * minted with this journey): the "My courses" key on the default sidebar
 * layout is always open, so the spec waits for `dashboard-courses-key`, then
 * asserts the seeded course inside the
 * `dashboard-course-code` row labels. The course itself is asserted by seeded
 * DATA, not copy: `rich-course-math210` ("MATH210" — Linear Algebra,
 * db/seed_local_rich.py) is rich-user-active's spring-2026 enrollment, and
 * spring 2026 is the current term under the frozen test-mode clock
 * (2026-03-11), so its row always renders in the current — never Archive —
 * bucket of the key.
 */
import { expect, test } from "./support/fixtures";

test("seeded session lands on dashboard with a seeded course visible", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // The "My courses" key only mounts once enrollments have loaded, so waiting
  // for it doubles as the "dashboard data arrived" gate.
  await expect(page.getByTestId("dashboard-courses-key")).toBeVisible({ timeout: 30_000 });

  // One row label carries the seeded course code (course_code wins over
  // course_name in the row renderer). `dashboard-course-code` repeats per
  // course, so filter down to the seeded MATH210 row.
  await expect(
    page.getByTestId("dashboard-course-code").filter({ hasText: "MATH210" }),
  ).toBeVisible();
});
