/**
 * Journey — semester scoping is opt-in, All semesters is the default (#360).
 *
 * The e2e lane vetoed auto-resolving a default term: the rich seed spans
 * Fall 2025 / Spring 2026 / Fall 2026, and an auto-picked term silently hid
 * cross-term fixtures (dashboard lost MATH210; the graph shrank to one term's
 * nodes). This journey pins the reworked contract:
 *
 *   1. Default (nothing stored) = ALL SEMESTERS — courses from different
 *      terms are visible together (Spring 2026 MATH210 AND Fall 2025 BIO110).
 *   2. Picking "Fall 2025" in the Courses & Semesters hub scopes the
 *      dashboard: the Fall course stays, the Spring-only MATH210 disappears.
 *   3. Picking "All semesters" clears the scope: MATH210 is back.
 *
 * Selectors: the `dashboard` testid surface (docs/frontend-testids.md) for the
 * key overlay + hub trigger; the hub's semester tabs are plain text buttons
 * selected by role/name ("Fall 2025", "All semesters" — unique in the page).
 * Course rows are asserted by seeded DATA (db/seed_local_rich.py):
 * rich-user-active is enrolled in MATH210 only in spring-2026 and BIO110 only
 * in fall-2025. Every assertion is an auto-waiting expect — no timeouts.
 */
import { test } from "./support/fixtures";
import { expectHomeCourse, openCoursesHub, waitForHome } from "./support/home";

test("dashboard defaults to all semesters; picking a term scopes it; All clears", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // The Home course dropdown only mounts once enrollments have loaded, so
  // waiting for it doubles as the "dashboard data arrived" gate.
  await waitForHome(page);

  // 1. Default = All semesters: cross-term courses are offered TOGETHER.
  await expectHomeCourse(page, "MATH210"); // Spring 2026 only
  await expectHomeCourse(page, "BIO110"); // Fall 2025 only

  // 2. Open the Courses & Semesters hub and pick Fall 2025.
  await openCoursesHub(page);
  await page.getByRole("button", { name: "Fall 2025" }).click();
  await page.getByRole("button", { name: "Close" }).click();

  // Scoped: the Fall course stays, the Spring-only course is gone.
  await expectHomeCourse(page, "BIO110");
  await expectHomeCourse(page, "MATH210", false);

  // 3. Back to All semesters — the cross-term view is restored.
  await openCoursesHub(page);
  await page.getByRole("button", { name: "All semesters" }).click();
  await page.getByRole("button", { name: "Close" }).click();

  await expectHomeCourse(page, "MATH210");
  await expectHomeCourse(page, "BIO110");
});
