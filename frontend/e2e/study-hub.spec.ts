/**
 * Journey #870 — the Study hub (/study, components/study/StudyHub.tsx), and the
 * way out of it into Flashcards.
 *
 * The hub is one page per course: a readiness figure, the course's concepts
 * as a roadmap of tiles, and a Daily Goal card. A concept's "..." menu goes
 * straight INTO a tool for it (`start=1`, lib/toolHrefs.ts): for a concept
 * with no cards, Flashcards makes them on arrival and opens the review.
 *
 *   1. The hub renders for the seeded student on a course (a), and an edited
 *      daily goal is stored and survives a reload (b).
 *   2. "Make Flashcards" on a concept with NO cards lands on /flashcards, the
 *      function-mode model generates, and the review opens on a scripted card
 *      (c). Closing the review does not start it again, and neither does a
 *      reload after closing (d).
 *
 * (c) is two regressions in one path. The `flashcard` agent had no
 * function-mode handler, so the generate call answered 502. And the page read
 * `start` off the ADDRESS BAR while it first rendered — which, on a
 * client-side navigation, is still the hub's URL (the router writes the new
 * one when the render commits): arriving from the hub opened the set builder
 * and started nothing, while typing the same link into the address bar worked.
 * So this journey must arrive by CLICKING through the hub, never by `goto`.
 *
 * Seeded (db/seed_local_rich.py): rich-user-active's first course is CS101,
 * with five concepts (mastery 92 / 60 / 25 / 5 / 80; the 5% one counts as not
 * started) and flashcards on the topic "CS Basics" only — none on "Recursion".
 * No daily goal is seeded, so the Daily Goal starts at the column default
 * (`user_settings.daily_goal_minutes`, 30).
 *
 * Function mode: POST /api/flashcards/generate answers with the fixed
 * E2E_FLASHCARDS (backend/agents/function_handlers_e2e.py — three cards whose
 * fronts start "[e2e-function-model]", whatever topic or count was asked for).
 * Keep CARD_FRONT in sync with that constant and with
 * backend/tests/test_e2e_function_handlers.py.
 *
 * Selectors: the hub's and the `flashcards` testids (docs/frontend-testids.md);
 * the Daily Goal's controls and the tile menu by role/name — their names are
 * built from DATA (the goal in minutes, the seeded concept name).
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";

const COURSE_CS = "rich-course-cs101";
const NODE_RECURSION = "rich-node-cs-recursion";
const CS_NODES = [
  "rich-node-cs-variables",
  "rich-node-cs-controlflow",
  NODE_RECURSION,
  "rich-node-cs-pointers",
  "rich-node-cs-algorithms",
];

/** The front of any one of E2E_FLASHCARDS (the deck is shuffled). */
const CARD_FRONT =
  /\[e2e-function-model\] (What must every recursive function have\?|What does the recursive step do\?|What happens without a base case\?)/;

const goalRows = () =>
  queryRaw("select daily_goal_minutes from user_settings where user_id = $1", [USER_ACTIVE]);

const recursionCards = async () =>
  (
    await queryRaw("select count(*)::int as n from flashcards where user_id = $1 and topic = $2", [
      USER_ACTIVE,
      "Recursion",
    ])
  )[0].n;

test("the hub renders the seeded course, and an edited daily goal persists", async ({ page }) => {
  await page.goto("/study");

  // (a) The hub, on the student's first course.
  // Readiness is the mean mastery of the course's concepts, a not-started one
  // counting as 0: (92 + 60 + 25 + 0 + 80) / 5 = 51.4.
  await expect(page.getByTestId("readiness-pct")).toHaveText("51%", { timeout: 30_000 });
  // The course field is the page's only listbox trigger.
  await expect(page.locator('button[aria-haspopup="listbox"]')).toContainText("CS101");
  const roadmap = page.getByRole("region", { name: "Roadmap" });
  for (const node of CS_NODES) await expect(roadmap.getByTestId(`tile-${node}`)).toBeVisible();
  await expect(roadmap.getByTestId(/^tile-rich-node-/)).toHaveCount(CS_NODES.length);

  const goal = page.getByTestId("daily-goal");
  const target = (minutes: number) =>
    goal.getByRole("button", { name: `Daily goal: ${minutes} minutes. Change daily goal` });
  await expect(target(30)).toBeVisible();
  // Nothing stored yet but the column default (the row itself is made lazily,
  // by whichever setting is written first).
  expect((await goalRows()).filter((row) => row.daily_goal_minutes !== 30)).toEqual([]);

  // (b) The target is the edit button; one tap on a preset saves it.
  await target(30).click();
  const presets = goal.getByRole("radiogroup", { name: "Daily goal, minutes a day" });
  await expect(presets.getByRole("radio", { name: "30 minutes" })).toBeChecked();
  const saved = page.waitForResponse(
    (res) => res.request().method() === "PATCH" && res.url().endsWith(`/api/study/${USER_ACTIVE}/daily-goal`),
  );
  await presets.getByRole("radio", { name: "45 minutes" }).click();
  expect((await saved).status()).toBe(200);
  await expect(target(45)).toBeVisible();
  expect(await goalRows()).toEqual([{ daily_goal_minutes: 45 }]);

  // It is the stored goal the hub shows, not the one this page was holding.
  await page.reload();
  await expect(target(45)).toBeVisible({ timeout: 30_000 });
});

test("Make Flashcards on a concept with no cards generates them and reviews; closing does not restart", async ({
  page,
}) => {
  expect(await recursionCards()).toBe(0);
  const generateCalls: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && new URL(req.url()).pathname === "/api/flashcards/generate") {
      generateCalls.push(req.postData() ?? "");
    }
  });

  await page.goto(`/study?course=${COURSE_CS}`);
  await page.getByTestId(`tile-actions-${NODE_RECURSION}`).click({ timeout: 30_000 });
  const make = page
    .getByRole("menu", { name: "Recursion actions" })
    .getByRole("menuitem", { name: "Make Flashcards" });
  // The link asks Flashcards to START on this concept, not just to open.
  await expect(make).toHaveAttribute(
    "href",
    `/flashcards?course=${COURSE_CS}&concepts=Recursion&start=1`,
  );

  // (c) Clicked through (a client-side navigation): the cards are made, then
  // the review opens on them.
  const generated = page.waitForResponse(
    (res) => res.request().method() === "POST" && new URL(res.url()).pathname === "/api/flashcards/generate",
  );
  await make.click();
  expect((await generated).status()).toBe(200);
  await expect(page.getByText("Card 1 of 3")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("flashcards-deck-name")).toHaveText("Recursion");
  await expect(page.getByTestId("flashcards-topic")).toHaveText("Recursion");
  await expect(page.getByTestId("flashcards-card")).toContainText(CARD_FRONT);
  expect(JSON.parse(generateCalls[0])).toMatchObject({
    user_id: USER_ACTIVE,
    topic: "Recursion",
    course_id: COURSE_CS,
  });
  expect(await recursionCards()).toBe(3);
  // `start` has been acted on and is gone; the open review is marked instead,
  // so a reload HERE comes back to this review rather than starting another.
  await expect(page).toHaveURL(/\/flashcards\?(?!.*\bstart=).*\breview=1/);

  // (d) Close it. The page stays out of the review, and the URL asks for
  // nothing to be started.
  await page.getByTestId("back-link").click();
  await expect(page.getByTestId("flashcards-figure-cards").locator("dd")).toHaveText("6");
  await expect(page.getByText(/Card \d+ of \d+/)).toHaveCount(0);
  await expect(page).toHaveURL(/\/flashcards\?(?!.*\b(start|review)=)/);

  // A reload after closing starts nothing either: the link that is left names
  // the concept without `start`, which opens the set builder on it.
  await page.reload();
  await expect(page.getByTestId("flashcards-selection")).toContainText("1 concept", { timeout: 30_000 });
  await expect(page.getByText(/Card \d+ of \d+/)).toHaveCount(0);
  await expect(page).toHaveURL(/\/flashcards\?(?!.*\bstart=)/);

  // One generate call, three cards: nothing was started (or made) twice.
  expect(generateCalls).toHaveLength(1);
  expect(await recursionCards()).toBe(3);
});
