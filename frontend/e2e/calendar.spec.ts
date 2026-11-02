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

test("linked Google events appear in the calendar without duplicates after refreshing", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-03-11T12:00:00Z") });
  await page.addInitScript(() => {
    globalThis.__SAPLING_TEST_NOW__ = Date.UTC(2026, 2, 11, 12);
  });
  let eventsEnabled = true;
  await page.route("**/api/calendar/status/**", route => route.fulfill({ json: { connected: true, events_enabled: eventsEnabled } }));
  await page.route("**/api/calendar/disconnect/**", route => {
    eventsEnabled = false;
    return route.fulfill({ json: { disconnected: true } });
  });
  await page.route("**/api/calendar/connect/**", route => {
    eventsEnabled = true;
    return route.fulfill({ json: { events_enabled: true } });
  });
  let title = "Google office hours";
  await page.route("**/api/calendar/import/**", route => {
    const event = { google_event_id: "g1", calendar_id: "c1", primary_calendar: true,
      title, all_day: true, start_date: "2026-03-11", end_date: "2026-03-12" };
    return route.fulfill({ json: { events: [event, event], count: 2 } });
  });
  await page.goto("/calendar");
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toHaveCount(1);
  title = "Updated Google office hours";
  await page.getByRole("button", { name: "Refresh Google events" }).click();
  await expect(page.getByText(title, { exact: true })).toHaveCount(1);
  await expect(page.getByText("Google office hours", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Day", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "Disconnect events", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Export all to Google" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Reconnect events", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reconnect events", exact: true }).click();
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toHaveCount(1);
});

test("month navigation visits February from the last day of January", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-01-31T17:00:00Z") });
  await page.addInitScript(() => {
    globalThis.__SAPLING_TEST_NOW__ = Date.UTC(2026, 0, 31, 17);
  });
  await page.goto("/calendar");
  await expect(page.getByText("Mon", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page.getByText(/^January 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText(/^February 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText(/^March 2026 ·/)).toBeVisible();
  await page.getByRole("button", { name: "Prev", exact: true }).click();
  await expect(page.getByText(/^February 2026 ·/)).toBeVisible();
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
