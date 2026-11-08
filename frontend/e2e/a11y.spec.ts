/**
 * The accessibility lane (learning-loop spec §13 A135): axe-core's WCAG 2.0 /
 * 2.1 level A and AA rules (support/a11y.ts) run against every student surface
 * in its key states, plus one admin page. Any violation fails the test; each
 * test scans all of its states before it fails (soft assertions), so one run
 * reports everything.
 *
 * Surfaces and states:
 *  - the shell's top-navigation layout, wide and on a phone with its menu open;
 *  - dashboard (and its courses key open), library (documents, a document's
 *    detail panel, the upload dialog), study (guides, a guide open, flashcards),
 *    notes, settings (every tab), another student's profile, quiz (the AI
 *    notice, home, the adjust dialog, a multiple-choice question, its checked
 *    answer, the ask panel, a written answer, results), the admin check-item
 *    queue and key audit — in both lanes;
 *  - the learning loop (default lane only, spec §11.4): the check-in question,
 *    the answer shown after a miss, the plan, a teaching turn, a check card
 *    with its worked-example hint, a refused hint, feedback after an answer, a
 *    multiple-choice check card, the wrap-up, the budget pause with the
 *    degraded-mode notes, the review queue (a flashcard, its answer, the
 *    rated result, a multiple-choice check) and the retention check (its entry,
 *    opened with nothing eligible);
 *  - the legacy tutor screen (kill-switch lane only).
 *
 * Determinism: function mode (agents/function_handlers_e2e.py) supplies every
 * model's text; scans run with reduced motion and wait for animations to end.
 * The seeded loop items are free-text only (db/seed_local_rich.py
 * SEED_LOOP_FORMATS), so the two multiple-choice cards are rendered from a
 * routed `/check/next` and `/review/next` answer carrying an `mc_reason` pose,
 * fulfilled in the browser (the server poses nothing): the scan checks their
 * markup, and nothing is submitted from them. The degraded-mode notes come from
 * the server's own `/start-session` answer with A128's flag added and a routed
 * `/probe/next` saying questions are being prepared (function mode never fails
 * a retrieval or drafts on a schedule).
 */
import type { Browser, Page, Route } from "@playwright/test";

import { expectAccessible } from "./support/a11y";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { learningParams } from "./support/params";
import { expectAskReply, STREAM_TIMEOUT } from "./support/quiz";
import { mintStorageState } from "./support/session";
import { USER_CAPPED, USER_LOOP } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role
const USER_SECOND = "rich-user-second";
/** The seeded struggling concept (db/seed_local_rich.py), as the quiz journeys use it. */
const QUIZ_NODE = "rich-node-cs-recursion";

/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_PROBE_PROMPT */
const LOOP_PROBE_PROMPT = "[e2e-loop] Check item: type the e2e grader's correct token to be marked correct.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_BODY */
const LOOP_HINT_BODY = "Reread the item and name the one thing it wants you to state.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_FEEDBACK_BODY */
const LOOP_FEEDBACK_BODY = "Look at which part of the item your answer addressed.";
/** A genuine attempt that never carries the correct token (learn-loop.spec.ts). */
const WORKING_ATTEMPT = "working: I think it is the value the item names";

const LOOP_TIMEOUT_MS = 240_000;
const QUIZ_TIMEOUT_MS = 180_000;
const GENERATE_TIMEOUT = 60_000;

/** An `mc_reason` pose for the routed multiple-choice cards (stored-order
 *  options, none marked correct — A22). */
const MC_OPTIONS = [
  { letter: "A", text: "It writes a value in base ten." },
  { letter: "B", text: "It writes a value in base two, one bit per place." },
  { letter: "C", text: "It stores a negative number by inverting and adding one." },
];
const MC_PROMPT = "[a11y] Which statement describes a binary number?";

test.use({ contextOptions: { reducedMotion: "reduce" } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
});

/** A second signed-in context (reduced motion, AI notice acknowledged). */
async function signIn(browser: Browser, userId: string, name: string) {
  const context = await browser.newContext({
    storageState: await mintStorageState(userId, name),
    reducedMotion: "reduce",
  });
  await context.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page: await context.newPage() };
}

/** Replace a JSON response with the server's own answer plus `extra`. */
async function withFields(route: Route, extra: Record<string, unknown>) {
  const response = await route.fetch();
  const json = await response.json();
  await route.fulfill({ response, json: { ...json, ...extra } });
}

test("dashboard", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByTestId("dashboard-plan")).toBeVisible();
  await expect(page.getByTestId("dashboard-courses-key-toggle")).toBeVisible();
  await expectAccessible(page, "dashboard");
  await page.getByTestId("dashboard-courses-key-toggle").click();
  await expect(page.getByTestId("dashboard-course-code").first()).toBeVisible();
  await expectAccessible(page, "dashboard: courses key open");
});

test("shell: the top navigation layout, wide and on a phone with its menu open", async ({ page }) => {
  // The other shell skin a student can pick (Settings → Preferences → Layout),
  // and the one every phone gets.
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_layout", "topnav");
  });
  await page.goto("/dashboard");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  // this layout's dashboard has no plan card; its greeting types itself out
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Good (morning|afternoon|evening), Rich/);
  await expectAccessible(page, "shell: top navigation");
  await page.setViewportSize({ width: 390, height: 844 });
  const menu = page.getByRole("button", { name: /^Navigation menu/ });
  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expectAccessible(page, "shell: phone, navigation menu open");
});

test("library", async ({ page }) => {
  await page.goto("/library");
  const doc = page.locator('[data-testid^="library-doc-"]').first();
  await expect(doc).toBeVisible();
  await expectAccessible(page, "library: documents");
  await doc.click();
  await expect(page.getByTestId("library-detail-close")).toBeVisible();
  await expectAccessible(page, "library: document detail");
  await page.getByTestId("library-detail-close").click();
  await page.getByTestId("library-upload").click();
  await expect(page.getByTestId("upload-modal")).toBeVisible();
  await expectAccessible(page, "library: upload dialog");
});

test("study and flashcards", async ({ page }) => {
  await page.goto("/study");
  const recent = page.getByRole("button", { name: /Midterm Exam/ });
  await expect(recent).toBeVisible();
  await expectAccessible(page, "study: guides");
  // The shared select (CustomSelect), open from the keyboard: the list takes
  // focus with an active option, and Escape hands focus back to its button.
  const coursePicker = page.locator('button[aria-haspopup="listbox"]').first();
  await coursePicker.focus();
  await page.keyboard.press("ArrowDown");
  const courses = page.getByRole("listbox", { name: "Course" });
  await expect(courses).toBeFocused();
  await expect(courses).toHaveAttribute("aria-activedescendant", /.+/);
  await expectAccessible(page, "study: course picker open");
  await page.keyboard.press("Escape");
  await expect(courses).toHaveCount(0);
  await expect(coursePicker).toBeFocused();
  await recent.click();
  await expect(page.getByText("Covers variables, control flow, and functions.")).toBeVisible();
  await expectAccessible(page, "study: guide open");
  await page.goto("/study?mode=cards");
  await expect(page.getByText("Flashcards", { exact: true }).first()).toBeVisible();
  if (!killSwitchLane) await expect(page.getByTestId("review-due-panel")).toBeVisible();
  await expectAccessible(page, "study: flashcards");
});

test("notes", async ({ page }) => {
  await page.goto("/notetaker");
  await expect(page.getByRole("textbox", { name: "Untitled note" })).toBeVisible();
  await expectAccessible(page, "notes");
});

test("settings and a profile", async ({ page }) => {
  await page.goto("/settings");
  // Each tab's content, once loaded (the form waits on the settings read).
  const loaded: Record<string, () => ReturnType<Page["getByText"]>> = {
    profile: () => page.getByRole("button", { name: /Sign out/ }),
    cosmetics: () => page.getByText("Cosmetics", { exact: true }),
    preferences: () => page.getByRole("button", { name: /^Layout\b/ }), // the layout select, named by its label
    notifications: () => page.getByTestId("settings-toggle-notification_email"),
    data: () => page.getByTestId("settings-analytics-toggle"),
  };
  for (const [tab, content] of Object.entries(loaded)) {
    await page.getByTestId(`settings-tab-${tab}`).click();
    await expect(content()).toBeVisible();
    if (tab === "data") await expect(content()).toBeEnabled();
    await expectAccessible(page, `settings: ${tab}`);
  }
  await page.goto(`/profile/${USER_SECOND}`);
  await expect(page.getByTestId("profile-add-friend").or(page.getByTestId("profile-friend-status"))).toBeVisible();
  await expectAccessible(page, "profile: another student");
});

test("quiz: notice, home, a multiple-choice question, its verdict, the ask panel and results", async ({ browser }) => {
  test.setTimeout(QUIZ_TIMEOUT_MS);
  // A browser that has never seen the AI notice: no acknowledgement here.
  const context = await browser.newContext({
    storageState: "e2e/.auth/storageState.json",
    reducedMotion: "reduce",
  });
  await context.addInitScript(() => {
    window.localStorage.setItem(
      "sapling_quiz_prefs",
      JSON.stringify({ count: 3, difficulty: "medium", feedback: "as-you-go" }),
    );
  });
  const page = await context.newPage();
  try {
    await page.goto(`/quiz?concept=${QUIZ_NODE}`);
    const notice = page.getByRole("dialog", { name: "Sapling uses AI" });
    await expect(notice).toBeVisible();
    await expectAccessible(page, "quiz: AI notice");
    await notice.getByRole("button", { name: "Got it" }).click();
    await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: 30_000 });
    await expectAccessible(page, "quiz: home");
    await page.getByTestId("quiz-adjust").click();
    await expect(page.getByTestId("quiz-adjust-dialog")).toBeVisible();
    await expectAccessible(page, "quiz: adjust dialog");
    await page.getByTestId("quiz-adjust-done").click();
    await expect(page.getByTestId("quiz-adjust-dialog")).toHaveCount(0);

    await page.getByTestId("quiz-start").click();
    await expect(page.getByTestId("quiz-answer-options")).toBeVisible({ timeout: GENERATE_TIMEOUT });
    await page.getByTestId("quiz-answer-option-A").click();
    await expectAccessible(page, "quiz: multiple-choice question");
    await page.getByTestId("quiz-submit-answer").click();
    await expect(page.getByTestId("quiz-review-verdict")).toBeVisible({ timeout: 30_000 });
    await expectAccessible(page, "quiz: answer checked");

    await page.getByTestId("quiz-ask").click();
    const sheet = page.getByTestId("quiz-ask-panel");
    await expect(sheet).toBeVisible();
    await expectAskReply(sheet, STREAM_TIMEOUT);
    await expectAccessible(page, "quiz: ask panel");
    await page.getByTestId("quiz-ask-panel-close").click();
    await expect(sheet).toHaveCount(0);

    for (let n = 2; n <= 3; n += 1) {
      await page.getByTestId("quiz-next").click();
      await expect(page.getByTestId("quiz-panel")).toContainText(`E2E deterministic question ${n}`, { timeout: 30_000 });
      await page.getByTestId("quiz-answer-option-A").click();
      await page.getByTestId("quiz-submit-answer").click();
      await expect(page.getByTestId("quiz-review-verdict")).toBeVisible({ timeout: 30_000 });
    }
    await page.getByTestId("quiz-next").click();
    await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: 30_000 });
    await expectAccessible(page, "quiz: results");
  } finally {
    await context.close();
  }
});

test("quiz: a written answer", async ({ page }) => {
  test.setTimeout(QUIZ_TIMEOUT_MS);
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "sapling_quiz_prefs",
      JSON.stringify({ count: 3, difficulty: "medium", feedback: "at-end", questionFormat: "mixed" }),
    );
  });
  await page.goto(`/quiz?concept=${QUIZ_NODE}`);
  await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("quiz-start").click();
  const written = page.getByTestId("quiz-written-answer");
  await expect(written).toBeVisible({ timeout: GENERATE_TIMEOUT });
  await written.fill("termination condition");
  await expectAccessible(page, "quiz: written answer");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 2", { timeout: 30_000 });
  await written.fill("50%");
  await expect(page.getByTestId("quiz-written-readback")).toContainText("Reads as 0.5");
  await expectAccessible(page, "quiz: numeric answer read back");
});

test("admin: check-item review queue and key audit", async ({ browser }) => {
  const { context, page } = await signIn(browser, USER_ADMIN, "Ada Admin");
  try {
    await page.goto("/admin/check-items");
    await expect(page.getByTestId("admin-items")).toBeVisible();
    await expect(page.getByTestId("admin-items-count").or(page.getByTestId("admin-items-empty"))).toBeVisible();
    await expectAccessible(page, "admin: check-item queue");
    await page.getByTestId("admin-items-tab-audit").click();
    await expect(page.getByTestId("admin-audit")).toBeVisible();
    await expectAccessible(page, "admin: key audit");
  } finally {
    await context.close();
  }
});

test("legacy tutor screen (kill switch)", async ({ page }) => {
  test.skip(!killSwitchLane, "kill-switch lane only: the loop replaces this screen by default");
  await page.goto("/learn");
  await expect(page.getByTestId("tutor-topic-picker")).toBeVisible();
  await expectAccessible(page, "legacy tutor: start");
  await page.getByRole("button", { name: /Recursion socratic/ }).click();
  await expect(page.getByTestId("tutor-input")).toBeVisible({ timeout: 30_000 });
  await expectAccessible(page, "legacy tutor: a resumed session");
});

/** Probe → plan, scanning the check-in question, an answer shown after a miss,
 *  and the plan. Easy items are answered right, harder ones missed, as the loop
 *  journey does (learn-loop.spec.ts::walkProbeAndPlan). */
async function walkCheckInAndPlan(page: Page, cap: number) {
  const phase = page.getByTestId("loop-phase");
  const probeItem = page.getByTestId("loop-probe-item");
  await expect(probeItem).toContainText(LOOP_PROBE_PROMPT);
  await expectAccessible(page, "learn loop: check-in question");
  let answered = 0;
  let referenceScanned = false;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < cap) {
    const qh = await probeItem.getAttribute("data-question-hash");
    const difficulty = Number(await probeItem.getAttribute("data-difficulty"));
    await page.getByTestId("loop-probe-input").fill(difficulty === 1 ? GRADER_CORRECT_TOKEN : WORKING_ATTEMPT);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    await expect
      .poll(async () => {
        if ((await phase.getAttribute("data-phase")) !== "probe") return true;
        if (!(await probeItem.isVisible())) return false;
        const now = await probeItem.getAttribute("data-question-hash");
        return (await page.getByTestId("loop-probe-reference").isVisible()) || (now !== null && now !== qh);
      })
      .toBe(true);
    if (await page.getByTestId("loop-probe-reference").isVisible()) {
      if (!referenceScanned) {
        await expectAccessible(page, "learn loop: check-in answer shown");
        referenceScanned = true;
      }
      await page.getByTestId("loop-probe-next").click();
      await expect
        .poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
          (await probeItem.getAttribute("data-question-hash")) !== qh)
        .toBe(true);
    }
  }
  expect(referenceScanned, "the check-in missed a harder item, so its answer was shown").toBe(true);
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await expectAccessible(page, "learn loop: plan");
  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
}

test("learning loop: check-in, plan, teaching, a check with hints, feedback, a multiple-choice check and the wrap-up", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await walkCheckInAndPlan(page, Number(P.PROBE_SESSION_CAP));
    const phase = page.getByTestId("loop-phase");

    await page.getByTestId("loop-teach-start").click();
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByTestId("loop-check-me")).toBeEnabled();
    await expectAccessible(page, "learn loop: teaching");

    // spec §13 A122: this novice's first check opens on its worked example (a hint).
    await page.getByTestId("loop-check-me").click();
    await expect(page.getByTestId("loop-check-prompt")).toContainText(LOOP_PROBE_PROMPT);
    await expect(page.getByTestId("loop-hint-reply")).toContainText(LOOP_HINT_BODY, { timeout: 30_000 });
    await expect(page.getByTestId("loop-hint-button")).toBeEnabled();
    await expectAccessible(page, "learn loop: check with a hint");
    await page.getByTestId("loop-hint-button").click();
    await expect(page.getByTestId("loop-hint-denied")).toBeVisible();
    await expectAccessible(page, "learn loop: hint refused");

    await page.getByTestId("loop-attempt-input").fill(`working: ${GRADER_CORRECT_TOKEN}`);
    await page.getByTestId("loop-attempt-submit").click();
    await expect(phase).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_BODY, { timeout: 30_000 });
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    await expectAccessible(page, "learn loop: feedback");

    // A multiple-choice card, from a routed pose (the seeded items are free
    // text). Fulfilled without reaching the server, so no item is posed there.
    await page.route("**/api/learn/loop/check/next", (route) =>
      route.fulfill({
        json: {
          phase: "check",
          check: { question_hash: "a11y-mc-pose", format: "mc_reason", difficulty: 1, prompt: MC_PROMPT, options: MC_OPTIONS },
        },
      }),
    );
    await page.getByTestId("loop-check-me").click();
    await expect(page.getByTestId("loop-attempt-option-B")).toBeVisible();
    await page.getByTestId("loop-attempt-option-B").click();
    await page.getByTestId("loop-check-confidence-fairly_sure").click();
    await expectAccessible(page, "learn loop: multiple-choice check");
    await page.unroute("**/api/learn/loop/check/next");

    await page.getByTestId("loop-close-button").click();
    await expect(phase).toHaveAttribute("data-phase", "close");
    await expect(page.getByTestId("loop-close-done")).toBeVisible();
    await expectAccessible(page, "learn loop: wrap-up");
  } finally {
    await context.close();
  }
});

test("learning loop: the budget pause and the degraded-mode notes", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  try {
    // spec §13 A128's notes, from the server's own answers with the flags set.
    await page.route("**/api/learn/loop/start-session", (route) => withFields(route, { materials_unavailable: true }));
    await page.route("**/api/learn/loop/probe/next", (route) =>
      route.fulfill({ json: { done: true, phase: "plan", no_check_items: true, preparing: true } }),
    );
    await page.goto("/learn");
    await expect(page.getByTestId("loop-budget-paused")).toBeVisible();
    await expect(page.getByTestId("loop-materials-unavailable")).toBeVisible();
    await expect(page.getByTestId("loop-preparing-items")).toBeVisible();
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "plan");
    await expectAccessible(page, "learn loop: paused, materials unavailable, preparing questions");
  } finally {
    await context.close();
  }
});

test("review queue: a flashcard, its answer, the rated result and a multiple-choice check", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  try {
    await page.goto("/study?mode=cards");
    await expect(page.getByTestId("review-item")).toBeVisible();
    await expectAccessible(page, "review: a flashcard");
    await page.getByTestId("review-flip").click();
    await expect(page.getByTestId("review-rate-3")).toBeVisible();
    await expectAccessible(page, "review: the flashcard's answer");
    await page.getByTestId("review-rate-3").click();
    await expect(page.getByTestId("review-hint")).toBeVisible();
    await expectAccessible(page, "review: rated");

    // A multiple-choice check, from a routed item (the seeded items are free
    // text). Fulfilled without reaching the server, so nothing is served there.
    await page.route("**/api/learn/loop/review/next*", (route) =>
      route.fulfill({
        json: {
          item: {
            kind: "check", id: "a11y-review-mc", cost_s: 60, sr: { stage: "acquire", correct: 0, target: 1 },
            concept_name: "Binary Numbers", format: "mc_reason", difficulty: 1, prompt: MC_PROMPT, options: MC_OPTIONS,
          },
          remaining_budget_s: 600,
          session_id: "a11y-review-session",
          retention_target: 0.9,
          due_total: 1,
          in_budget: 1,
        },
      }),
    );
    await page.getByTestId("review-next").click();
    await expect(page.getByTestId("review-option-B")).toBeVisible();
    await page.getByTestId("review-option-B").check();
    await page.getByTestId("review-confidence-sure").click();
    await expectAccessible(page, "review: a multiple-choice check");
  } finally {
    await context.close();
  }
});

test("retention check: opened with nothing eligible yet", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/study?mode=cards");
    await expect(page.getByTestId("retention-open")).toBeEnabled();
    await expectAccessible(page, "review: retention check entry");
    await page.getByTestId("retention-open").click();
    await expect(page.getByTestId("retention-empty")).toBeVisible();
    await expectAccessible(page, "review: retention check, none eligible");
  } finally {
    await context.close();
  }
});
