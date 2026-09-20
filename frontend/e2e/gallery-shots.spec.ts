/**
 * Product screenshots for the /gallery cards.
 *
 * Design: docs/superpowers/specs/2026-09-03-gallery-screenshots-design.md
 *
 * `/gallery` promises "every screen in Sapling, as it actually looks" and has
 * always rendered twelve empty tinted panels. This captures the twelve, from
 * the same deterministic stack the browser lane uses — seeded PRNG, clock
 * frozen at 2026-03-11T12:00:00Z, timezone pinned — so re-running produces
 * the same pixels rather than a fresh set of diffs.
 *
 * Gated on GALLERY_SHOTS_DIR exactly as quiz-integration.spec.ts's shot test
 * is gated on QUIZ_SHOTS: unset, the normal lane collects these and skips
 * them for nothing. `scripts/gallery-shots.sh` is what sets it.
 *
 * NOTE the import: `test` comes from @playwright/test directly, NOT from
 * support/fixtures.ts. That module's autouse `dbReset` fixture truncates and
 * re-seeds the rich dataset before every test, which would wipe the showcase
 * overlay (db/seed_showcase.py) out from under the run. Config-level
 * `use.storageState` still applies, so these are signed in as the seeded
 * student without any sign-in code here.
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { GALLERY_SHOTS } from "../src/lib/landing/companionContent";
import { FRONTEND_URL } from "./support/stack";

const OUT_DIR = process.env.GALLERY_SHOTS_DIR?.trim();

// 1440x900 is 16:10 — the aspect the gallery cards render at, so captures need
// no cropping.
test.use({ viewport: { width: 1440, height: 900 } });

/** The seeded struggling concept, from db/seed_local_rich.py. */
const NODE_RECURSION = "rich-node-cs-recursion";

/**
 * Acknowledge the AI-disclosure modal before every shot.
 *
 * DisclaimerModal.tsx is a fixed overlay a browser that has never dismissed it
 * gets on the AI surfaces, and it both photographs badly and swallows clicks —
 * the first capture run failed on /learn and /quiz because of it, the quiz one
 * with "<div role=dialog> intercepts pointer events". Applied globally rather
 * than per-recipe: it is unrelated chrome on every screen it appears on, and
 * a shot of it is never the shot we want. Same localStorage key the tutor and
 * quiz journeys use (support/quizStack.ts documents it as an app contract).
 */
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
});

/**
 * Everything a screen needs before it is worth photographing: the network
 * quiet, motion suppressed (the app animates on mount — `fadeUp`, the graph —
 * and a shot taken mid-animation is a shot of a half-faded screen), webfonts
 * resolved (Playfair and Spectral swap in late, so capturing early
 * photographs the fallback stack), and one beat to settle.
 */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.emulateMedia({ reducedMotion: "reduce" });
  // Park the cursor. A recipe that clicks leaves the pointer wherever it
  // landed, and hover state photographs: the first /learn capture came back
  // with a node tooltip stuck over the knowledge map, covering the legend.
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
}

/**
 * Per-slot recipes. These live here rather than in GALLERY_SHOTS because that
 * table is imported by a client component — Playwright steps in it would drag
 * test code into the browser bundle.
 *
 * A recipe's last act is an assertion that the screen is READY, not merely
 * loaded. A bare `goto` photographs skeletons.
 */
const RECIPES: Record<string, (page: Page) => Promise<void>> = {
  "shot-tree": async (page) => {
    await page.goto("/tree");
    // The SVG node groups are the thing being photographed; the a11y list
    // mirrors them 1:1 but renders offscreen (see graph.spec.ts).
    const container = page.getByTestId("graph-container");
    await expect(container).toBeVisible({ timeout: 30_000 });
    await expect(container.getByTestId("graph-node").first()).toBeVisible({
      timeout: 30_000,
    });
  },

  // /learn lands on "Start a session", not on a conversation. The seeded
  // sessions are in the sidebar, so open one — a tutor screenshot with no
  // tutoring in it is not a picture of the tutor.
  "shot-learn": async (page) => {
    await page.goto("/learn");
    await page.getByRole("button", { name: /Recursion socratic/ }).click();
    await expect(page.getByTestId("tutor-input")).toBeVisible({ timeout: 30_000 });
  },

  // The one shot that drives generation rather than viewing seeded state: a
  // quiz screen with no question on it is not a picture of the quiz.
  //
  // The length pref is pinned to the showcase handler's fixed three questions.
  // Left at the app default it asks for more, and the shortfall raises a
  // "Only 3 questions were ready for this concept" toast across the header —
  // true, and not what this card is meant to show. Same key the quiz journeys
  // use (support/quizStack.ts).
  "shot-quiz": async (page) => {
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "sapling_quiz_prefs",
        JSON.stringify({ count: 3, difficulty: "medium", feedback: "at-end" }),
      );
    });
    await page.goto(`/quiz?concept=${NODE_RECURSION}&from=tree&return=%2Ftree`);
    await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("quiz-start")).toBeEnabled();
    await page.getByTestId("quiz-start").click();
    await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: 60_000 });
  },

  // The two /study shots are one route in two modes — `/flashcards` is only a
  // redirect to `?mode=cards`, and Study.tsx reads that param. Going straight
  // to the URL beats clicking the toggle: no animation to wait out.
  "shot-study": async (page) => {
    await page.goto("/study?mode=cards");
    await expect(page.getByText("Flashcards", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
  },

  "shot-guide": async (page) => {
    await page.goto("/study");
    await expect(page.getByText("Study Guide", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
  },

  // The notetaker has no h1 — it opens straight into the editor with the most
  // recent note loaded, so the title field is what "ready" looks like.
  "shot-notetaker": async (page) => {
    await page.goto("/notetaker");
    await expect(page.getByRole("textbox", { name: "Untitled note" })).toBeVisible({
      timeout: 30_000,
    });
  },

  "shot-library": async (page) => {
    await page.goto("/library");
    await expect(page.getByTestId("library-search")).toBeVisible({ timeout: 30_000 });
  },

  // /social opens on whichever room comes first, which is the lounge and its
  // three stranded lines. The CS101 study group is both fuller (the showcase
  // overlay adds four messages to it) and the better room to photograph — a
  // study tool should show people studying.
  "shot-social": async (page) => {
    await page.goto("/social");
    await expect(page.getByTestId("social-chat-messages")).toBeVisible({
      timeout: 30_000,
    });
    await page.getByText("CS101 Study Group", { exact: true }).click();
    await expect(page.getByTestId("social-room-name")).toContainText("CS101", {
      timeout: 15_000,
    });
  },

  "shot-achievements": async (page) => {
    await page.goto("/achievements");
    await expect(page.getByTestId("gamification-hero")).toBeVisible({
      timeout: 30_000,
    });
  },

  "shot-calendar": async (page) => {
    await page.goto("/calendar");
    await expect(page.getByTestId("calendar-skeleton")).toHaveCount(0, {
      timeout: 30_000,
    });
  },

  "shot-gradebook": async (page) => {
    await page.goto("/gradebook");
    await expect(page.getByRole("grid", { name: "Courses" })).toBeVisible({
      timeout: 30_000,
    });
  },

  "shot-planner": async (page) => {
    await page.goto("/course-planner");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 30_000,
    });
  },
};

/**
 * The contract between this file and the content table. Two lists that must
 * correspond, with one of them saying so — the same discipline #601 applied to
 * the journal, so that adding a thirteenth card fails loudly instead of
 * producing twelve screenshots and no complaint.
 *
 * Deliberately NOT gated on GALLERY_SHOTS_DIR: it costs nothing and it is
 * worth failing in the normal lane, where someone adding a card will see it.
 */
test("every gallery slot has a capture recipe, and every recipe a slot", () => {
  const slots = GALLERY_SHOTS.map((s) => s.slot).sort();
  const recipes = Object.keys(RECIPES).sort();
  expect(recipes).toEqual(slots);
});

for (const shot of GALLERY_SHOTS) {
  test(`gallery shot — ${shot.slot} (${shot.route})`, async ({ page }) => {
    test.skip(!OUT_DIR, "set GALLERY_SHOTS_DIR=<output dir> to capture");
    test.setTimeout(120_000);

    // A screenshot tool drives a signed-in session through real product
    // surfaces. Pointing it anywhere but local would photograph real data.
    expect(
      FRONTEND_URL.includes("localhost") || FRONTEND_URL.includes("127.0.0.1"),
      `REFUSING: FRONTEND_URL ${FRONTEND_URL} is not local`,
    ).toBe(true);

    await RECIPES[shot.slot](page);
    await settle(page);

    fs.mkdirSync(OUT_DIR!, { recursive: true });
    await page.screenshot({
      path: path.join(OUT_DIR!, `${shot.slot}.png`),
      fullPage: false,
    });
  });
}
