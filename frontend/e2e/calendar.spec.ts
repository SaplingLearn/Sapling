/**
 * Journey — the calendar survives an undated assignment.
 *
 * Promoted regression for the /calendar crash: `assignments.due_date` has
 * been nullable since 0012 (gradebook items and Gradescope imports may carry
 * no date), but the month grid called `a.due_date.slice(0, 10)` on every
 * row. One undated assignment threw "Cannot read properties of null
 * (reading 'slice')" and the whole screen fell into the error boundary,
 * with "Try again" re-crashing on the same data.
 *
 * The undated row is created the way real users create one — the gradebook
 * "add assignment" modal with only a title — and DB truth confirms it really
 * is NULL before the calendar is opened. Then the calendar must render its
 * month grid (no error boundary), list the item in the Table view as
 * "No date", and save an edit to it without inventing a date.
 *
 * Test-mode clock note: the e2e frontend runs with the frozen clock
 * 2026-03-11; the Spring 2026 chip is selected explicitly anyway.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";

const TITLE = "Undated participation";

test("month navigation visits February from the last day of January", async ({ page }) => {
  await page.addInitScript(() => {
    globalThis.__SAPLING_TEST_NOW__ = Date.UTC(2026, 0, 31, 17);
  });
  await page.goto("/calendar");
  await expect(page.getByText("Mon", { exact: true })).toBeVisible();
  await expect(page.getByText(/January 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText(/February 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText(/March 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Prev", exact: true }).click();
  await expect(page.getByText(/February 2026 ·/)).toBeVisible();
});

test("an assignment with no due date does not crash the calendar", async ({ page }) => {
  await page.goto("/gradebook");
  await page.getByRole("button", { name: "Spring 2026", exact: true }).click();
  await page
    .getByRole("grid", { name: "Courses" })
    .getByRole("link")
    .filter({ hasText: "CS101" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Introduction to Computer Science" }),
  ).toBeVisible();

  await page.getByTestId("gradebook-add-assignment").click();
  await page.getByTestId("gradebook-assignment-title").fill(TITLE);
  await page.getByTestId("gradebook-assignment-save").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // DB truth: the precondition this journey exists for. If the modal ever
  // starts defaulting a date, this stops covering the crash — fail loudly.
  await expect
    .poll(async () => {
      const rows = await queryRaw(
        `SELECT due_date FROM assignments WHERE title = $1`,
        [TITLE],
      );
      return rows.map((r) => r.due_date);
    })
    .toEqual([null]);

  await page.goto("/calendar");
  await expect(page.getByText("Mon", { exact: true })).toBeVisible();
  await expect(page.getByText("We hit a snag")).toHaveCount(0);

  await page.getByRole("button", { name: "Table", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: TITLE });
  await expect(row).toBeVisible();
  await expect(row.getByText("No date", { exact: true })).toBeVisible();

  // Editing the undated row must save: the empty date input used to go out
  // as due_date "", which the DATE column rejects, so every save failed.
  await row.getByTitle("Edit").click();
  await page
    .getByRole("cell", { name: TITLE, exact: true })
    .getByRole("textbox")
    .fill(`${TITLE} (edited)`);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Assignment updated.")).toBeVisible();
  await expect
    .poll(async () => {
      const rows = await queryRaw(
        `SELECT due_date FROM assignments WHERE title = $1`,
        [`${TITLE} (edited)`],
      );
      return rows.map((r) => r.due_date);
    })
    .toEqual([null]);
});
