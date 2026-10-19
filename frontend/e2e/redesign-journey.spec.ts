/**
 * Journey (redesign prompt 05): Library → Learn → Clov tutor → Library, as ONE
 * learning flow on the integrated redesign.
 *
 * Proves the cross-surface contracts the per-surface journeys cannot:
 *  1. Library's "Ask Clov" deep link carries the course: the studio opens a
 *     session on THAT course (the stored session's offering is the course's);
 *  2. switching the studio ↔ the tutor view keeps the SAME session: the
 *     sessions rows are unchanged after every switch, the same `data-session-id`, and no second
 *     start-session request;
 *  3. the tutor's Materials link carries the course back: Library opens with
 *     that course pre-selected (`?course=`) and lists only its materials;
 *  4. returning from Library ("Ask Clov") resumes the same session — no new
 *     row — and the tutor ↔ studio switches keep it.
 *
 * Runs as the multi-course seeded student (rich-user-active: CS101, MATH210,
 * BIO110, ENG150, with a seeded document in MATH210) so "keeps the course" is a
 * real choice, not the only course. Function mode, as learn-loop.spec.ts.
 */
import type { Page } from "@playwright/test";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { setUserFlag } from "./support/flags";
import { USER_ACTIVE } from "./support/stack";

/** The shell's <main>: until React reveals a streamed
 *  shell page, the server's copy sits in a hidden `<div hidden id="S:N">`
 *  outside it (see upload.spec.ts::appShellUpload). Only page-level ids read
 *  right after a navigation are scoped: sheets and dialogs portal to <body>. */
function shell(page: Page) {
  return page.getByTestId("app-shell");
}

const MATH_COURSE = "rich-course-math210";
const MATH_DOC = "rich-doc-math-notes";
const MATH_DOC_NAME = "linear-algebra-notes.pdf";

/** This student's learning sessions with the ABSTRACT course each runs on
 *  (the loop resolves the course's current-term offering, so the offering id
 *  itself is not the seeded one). */
async function learningSessions(): Promise<{ id: string; course_id: string }[]> {
  return (await queryRaw(
    `SELECT s.id, o.course_id
       FROM sessions s JOIN course_offerings o ON o.id = s.offering_id
      WHERE s.user_id = $1 AND s.mode <> 'review'
      ORDER BY s.started_at, s.id`,
    [USER_ACTIVE],
  )) as { id: string; course_id: string }[];
}

test("Library → Learn → tutor → Library keeps the course and ONE session (redesign prompt 05)", async ({ browser, page }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(120_000);
  await setUserFlag(browser, "tutor_view", USER_ACTIVE, "on");
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    // The shell's global prompts are out of scope here and would cover the
    // page: the session pulse opens on every client-side exit from /learn
    // (SessionFeedbackGlobal) and the general pulse after 45 s (FeedbackFlow).
    // Both honour a recent cooldown stamp.
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
  });
  const starts: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/learn/loop/start-session")) starts.push(r.url());
  });

  // 1. Library: pick the MATH210 material and ask Clov about its course.
  await page.goto("/library");
  const courseFilter = shell(page).getByTestId("library-course-filter");
  await expect(courseFilter.locator(`option[value="${MATH_COURSE}"]`)).toHaveCount(1);
  await courseFilter.selectOption(MATH_COURSE);
  await shell(page).getByTestId(`library-doc-${MATH_DOC}`).click();
  const ask = page.getByTestId("library-detail-ask-clov");
  await expect(ask).toHaveAttribute("href", `/learn?course=${MATH_COURSE}`);
  // The seed carries legacy (classic tutor) sessions for this student; the
  // journey asserts against that baseline.
  const seeded = await learningSessions();
  await ask.click();

  // 2. The studio opens a loop session on THAT course (not the first
  // enrollment): exactly one new sessions row, on MATH210.
  await expect(page).toHaveURL(/\/learn/);
  const root = shell(page).getByTestId("loop-phase");
  await expect(root).not.toHaveAttribute("data-session-id", "", { timeout: 30_000 });
  const sessionId = (await root.getAttribute("data-session-id"))!;
  await expect.poll(async () => (await learningSessions()).length).toBe(seeded.length + 1);
  const afterStart = await learningSessions();
  expect(afterStart.filter((r) => !seeded.some((s) => s.id === r.id))).toEqual([
    { id: sessionId, course_id: MATH_COURSE },
  ]);
  expect(starts).toHaveLength(1);

  // 3. Studio → tutor: a view change only. Same session, same row, no start.
  await page.getByTestId("loop-view-tutor").click();
  await expect(root).toHaveAttribute("data-view", "tutor");
  await expect(page).toHaveURL(/view=tutor/);
  await expect(root).toHaveAttribute("data-session-id", sessionId);

  // 4. The tutor's Materials are this course's, and its Library link keeps it.
  await page.getByTestId("tutor-context-materials").click();
  const materials = page.getByTestId("tutor-materials");
  await expect(materials).toContainText(MATH_DOC_NAME);
  const toLibrary = page.getByTestId("tutor-materials-library");
  await expect(toLibrary).toHaveAttribute("href", `/library?course=${MATH_COURSE}`);
  await toLibrary.click();
  await expect(page).toHaveURL(new RegExp(`/library\\?course=${MATH_COURSE}`));
  await expect(courseFilter).toHaveValue(MATH_COURSE);
  await expect(shell(page).getByTestId(`library-doc-${MATH_DOC}`)).toBeVisible();
  await expect(shell(page).locator('[data-testid^="library-doc-"]')).toHaveCount(1);

  // 5. Back to Clov from Library ("Ask Clov", the in-app path): the open
  // MATH210 session RESUMES — no second session, no start request. (The
  // browser Back button lands on /learn?view=tutor without the course, which
  // opens the default course: a pre-existing loop gap, see 05-review-package.)
  await shell(page).getByTestId(`library-doc-${MATH_DOC}`).click();
  await page.getByTestId("library-detail-ask-clov").click();
  await expect(page).toHaveURL(/\/learn/);
  await expect(root).toHaveAttribute("data-session-id", sessionId, { timeout: 15_000 });

  // 6. Studio → tutor → studio (the tutor's session menu): same session again.
  await page.getByTestId("loop-view-tutor").click();
  await expect(root).toHaveAttribute("data-view", "tutor");
  await expect(root).toHaveAttribute("data-session-id", sessionId);
  await page.getByTestId("tutor-menu").click();
  await page.getByTestId("tutor-menu-studio").click();
  await expect(root).not.toHaveAttribute("data-view", "tutor");
  await expect(root).toHaveAttribute("data-session-id", sessionId);

  expect(starts).toHaveLength(1);
  expect(await learningSessions()).toEqual(afterStart);
});
