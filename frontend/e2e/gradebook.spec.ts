/**
 * Journey #139 — gradebook term switcher + transcript.
 *
 * Two journeys over the `gradebook` testid surface (docs/frontend-testids.md):
 *
 * 1. Multi-term course resolution — the promoted regression for the #139
 *    404. The card link used to drop the selected term, so
 *    `_resolve_enrollment(user, course, None)` resolved the CURRENT term and
 *    a course also taken in an archived term 404'd ("Course not in your
 *    gradebook") from that term's chip. DB truth first (support/db.ts
 *    ::queryRaw): rich-user-active holds TWO enrollments of
 *    rich-course-cs101 (fall-2025 + spring-2026 offerings,
 *    db/seed_local_rich.py) — the precondition that makes the ambiguity
 *    real. Then each chip's CS101 card must open THAT term's enrollment,
 *    told apart by seeded category names (Fall: Homework/Exams; Spring:
 *    Homework/Projects). The Fall leg also WRITES (#468 review): an
 *    assignment created from the Fall page must hang off the fall-2025
 *    enrollment row — mutations used to resolve term-blind and would have
 *    landed it on the CURRENT (spring-2026) enrollment.
 *
 * 2. Transcript — the landing's Transcript button opens the cumulative
 *    modal: a real x.xx GPA plus per-semester sections for both seeded
 *    terms.
 *
 * Test-mode clock note: the e2e frontend runs with the frozen clock
 * 2026-03-11, so the landing's DEFAULT chip is Spring 2026. Chips are always
 * selected explicitly here — never rely on the default.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

const COURSE_CS = "rich-course-cs101";

test("a course taken in two terms opens the right enrollment from each chip", async ({
  page,
}) => {
  // DB truth: the seeded ambiguity this journey exists for. If the seed ever
  // stops enrolling the user in CS101 twice, this journey silently stops
  // covering #139 — fail loudly instead.
  const enrollments = await queryRaw(
    `SELECT o.term_id
       FROM enrollments e
       JOIN course_offerings o ON o.id = e.offering_id
      WHERE e.user_id = $1 AND o.course_id = $2
      ORDER BY o.term_id`,
    [USER_ACTIVE, COURSE_CS],
  );
  expect(enrollments.map((r) => r.term_id)).toEqual(["fall-2025", "spring-2026"]);

  await page.goto("/gradebook");

  const grid = page.getByRole("grid", { name: "Courses" });
  const csCard = grid.getByRole("link").filter({ hasText: "CS101" });

  // Fall 2025 — the ARCHIVED term under the frozen clock, i.e. the chip that
  // used to 404. Its CS101 card must load the Fall enrollment: the Exams
  // category exists only on the fall-2025 gradebook.
  await page.getByRole("button", { name: "Fall 2025", exact: true }).click();
  await csCard.click();
  await expect(
    page.getByRole("heading", { name: "Introduction to Computer Science" }),
  ).toBeVisible();
  await expect(page.getByText("Exams").first()).toBeVisible();
  await expect(page.getByText("We couldn't load this course.")).toHaveCount(0);

  // Mutation leg (#468): a write from the Fall page must land on the FALL
  // enrollment. Create an assignment through the modal, then assert the row
  // hangs off rich-enr-active-cs101-f25 — NOT the spring enrollment the
  // term-blind resolver would have picked (spring-2026 is the current term
  // under the frozen clock).
  await page.getByTestId("gradebook-add-assignment").click();
  await page.getByTestId("gradebook-assignment-title").fill("Fall-only essay");
  await page.getByTestId("gradebook-assignment-save").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect
    .poll(async () => {
      const rows = await queryRaw(
        `SELECT enrollment_id FROM assignments WHERE title = $1`,
        ["Fall-only essay"],
      );
      return rows.map((r) => r.enrollment_id);
    })
    .toEqual(["rich-enr-active-cs101-f25"]);

  // Back on the landing, pick Spring 2026 explicitly: its CS101 card must
  // load the OTHER enrollment — Projects only exists on spring-2026.
  await page.goBack();
  await page.getByRole("button", { name: "Spring 2026", exact: true }).click();
  await csCard.click();
  await expect(
    page.getByRole("heading", { name: "Introduction to Computer Science" }),
  ).toBeVisible();
  await expect(page.getByText("Projects").first()).toBeVisible();
  await expect(page.getByText("We couldn't load this course.")).toHaveCount(0);
});

test("the transcript modal shows a cumulative GPA and every seeded term", async ({
  page,
}) => {
  await page.goto("/gradebook");

  await page.getByTestId("gradebook-transcript-open").click();

  const dialog = page.getByRole("dialog");
  // The seed has graded work (CS101 Fall homework, …), so the cumulative GPA
  // is a real x.xx number — never the "—" placeholder.
  await expect(page.getByTestId("gradebook-transcript-gpa")).toHaveText(/\d\.\d\d/);

  // Per-semester sections for both multi-enrollment terms.
  await expect(dialog.getByText("Fall 2025", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Spring 2026", { exact: true })).toBeVisible();
});
