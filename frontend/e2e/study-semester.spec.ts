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
 * Flashcards are the assertable read, on the page they moved to in #870:
 * /flashcards (screens/Flashcards.tsx; the old `/study?mode=cards` pane now
 * redirects there). That page shows ONE course at a time — there is no
 * all-courses view — so the journey walks the courses instead of reading two
 * decks off one screen. No generation is involved (the seam caution stands):
 * every review here is of SEEDED cards, played from the "All of <course>"
 * deck, which never generates (home/decksModel.ts).
 *
 * Seeded data (db/seed_local_rich.py): rich-user-active has "CS Basics" ×3 on
 * the FALL-2025 CS101 offering and "Linear Algebra" ×3 on the SPRING-2026
 * MATH210 offering. They are enrolled in CS101 in both terms and in MATH210
 * in spring only.
 *
 *   1. Default (All semesters): BOTH terms' cards are there — the fall deck
 *      under CS101 and the spring deck under MATH210 — and the card read
 *      names no term (#360 contract: cross-term data under the default).
 *   2. Pick "Fall 2025" in the hub: the read names that term, CS101 serves
 *      the FALL deck (the #141 point — current-term resolution served spring
 *      only), and the spring-only course is not offered at all.
 *   3. Pick "Spring 2026": the read names that term and the SAME course,
 *      CS101, now has no cards — its only deck belongs to the fall offering —
 *      while MATH210's spring deck is served. This is the leg that tells a
 *      scoped read from the page's own per-course filter.
 *
 * Selectors: the `flashcards` testid surface (docs/frontend-testids.md) for
 * the figures, the deck and the review card; the deck's play button and the
 * course options by role/name (their names are seeded course codes — data,
 * not copy); the hub is reached exactly as in semester-scope.spec.ts. The
 * "Card 1 of N" counter pins the reviewed deck's SIZE (N is data; the phrasing
 * is stable Flashcards copy).
 */
import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";

const COURSE_CS = "rich-course-cs101";
const COURSE_MATH = "rich-course-math210";
/** The "All of <course>" deck: every card the course has, never generated. */
const ALL_DECK = "flashcards-deck-auto:all";

/**
 * Open /flashcards on a course and wait for its home. Resolves with the term
 * the page asked the card list for — the selector's label, as the API takes
 * it (`null`: no `semester` param, i.e. All semesters). That read is what this
 * journey is about.
 */
async function openFlashcards(page: Page, courseId: string): Promise<string | null> {
  const cardRead = page.waitForRequest((req) => {
    const url = new URL(req.url());
    return req.method() === "GET" && /^\/api\/flashcards\/user\/[^/]+$/.test(url.pathname);
  });
  await page.goto(`/flashcards?course=${courseId}`);
  const semester = new URL((await cardRead).url()).searchParams.get("semester");
  await expect(page.getByTestId(ALL_DECK)).toBeVisible({ timeout: 30_000 });
  return semester;
}

/** The hero's "cards" figure: how many cards the course has under this term. */
const cardCount = (page: Page) => page.getByTestId("flashcards-figure-cards").locator("dd");

/** Play the course's whole deck and assert what the review serves. */
async function expectDeck(page: Page, topic: string, size: number): Promise<void> {
  await expect(cardCount(page)).toHaveText(String(size));
  await page.getByTestId(ALL_DECK).getByRole("button", { name: /^Review All of / }).click();
  await expect(page.getByText(`Card 1 of ${size}`)).toBeVisible();
  // The deck is shuffled, but every card in it carries the seeded topic.
  await expect(page.getByTestId("flashcards-topic")).toHaveText(topic);
}

/** Pick a term in the Courses & Semesters hub (dashboard). */
async function pickSemester(page: Page, label: string): Promise<void> {
  await page.goto("/dashboard");
  await page.getByTestId("dashboard-courses-manage").click();
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("button", { name: "Close" }).click();
}

/** The course picker's options (course codes), as the page offers them now. */
async function offeredCourses(page: Page) {
  await page.locator('button[aria-haspopup="listbox"]').click();
  return page.getByRole("listbox", { name: "Courses" }).getByRole("option");
}

test("flashcards follow the semester selection; All semesters shows every term", async ({
  page,
}) => {
  // 1. Default = All semesters: the read is unscoped, and the fall deck (on
  //    CS101) and the spring deck (on MATH210) are both served.
  expect(await openFlashcards(page, COURSE_CS)).toBeNull();
  await expectDeck(page, "CS Basics", 3);
  expect(await openFlashcards(page, COURSE_MATH)).toBeNull();
  await expectDeck(page, "Linear Algebra", 3);

  // 2. Scope to Fall 2025: the read names the term and CS101 serves the
  //    fall-2025 deck — the read the current-term resolution used to hide.
  await pickSemester(page, "Fall 2025");
  expect(await openFlashcards(page, COURSE_CS)).toBe("Fall 2025");
  await expectDeck(page, "CS Basics", 3);
  // The spring-only course is not on offer under Fall 2025, so its deck is
  // unreachable: the picker lists this term's courses only.
  await page.getByTestId("back-link").click();
  const fallCourses = await offeredCourses(page);
  await expect(fallCourses.filter({ hasText: "CS101" })).toHaveCount(1);
  await expect(fallCourses.filter({ hasText: "MATH210" })).toHaveCount(0);

  // 3. Scope to Spring 2026: CS101 is still a course this term, but its only
  //    cards sit on the FALL offering, so the scoped read serves none of them…
  await pickSemester(page, "Spring 2026");
  expect(await openFlashcards(page, COURSE_CS)).toBe("Spring 2026");
  await expect(cardCount(page)).toHaveText("0");
  //    …while the spring deck is served on its own course.
  expect(await openFlashcards(page, COURSE_MATH)).toBe("Spring 2026");
  await expectDeck(page, "Linear Algebra", 3);
});
