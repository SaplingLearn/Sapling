/**
 * Journey #386 — seeded session → dashboard. The smallest journey in the
 * chapter-1 lane and the known-good base every other journey builds on:
 * inject the session cookie (storageState minted by global-setup) → land on
 * /dashboard → assert a known seeded course is visible. Deliberately nothing
 * else is asserted — smoke.spec.ts already owns the URL/shell proof.
 *
 * Selectors anchor on the `dashboard` testid surface (docs/frontend-testids.md,
 * minted with this journey): the knowledge-graph course dropdown
 * (`home-course-menu`, Home v2) mounts once enrollments load, so the spec waits
 * for it, then asserts the seeded course among its options. The course itself is asserted by seeded
 * DATA, not copy: `rich-course-math210` ("MATH210" — Linear Algebra,
 * db/seed_local_rich.py) is rich-user-active's spring-2026 enrollment, and
 * spring 2026 is the current term under the frozen test-mode clock
 * (2026-03-11), so its row always renders in the current — never Archive —
 * bucket of the key.
 */
import { test } from "./support/fixtures";
import { expectHomeCourse, waitForHome } from "./support/home";

test("seeded session lands on dashboard with a seeded course visible", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // The course dropdown only mounts once enrollments have loaded, so waiting
  // for it doubles as the "dashboard data arrived" gate.
  await waitForHome(page);

  // The knowledge-graph course dropdown lists every enrolled course by code.
  await expectHomeCourse(page, "MATH210");
});
