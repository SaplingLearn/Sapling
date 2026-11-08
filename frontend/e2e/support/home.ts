import { expect, type Page } from "@playwright/test";

/**
 * Home (Dashboard) course controls after the Home v2 redesign: the old
 * always-open "My courses" key is gone; courses live in the knowledge-graph
 * course dropdown (`home-course-menu`), and the Courses & Semesters hub is the
 * last row of that dropdown (`home-manage-courses`).
 */

/** Wait for Home data: the course dropdown mounts once enrollments load. */
export async function waitForHome(page: Page): Promise<void> {
  await expect(page.getByTestId("home-course-menu")).toBeVisible({ timeout: 30_000 });
}

/** Course codes listed in the dropdown (opens and closes it). */
export async function homeCourseCodes(page: Page): Promise<string[]> {
  await page.getByTestId("home-course-menu").click();
  const list = page.getByRole("listbox", { name: "Courses" });
  await expect(list).toBeVisible();
  const codes = (await list.getByRole("option").allInnerTexts()).map((t) => t.split("\n")[0].trim());
  await page.getByTestId("home-course-menu").click();
  return codes;
}

/** Assert a course code is (or is not) offered in the dropdown. */
export async function expectHomeCourse(page: Page, code: string, present = true): Promise<void> {
  await expect.poll(async () => (await homeCourseCodes(page)).includes(code)).toBe(present);
}

/** Open the Courses & Semesters hub from the dropdown. */
export async function openCoursesHub(page: Page): Promise<void> {
  await page.getByTestId("home-course-menu").click();
  await page.getByTestId("home-manage-courses").click();
}
