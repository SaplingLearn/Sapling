/**
 * Journey #141 — the semester selector scopes the STUDY-TOOL reads.
 *
 * The reframe: NO Archive toggle. The existing selector (Courses & Semesters
 * hub → lib/useActiveSemester; "" = All semesters, the e2e-pinned DEFAULT)
 * scopes the study reads the same way it already scopes the graph — the
 * study-tool endpoints used to hardcode current-term resolution
 * (`resolve_offering(course_id)`), pinning every course-scoped read to
 * spring-2026 under the frozen test clock (2026-03-11) regardless of the
 * user's selection.
 *
 * Flashcards are the assertable read (no generation involved — the seam
 * caution stands: nothing here may trigger flashcard/study-guide
 * generation). Seeded data (db/seed_local_rich.py): rich-user-active has the
 * "CS Basics" deck ×3 on the fall-2025 CS101 offering and the "Linear
 * Algebra" deck ×3 on the spring-2026 MATH210 offering.
 *
 *   1. Default (All semesters): BOTH terms' decks are visible together —
 *      cross-term data under the untouchable default (#360 contract).
 *   2. Pick "Fall 2025" in the hub: /study serves the FALL deck (the #141
 *      point — current-term resolution served spring only) and the
 *      spring-only deck is gone.
 *
 * Selectors: topic pills are buttons named by seeded deck names (data, not
 * copy); the hub is reached exactly as in semester-scope.spec.ts. The
 * "Card 1 of N" counter pins the scoped deck SIZE (N is data; the phrasing
 * is stable Study copy).
 */
import { expect, test } from "./support/fixtures";

test("study flashcards follow the semester selection; All semesters shows every term", async ({
  page,
}) => {
  // 1. Default = All semesters: fall AND spring decks render together.
  await page.goto("/study?mode=cards");
  await expect(page.getByRole("button", { name: "CS Basics" })).toBeVisible();
  // .first(): "Linear Algebra" is both MATH210's course pill and the deck's
  // topic pill under All semesters — any match proves the spring deck
  // surfaced; the "Card 1 of 6" counter is the actual scoping assertion.
  await expect(page.getByRole("button", { name: "Linear Algebra" }).first()).toBeVisible();
  await expect(page.getByText("Card 1 of 6")).toBeVisible();

  // 2. Scope to Fall 2025 via the Courses & Semesters hub (dashboard).
  await page.goto("/dashboard");
  await page.getByTestId("dashboard-courses-key-toggle").click();
  await page.getByTestId("dashboard-courses-manage").click();
  await page.getByRole("button", { name: "Fall 2025" }).click();
  await page.getByRole("button", { name: "Close" }).click();

  // 3. /study now serves the fall-2025 deck — the read the current-term
  //    resolution used to hide — and the spring-only deck is filtered out.
  await page.goto("/study?mode=cards");
  await expect(page.getByRole("button", { name: "CS Basics" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Linear Algebra" })).toHaveCount(0);
  await expect(page.getByText("Card 1 of 3")).toBeVisible();
});
