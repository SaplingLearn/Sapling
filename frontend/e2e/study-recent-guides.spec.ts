/**
 * Regression journey for #476 — opening a guide from the "Recent guides" rail
 * must leave the exam SELECTED, so Regenerate is usable on that path.
 *
 * The bug: openRecent sets courseId AND examId together, but the courseId-keyed
 * exams effect opened with an unconditional `setExamId("")`. Both effects ran in
 * the same commit, so the guide still loaded and only the NEXT render lost the
 * exam — leaving a guide on screen above a dead Regenerate button. It needs a
 * COURSE CHANGE to reproduce, which a fresh /study load gives for free
 * (courseId starts ""); a rail entry for the already-selected course never
 * tripped it.
 *
 * Seeded (db/seed_local_rich.py): rich-guide-cs-f25-mid, a CACHED guide for
 * rich-user-active on the fall-2025 CS101 offering, keyed to the real
 * "Midterm Exam" assignment. Cached matters — the guide GET returns the row
 * before reaching the study_guide agent, which has NO function-mode handler.
 * For the same reason this journey must never CLICK Regenerate: asserting the
 * button is enabled is the fix; pressing it would generate.
 */
import { expect, test } from "./support/fixtures";

// The course and exam pickers are the only listbox triggers on the guide pane,
// in that DOM order. Once both hold a value their accessible names no longer
// distinguish them from the rail entry, which repeats the exam title.
const examPicker = (page: import("@playwright/test").Page) =>
  page.locator('button[aria-haspopup="listbox"]').nth(1);

test("opening a recent guide keeps the exam selected, so Regenerate is usable", async ({
  page,
}) => {
  await page.goto("/study");

  // Before any selection the exam picker reads "Select a course first", so the
  // rail entry is the only thing named for the exam.
  const railEntry = page.getByRole("button", { name: /Midterm Exam/ });
  await expect(railEntry).toBeVisible();
  await expect(examPicker(page)).toHaveText(/Select a course first/);

  await railEntry.click();

  // The guide loads — that was never the broken half.
  await expect(page.getByText("Covers variables, control flow, and functions.")).toBeVisible();

  // #476: the selection openRecent made survives the course change it caused.
  await expect(examPicker(page)).toHaveText(/Midterm Exam/);
  await expect(page.getByRole("button", { name: /Regenerate/ })).toBeEnabled();
});
