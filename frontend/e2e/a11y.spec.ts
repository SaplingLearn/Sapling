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
 *    details dialog, the upload menu), study (the Study hub with the loop's
 *    due reviews, its course picker open, the deadlines pop-up, the dates
 *    editor, a concept's actions menu, the daily goal editor; the Study Guides
 *    home, the New study guide dialog with its class list open and with a
 *    class chosen, a guide open; flashcards), notes, settings (every tab),
 *    another student's profile, quiz (the AI
 *    notice, home, the adjust dialog, a multiple-choice question, its checked
 *    answer, the ask panel, a written answer, results; with the quiz's
 *    learning-system flags on for the student (spec §13 A143–A147), home with
 *    the plan's reason and results with the learning block), the admin
 *    check-item queue and key audit — in both lanes;
 *  - the learning loop (default lane only, spec §11.4): the check-in question,
 *    the answer shown after a miss, the plan, a teaching turn, a check card
 *    with its worked-example hint, a refused hint, feedback after an answer, a
 *    multiple-choice check card, the wrap-up, the budget pause with the
 *    degraded-mode notes, the review queue (a flashcard, its answer, the
 *    rated result, a multiple-choice check) and the retention check (its entry,
 *    opened with nothing eligible); with `segment_prequestion` and
 *    `self_explanation_prompts` on for the student (spec §13 A138, A139), a
 *    segment's ungraded guess (multiple choice, after the check-in) and the
 *    worked example's "why" prompt;
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
import { queryRaw, seedTeachPromptItems, setUserFlag } from "./support/db";
import { expect, test } from "./support/fixtures";
import { loopOffLane } from "./support/lane";
import { learningParams } from "./support/params";
import { showsAnotherItem } from "./support/probe";
import { expectAskReply, STREAM_TIMEOUT } from "./support/quiz";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE, USER_CAPPED, USER_LOOP } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role
const USER_SECOND = "rich-user-second";
/** The seeded struggling concept (db/seed_local_rich.py), as the quiz journeys use it. */
const QUIZ_NODE = "rich-node-cs-recursion";
/** The active student's first course, CS101, and the one term whose CS101
 *  offering has documents (db/seed_local_rich.py; study-guide.spec.ts). */
const COURSE_CS = "rich-course-cs101";
const GUIDE_TERM = "Fall 2025";
/** lib/useActiveSemester.ts's storage key: the term the Study pages scope to. */
const SEMESTER_KEY = "sapling_active_semester";
/** The one seeded study guide (db/seed_local_rich.py; study-guide.spec.ts). */
const SEEDED_GUIDE = { id: "rich-guide-cs-f25-mid", title: "Variables, control flow and functions" };

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
const STUDY_TIMEOUT_MS = 180_000;
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
  // #803: the course key is always open (it has no toggle), so the one scan
  // covers it, once its rows are in.
  await expect(page.getByTestId("dashboard-courses-key")).toBeVisible();
  await expect(page.getByTestId("dashboard-course-code").first()).toBeVisible();
  await expectAccessible(page, "dashboard");
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
  // v2 (#717): a document's details are the dialog its "⋯" opens, with the
  // next-steps links (W8.1) inside it.
  await doc.getByRole("button", { name: "Details and actions" }).click();
  await expect(page.getByTestId("library-doc-menu")).toBeVisible();
  await expectAccessible(page, "library: document details");
  await page.mouse.click(5, 5); // the dialog's scrim
  await expect(page.getByTestId("library-doc-menu")).toBeHidden();
  // The Upload button opens a menu (the picker and the uploader's dialog sit
  // behind a native file chooser).
  await page.getByTestId("library-upload").click();
  await expect(page.getByRole("menu")).toBeVisible();
  await expectAccessible(page, "library: upload menu");
});

/**
 * The Study hub (components/study/StudyHub.tsx) on the student's first course,
 * CS101, with the loop's due queue above it (screens/Study.tsx), and each
 * panel it opens. Its exam tabs and its course field are checked from the
 * keyboard on the way.
 */
async function scanStudyHub(page: Page) {
  await page.goto("/study");
  await expect(page.getByTestId("readiness-pct")).toHaveText(/^\d+%$/, { timeout: 30_000 });
  await expect(page.getByRole("region", { name: "Roadmap" }).getByTestId(`tile-${QUIZ_NODE}`)).toBeVisible();
  if (!loopOffLane) await expect(page.getByTestId("review-due-panel")).toBeVisible();
  await expectAccessible(page, "study: hub with due reviews");

  // The course field (study/CoursePicker.tsx, the page's only listbox
  // trigger), opened from the keyboard; Escape closes it and focus stays on it.
  const coursePicker = page.locator('button[aria-haspopup="listbox"]');
  await expect(coursePicker).toContainText("CS101");
  await coursePicker.focus();
  await page.keyboard.press("Enter");
  const courses = page.getByRole("listbox", { name: "Courses" });
  await expect(courses).toBeVisible();
  await expectAccessible(page, "study: course picker open");
  await page.keyboard.press("Escape");
  await expect(courses).toHaveCount(0);
  await expect(coursePicker).toBeFocused();

  // The deadlines pop-up (the bell), and from it the dates editor.
  await page.getByRole("button", { name: /^Upcoming deadlines,/ }).click();
  const deadlines = page.getByRole("dialog", { name: "Upcoming deadlines" });
  await expect(deadlines).toBeVisible();
  await expectAccessible(page, "study: upcoming deadlines");
  await deadlines.getByRole("button", { name: "Manage Dates" }).click();
  const dates = page.getByRole("dialog", { name: "Exams and deadlines" });
  await expect(dates).toBeVisible();
  await expectAccessible(page, "study: exams and deadlines editor");
  await dates.getByRole("button", { name: "Cancel" }).click();
  await expect(dates).toHaveCount(0);

  // A concept's "..." menu. Opening it selects the concept, so the roadmap
  // highlights what it rests on and unlocks, and dims the rest.
  await page.getByTestId(`tile-actions-${QUIZ_NODE}`).click();
  const actions = page.getByRole("menu", { name: "Recursion actions" });
  await expect(actions).toBeVisible();
  await expectAccessible(page, "study: a concept's actions");
  await page.keyboard.press("Escape");
  await expect(actions).toHaveCount(0);

  // The daily goal's editor: its presets, a radio group.
  const goal = page.getByTestId("daily-goal");
  await goal.getByRole("button", { name: /^Daily goal: \d+ minutes\. Change daily goal$/ }).click();
  const presets = goal.getByRole("radiogroup", { name: "Daily goal, minutes a day" });
  await expect(presets).toBeVisible();
  await expectAccessible(page, "study: daily goal editor");
  await page.keyboard.press("Escape");
  await expect(presets).toHaveCount(0);

  // The exam tabs: the selected tab is the row's one Tab stop, and Home and
  // End (as the arrows do) select the tab they land on and take focus there.
  const exams = page.getByRole("tablist", { name: "Exams" });
  const tabs = exams.getByRole("tab");
  await exams.getByRole("tab", { selected: true }).focus();
  await page.keyboard.press("Home");
  await expect(tabs.first()).toBeFocused();
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
  await expect(tabs.first()).toHaveAttribute("tabindex", "0");
  await page.keyboard.press("End");
  await expect(tabs.last()).toBeFocused();
  await expect(tabs.last()).toHaveAttribute("aria-selected", "true");
}

/**
 * Study Guides (/study/guide, the hub's Study Guide tool): the home, its New
 * study guide dialog and the seeded guide open. Under the default "All
 * semesters" CS101 is its latest offering, which has no documents, so this
 * runs with the term whose offering has them (as study-guide.spec.ts does) and
 * puts the default back after.
 */
async function scanStudyGuides(page: Page) {
  await page.evaluate(([key, term]) => window.localStorage.setItem(key, term), [SEMESTER_KEY, GUIDE_TERM]);
  await page.goto("/study/guide");
  const seededCard = page.getByTestId(`guides-card-${SEEDED_GUIDE.id}`);
  await expect(seededCard).toBeVisible({ timeout: 20_000 });
  await expectAccessible(page, "study: guides");

  await page.getByTestId("guides-new").click();
  const dialog = page.getByTestId("guide-new-dialog");
  await expect(dialog).toBeVisible();
  const classSelect = page.getByTestId("guide-new-class");
  await expect(classSelect).toBeEnabled();
  await expectAccessible(page, "study: new guide dialog");
  // The shared select (CustomSelect), open from the keyboard: the list takes
  // focus with an active option, and Escape hands focus back to its button
  // (and closes only the list, not the dialog around it).
  await classSelect.focus();
  await page.keyboard.press("ArrowDown");
  const classes = page.getByRole("listbox", { name: "Class" });
  await expect(classes).toBeFocused();
  await expect(classes).toHaveAttribute("aria-activedescendant", /.+/);
  await expectAccessible(page, "study: new guide, class list open");
  await page.keyboard.press("Escape");
  await expect(classes).toHaveCount(0);
  await expect(classSelect).toBeFocused();
  await expect(dialog).toBeVisible();
  // A class and the whole course: its materials and the planned outline.
  await classSelect.click();
  await page.getByTestId(`guide-new-class-option-${COURSE_CS}`).click();
  await page.getByTestId("guide-new-scope").click();
  await page.getByTestId("guide-new-scope-option-course").click();
  await expect(page.getByTestId("guide-new-outline-section-0")).toBeVisible();
  await expect(page.getByTestId("guide-new-outline")).toHaveAttribute("aria-busy", "false");
  await expectAccessible(page, "study: new guide, a class chosen");
  await page.getByTestId("guide-new-cancel").click();
  await expect(dialog).toHaveCount(0);

  await seededCard.click();
  await expect(page.getByTestId("guide-title")).toHaveText(SEEDED_GUIDE.title, { timeout: 20_000 });
  await expect(page.getByTestId("guide-generating")).toHaveCount(0);
  await expectAccessible(page, "study: guide open");
  await page.evaluate((key) => window.localStorage.removeItem(key), SEMESTER_KEY);
}

test("study and flashcards", async ({ page }) => {
  // A dozen scans over four pages: more than the default minute.
  test.setTimeout(STUDY_TIMEOUT_MS);
  await scanStudyHub(page);
  await scanStudyGuides(page);
  // The flashcards are their own page (/flashcards).
  await page.goto("/flashcards");
  await expect(page.getByText("Flashcards", { exact: true }).first()).toBeVisible();
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

test("quiz, learning system on: home with the plan's reason, results with the learning block", async ({ page }) => {
  // #884: the quiz learning flags need the learning loop, which is off in these lanes
  test.skip(loopOffLane, "the quiz learning flags need the learning loop: default lane only");
  test.setTimeout(QUIZ_TIMEOUT_MS);
  for (const key of ["quiz_concept_plan", "quiz_planned_questions", "quiz_item_gates", "quiz_results_routing"]) {
    await setUserFlag(key, USER_ACTIVE, "on");
  }
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "sapling_quiz_prefs",
      JSON.stringify({ count: 3, difficulty: "adaptive", feedback: "at-end" }),
    );
  });
  await page.goto("/quiz");
  await expect(page.getByTestId("quiz-plan-reason")).toBeVisible({ timeout: 30_000 });
  await expectAccessible(page, "quiz: home with the plan's reason");

  await page.goto(`/quiz?concept=${QUIZ_NODE}`);
  await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("quiz-start").click();
  // The planned questions (function_handlers_e2e.py::_e2e_planned), keyed B, C, A.
  for (const [i, label] of ["B", "C", "A"].entries()) {
    await expect(page.getByTestId("quiz-panel")).toContainText(`E2E planned question ${i + 1} `, {
      timeout: GENERATE_TIMEOUT,
    });
    await page.getByTestId(`quiz-answer-option-${label}`).click();
    await page.getByTestId("quiz-submit-answer").click();
  }
  await expect(page.getByTestId("quiz-results-learning")).toBeVisible({ timeout: 30_000 });
  await expectAccessible(page, "quiz: results with the learning block");
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

test("legacy tutor screen (loop off)", async ({ page }) => {
  test.skip(!loopOffLane, "loop-off lanes only: the loop replaces this screen by default");
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
async function walkCheckInAndPlan(page: Page, cap: number, { approve = true }: { approve?: boolean } = {}) {
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
        return (await page.getByTestId("loop-probe-reference").isVisible()) || (await showsAnotherItem(probeItem, qh));
      })
      .toBe(true);
    if (await page.getByTestId("loop-probe-reference").isVisible()) {
      if (!referenceScanned) {
        await expectAccessible(page, "learn loop: check-in answer shown");
        referenceScanned = true;
      }
      await page.getByTestId("loop-probe-next").click();
      await expect
        .poll(async () => (await phase.getAttribute("data-phase")) !== "probe" || (await showsAnotherItem(probeItem, qh)))
        .toBe(true);
    }
  }
  expect(referenceScanned, "the check-in missed a harder item, so its answer was shown").toBe(true);
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await expectAccessible(page, "learn loop: plan");
  if (!approve) return;
  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
}

test("learning loop: check-in, plan, teaching, a check with hints, feedback, a multiple-choice check and the wrap-up", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    // Wireframe T1: the Tutor home, before anything starts
    await expect(page.getByTestId("tutor-home")).toBeVisible();
    await expectAccessible(page, "learn loop: tutor home");
    await page.getByTestId("loop-start-guided").click();
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
    // Wireframes T2 and T3: a course page and every session, from the tutor sidebar
    await page.locator('[data-testid^="tutor-course-"]').first().click();
    await expect(page.getByTestId("tutor-course-page")).toBeVisible();
    await expectAccessible(page, "learn loop: course page");
    await page.getByTestId("tutor-view-all").click();
    await expect(page.getByTestId("tutor-all-sessions")).toBeVisible();
    await expectAccessible(page, "learn loop: all sessions");
  } finally {
    await context.close();
  }
});

// Tutor redesign phase 4: the rebuilt surfaces are student surfaces too (spec
// §13 A135), scanned in their own states with their flags on for this student.
test("learning loop: the rebuilt New session, plan, session panel, hint ladder, verdict, wrap-up and course page (new_session_v2, plan_v2, session_v2, hint_ladder, verdict_v2, wrapup_v2, course_page_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  await setUserFlag("hint_ladder", USER_LOOP, "on");
  await setUserFlag("verdict_v2", USER_LOOP, "on");
  await setUserFlag("wrapup_v2", USER_LOOP, "on");
  await setUserFlag("plan_v2", USER_LOOP, "on");
  await setUserFlag("new_session_v2", USER_LOOP, "on");
  await setUserFlag("session_v2", USER_LOOP, "on");
  await setUserFlag("course_page_v2", USER_LOOP, "on");
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await expect(page.getByTestId("tutor-new-session-v2")).toBeVisible();
    await expect(page.getByRole("heading", { name: "What are we working on?" })).toBeFocused();
    await expectAccessible(page, "learn loop: the rebuilt New session");
    // the whole-course session is picked first, as the old home's one CTA
    await expect(page.getByTestId("loop-start-guided")).toHaveAttribute("data-intent", "course");
    await page.getByTestId("loop-start-guided").click();
    // the walker scans the plan it lands on: here the rebuilt one
    await walkCheckInAndPlan(page, Number(P.PROBE_SESSION_CAP), { approve: false });
    await expect(page.getByTestId("loop-plan-v2")).toBeVisible();
    await expect(page.getByTestId("loop-plan-intro")).toBeFocused();
    await expect(page.getByTestId("loop-set-goal")).toHaveCount(1); // Change goal, in the plan
    const phase = page.getByTestId("loop-phase");
    await page.getByTestId("loop-plan-approve").click();
    await expect(phase).toHaveAttribute("data-phase", "teach");
    await page.getByTestId("loop-teach-start").click();
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    // the rebuilt panel: one list, each concept's level in its row; Review in the sidebar
    await expect(page.getByTestId("tutor-panel-v2")).toBeVisible();
    await expect(page.locator("[data-testid^='tutor-panel-concept-'][aria-current='step']")).toHaveCount(1);
    await expect(page.getByTestId("tutor-map-key")).toHaveCount(0);
    await expectAccessible(page, "learn loop: the rebuilt session panel");

    // spec §13 A122: the first check opens on its worked example: the ladder's first step.
    await page.getByTestId("loop-check-me").click();
    await expect(page.getByTestId("loop-hint-ladder")).toContainText(LOOP_HINT_BODY, { timeout: 30_000 });
    await expect(page.getByTestId("loop-hint-reply")).toHaveAttribute("data-rung", /^[4-6]$/);
    await expect(page.getByTestId("loop-hint-cost")).toContainText("Worked steps: no credit");
    await expectAccessible(page, "learn loop: the hint ladder");
    await page.getByTestId("loop-hint-button").click();
    await expect(page.getByTestId("loop-hint-denied")).toBeVisible();
    await expectAccessible(page, "learn loop: the hint ladder, a step refused");

    await page.getByTestId("loop-attempt-input").fill(`working: ${GRADER_CORRECT_TOKEN}`);
    await page.getByTestId("loop-attempt-submit").click();
    await expect(phase).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    const verdict = page.getByTestId("loop-verdict");
    await expect(verdict).toBeVisible();
    await expect(verdict).not.toContainText("Not yet"); // the rebuilt card's words
    await expectAccessible(page, "learn loop: the rebuilt verdict");

    await page.getByTestId("loop-close-button").click();
    await expect(phase).toHaveAttribute("data-phase", "close");
    await expect(page.getByTestId("loop-wrapup-v2")).toBeVisible();
    await expect(page.getByTestId("loop-close-headline")).toBeFocused();
    await expectAccessible(page, "learn loop: the rebuilt wrap-up");

    // the course page, from the tutor sidebar
    await page.locator('[data-testid^="tutor-course-"]').first().click();
    await expect(page.getByTestId("tutor-course-v2")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ready to learn" })).toBeFocused();
    await expectAccessible(page, "learn loop: the rebuilt course page");
  } finally {
    await context.close();
  }
});

// Milestones in the Tutor (`milestones`): the sidebar's countdown, a
// milestone's page and New session's "Prepare for <exam>". The seed links no
// topic to an exam (its checklist content is encrypted at rest), so the exam
// and its links are the server's own answers with one routed in: the scans
// check the markup, and nothing is written.
test("learning loop: milestones in the Tutor (milestones, course_page_v2, new_session_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  for (const flag of ["milestones", "course_page_v2", "new_session_v2"]) await setUserFlag(flag, USER_LOOP, "on");
  const nodes = (await queryRaw(
    `SELECT id, course_id FROM graph_nodes WHERE user_id = $1 AND course_id IS NOT NULL ORDER BY id`,
    [USER_LOOP],
  )) as { id: string; course_id: string }[];
  expect(nodes.length, "the loop student has concepts").toBeGreaterThan(0);
  const courseId = nodes[0].course_id;
  const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);
  const exam = { id: "a11y-midterm", user_id: USER_LOOP, title: "Midterm 2", due_date: inDays(13), assignment_type: "exam", course_id: courseId };
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.route(`**/api/calendar/all/**`, (route) => route.fulfill({ json: { assignments: [exam] } }));
    await page.route(`**/api/calendar/upcoming/**`, (route) => route.fulfill({ json: { assignments: [exam] } }));
    await page.route(`**/api/topic-checklist/**/courses/**`, (route) => route.fulfill({ json: {
      course_id: courseId, semester: "", generated_at: null, needs_refresh: false, assessments: [], warnings: [], review_after_days: 7,
      topics: nodes.filter((n) => n.course_id === courseId).map((n, i) => ({
        id: `a11y-topic-${i}`, name: n.id, description: "", importance: 0.5, parent_id: null, prerequisite_ids: [], prerequisite_gaps: [],
        status: "not_started", checked: false, mastery_score: null, last_studied_at: null, review_reasons: [], priority: "normal",
        assessments: [], assessment_ids: [exam.id], sources: [], node_id: n.id,
      })),
    } }));
    await page.goto("/learn");
    // New session offers the exam first
    await expect(page.getByTestId("tutor-new-intent-prepare")).toBeVisible();
    await expect(page.getByTestId("loop-start-guided")).toHaveAttribute("data-intent", "prepare");
    await expectAccessible(page, "milestones: New session's Prepare for the exam");
    // the sidebar's countdown opens the milestone's page
    const row = page.getByTestId(`tutor-milestone-${exam.id}`);
    await expect(row).toContainText("13 days");
    await row.click();
    await expect(page.getByTestId("tutor-milestone")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Midterm 2 in 13 days" })).toBeFocused();
    await expect(page.getByTestId("tutor-milestone-prepare")).toBeEnabled();
    await expectAccessible(page, "milestones: a milestone's page");
    // back on the course page, Coming up says how ready
    await page.getByTestId("tutor-milestone-back").click();
    await expect(page.getByTestId(`tutor-course-due-ready-${exam.id}`)).toContainText("ready");
    await expectAccessible(page, "milestones: the course page's Coming up");
  } finally {
    await context.close();
  }
});

// Just ask a question (`just_ask`): an ungraded chat from New session. It
// starts teaching at once on the server's own just_ask session (no check-in,
// no Check me), and the tutor answers the student's first message.
test("learning loop: Just ask a question, an ungraded chat (just_ask, new_session_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  for (const flag of ["just_ask", "new_session_v2"]) await setUserFlag(flag, USER_LOOP, "on");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await page.getByRole("radio", { name: /Just ask a question/ }).check();
    await expect(page.getByTestId("loop-start-guided")).toHaveText("Start chatting");
    await page.getByTestId("loop-start-guided").click();
    const phase = page.getByTestId("loop-phase");
    await expect(phase).toHaveAttribute("data-phase", "teach");
    await expect(page.getByTestId("tutor-messages")).toContainText("Nothing here is graded.");
    await expect(page.getByTestId("loop-check-me")).toHaveCount(0);
    await expect(page.getByTestId("loop-probe-item")).toHaveCount(0);
    await page.getByTestId("tutor-input").fill("What is a bit?");
    await page.getByTestId("tutor-send").click();
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByTestId("tutor-messages")).toContainText("What is a bit?");
    await expect(page.getByTestId("loop-check-me")).toHaveCount(0); // still nothing to grade
    await expectAccessible(page, "just ask: an ungraded chat");
  } finally {
    await context.close();
  }
});

// Saved (`saved_items`): Save under a tutor reply, then the session panel's
// Saved tab lists it. A just-ask session is the shortest way to a real reply.
test("learning loop: saving a tutor reply and the Saved tab (saved_items, session_v2, just_ask on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  for (const flag of ["saved_items", "session_v2", "just_ask", "new_session_v2"]) await setUserFlag(flag, USER_LOOP, "on");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await page.getByRole("radio", { name: /Just ask a question/ }).check();
    await page.getByTestId("loop-start-guided").click();
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "teach");
    await page.getByTestId("tutor-input").fill("What is a bit?");
    await page.getByTestId("tutor-send").click();
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    const save = page.getByTestId("tutor-save-reply").last();
    await expect(save).toHaveText("Save");
    await save.click();
    await expect(save).toHaveText("Saved");
    const tab = page.getByTestId("tutor-panel-tab-saved");
    await expect(tab).toHaveText("Saved (1)");
    await tab.click();
    await expect(page.getByTestId("tutor-saved-list").getByRole("listitem")).toHaveCount(1);
    await expectAccessible(page, "saved: the session panel's Saved tab");
    const rows = (await queryRaw("SELECT title, content FROM tutor_saved_items WHERE user_id = $1", [USER_LOOP])) as { title: string; content: string }[];
    expect(rows).toHaveLength(1);
    expect(rows[0].content).not.toContain("bit"); // sealed at rest
  } finally {
    await context.close();
  }
});

// Course setup (`course_setup`, from the rebuilt course page): Skip the upload
// (the upload's pipeline is the gradebook flow's, covered elsewhere), review
// the course's dates and concepts, add and remove a date row, untick a
// concept nobody has started, Confirm. The concept is a throwaway node, so
// the seeded graph the other journeys read is untouched; the backend records
// it as excluded and deletes it.
test("learning loop: course setup, reviewing dates and unticking a concept (course_setup, course_page_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  for (const flag of ["course_setup", "course_page_v2"]) await setUserFlag(flag, USER_LOOP, "on");
  const [{ course_id: courseId }] = (await queryRaw(
    `SELECT course_id FROM graph_nodes WHERE user_id = $1 AND course_id IS NOT NULL ORDER BY id LIMIT 1`,
    [USER_LOOP],
  )) as { course_id: string }[];
  const nodeId = "a11y-setup-node";
  await queryRaw(`DELETE FROM course_concept_exclusions WHERE user_id = $1 AND concept_key = 'setup probe concept'`, [USER_LOOP]);
  await queryRaw(
    `INSERT INTO graph_nodes (id, user_id, course_id, concept_name, mastery_score) VALUES ($1, $2, $3, 'Setup probe concept', 0)
     ON CONFLICT DO NOTHING`,
    [nodeId, USER_LOOP, courseId],
  );
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await page.getByTestId(`tutor-course-${courseId}`).click();
    await page.getByTestId("tutor-course-setup").click();
    const setup = page.getByTestId("tutor-setup");
    await expect(setup).toHaveAttribute("data-step", "syllabus");
    await expect(page.getByRole("heading", { level: 2, name: /^Upload your .* syllabus$/ })).toBeFocused();
    await expectAccessible(page, "course setup: the syllabus step");
    await page.getByTestId("tutor-setup-skip").click();
    await expect(setup).toHaveAttribute("data-step", "review");
    await expect(page.getByRole("heading", { level: 2, name: /^Review / })).toBeFocused();
    await page.getByTestId("tutor-setup-add-date").click();
    await expect(page.getByRole("textbox", { name: "Name", exact: true })).toBeFocused();
    await page.keyboard.type("Quiz 9");
    const chip = page.getByTestId(`tutor-setup-concept-${nodeId}`);
    await expect(chip.getByRole("checkbox")).toBeChecked();
    await expectAccessible(page, "course setup: the review");
    // Remove the new row again (nothing to clean up on the calendar); focus moves to Add a date.
    await page.getByRole("button", { name: "Remove Quiz 9" }).click();
    await expect(page.getByTestId("tutor-setup-add-date")).toBeFocused();
    await chip.getByRole("checkbox").uncheck();
    await page.getByTestId("tutor-setup-confirm").click();
    await expect(setup).toHaveAttribute("data-step", "done");
    await expect(page.getByRole("heading", { level: 2, name: / is set up$/ })).toBeFocused();
    await expectAccessible(page, "course setup: done");
    expect(await queryRaw(`SELECT id FROM graph_nodes WHERE id = $1`, [nodeId])).toHaveLength(0);
    const excluded = (await queryRaw(
      `SELECT course_id, concept_key FROM course_concept_exclusions WHERE user_id = $1`, [USER_LOOP],
    )) as { course_id: string; concept_key: string }[];
    expect(excluded).toContainEqual({ course_id: courseId, concept_key: "setup probe concept" });
    await page.getByTestId("tutor-setup-start").click();
    await expect(page.getByTestId("loop-phase")).toBeVisible();
  } finally {
    await context.close();
    await queryRaw(`DELETE FROM course_concept_exclusions WHERE user_id = $1 AND concept_key = 'setup probe concept'`, [USER_LOOP]);
    await queryRaw(`DELETE FROM graph_nodes WHERE id = $1`, [nodeId]);
  }
});

// The redesigned calendar (`calendar_v2`, with `milestones` for an exam's
// Prepare): Agenda, an item opened, Month, Week, Semester, the empty state and
// the phone layout, each scanned. The dates are the design boards' own (the
// frozen test clock is Mar 11 2026), routed so no seeded row changes; an edit
// is routed too.
test("calendar redesign: every view, an item opened, empty and phone (calendar_v2, milestones on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  for (const flag of ["calendar_v2", "milestones"]) await setUserFlag(flag, USER_LOOP, "on");
  const [{ course_id: courseId }] = (await queryRaw(
    `SELECT o.course_id FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id WHERE e.user_id = $1 ORDER BY o.course_id LIMIT 1`,
    [USER_LOOP],
  )) as { course_id: string }[];
  const row = (id: string, title: string, due: string, type: string) =>
    ({ id, user_id: USER_LOOP, title, due_date: due, assignment_type: type, course_id: courseId, notes: "" });
  const dates = [
    row("cal-mid1", "Midterm Exam", "2026-03-02", "exam"), row("cal-hw7", "HW 7", "2026-03-12", "homework"),
    row("cal-q4", "Quiz 4", "2026-03-13", "quiz"), row("cal-mid2", "Midterm 2", "2026-03-20", "exam"),
    row("cal-mid3", "Midterm", "2026-03-30", "exam"), row("cal-prop", "Project proposal", "2026-03-31", "homework"),
    row("cal-prac", "Lab practical", "2026-04-01", "exam"),
  ];
  let served: object[] = dates;
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.route(/\/api\/calendar\/all\//, (route) => route.fulfill({ json: { assignments: served } }));
    await page.route(/\/api\/calendar\/assignments\//, (route) => route.fulfill({ json: { updated: true, deleted: true } }));
    await page.goto("/calendar");
    const cal = page.getByTestId("calendar-v2");
    await expect(cal).toHaveAttribute("data-view", "agenda");
    await expect(page.getByTestId("calendar-item-cal-hw7")).toContainText("Tomorrow");
    await expect(page.getByTestId("calendar-prepare-cal-mid2")).toHaveAttribute("href", `/learn?course=${courseId}&milestone=cal-mid2`);
    await expectAccessible(page, "calendar: agenda");

    const title = page.getByTestId("calendar-item-cal-mid2").getByRole("button", { name: /Midterm 2/ });
    await title.click();
    await expect(page.getByRole("heading", { level: 2, name: "Midterm 2" })).toBeFocused();
    await expectAccessible(page, "calendar: an item opened");
    await page.getByTestId("calendar-panel-edit").click();
    await expectAccessible(page, "calendar: editing an item");
    await page.keyboard.press("Escape");
    await expect(title).toBeFocused();

    for (const view of ["month", "week", "semester"] as const) {
      await page.getByTestId(`calendar-view-${view}`).click();
      await expect(cal).toHaveAttribute("data-view", view);
      await expectAccessible(page, `calendar: ${view}`);
    }
    await expect(page.getByTestId("calendar-semester")).toContainText("3 due, 2 exams");

    await page.getByTestId("calendar-view-agenda").click();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("calendar-agenda")).toBeVisible();
    await expectAccessible(page, "calendar: agenda on a phone");

    served = [];
    await page.setViewportSize({ width: 1440, height: 980 });
    await page.reload();
    await expect(page.getByTestId("calendar-empty")).toBeVisible();
    await expectAccessible(page, "calendar: nothing on it yet");
  } finally {
    await context.close();
    await setUserFlag("calendar_v2", USER_LOOP, "off");
  }
});

// The redesigned calendar, every control clicked once, with motion ON (the
// other journeys run reduced): the course dropdown, the period header (its
// name first, then the arrows and Today) in each view, a day in the
// mini month, every way into the item panel, Add a date, Edit + Save, Delete,
// and the More menu. The writes are answered here; what is asserted is the
// request each control sends.
test("calendar redesign: every control, with motion on (calendar_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  await setUserFlag("calendar_v2", USER_LOOP, "on");
  const [{ course_id: courseId }] = (await queryRaw(
    `SELECT o.course_id FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id WHERE e.user_id = $1 ORDER BY o.course_id LIMIT 1`,
    [USER_LOOP],
  )) as { course_id: string }[];
  const row = (id: string, title: string, due: string, type: string) =>
    ({ id, user_id: USER_LOOP, title, due_date: due, assignment_type: type, course_id: courseId, notes: "" });
  const dates = [
    row("cal-mid1", "Midterm Exam", "2026-03-02", "exam"), row("cal-hw7", "HW 7", "2026-03-12", "homework"),
    row("cal-q4", "Quiz 4", "2026-03-13", "quiz"), row("cal-mid2", "Midterm 2", "2026-03-20", "exam"),
    row("cal-mid3", "Midterm", "2026-03-30", "exam"),
  ];
  const writes: { method: string; url: string; body: string | null }[] = [];
  // motion explicitly on: headless Chromium can report reduced motion by default
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop"), reducedMotion: "no-preference" });
  await context.addInitScript(() => { window.localStorage.setItem("sapling_disclaimer_ack", "true"); });
  const page = await context.newPage();
  try {
    await page.route(/\/api\/calendar\/all\//, (route) => route.fulfill({ json: { assignments: dates } }));
    await page.route(/\/api\/calendar\/(save|assignments\/)/, (route) => {
      const r = route.request();
      writes.push({ method: r.method(), url: r.url(), body: r.postData() });
      return route.fulfill({ json: { saved_count: 1, updated: true, deleted: true } });
    });
    await page.goto("/calendar");
    const cal = page.getByTestId("calendar-v2");
    await expect(cal).toHaveAttribute("data-view", "agenda");

    // motion is on: a view arrives with its enter animation and settles opaque
    const view = cal.locator("[class*=viewEnter]");
    await expect.poll(() => view.evaluate((el) => getComputedStyle(el).animationName)).toContain("viewIn");
    await expect.poll(() => view.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");

    // the course dropdown: untick hides, All courses restores, Escape closes and hands focus back
    const courses = page.getByTestId("calendar-courses");
    await expect(courses).toHaveText("All courses");
    await courses.click();
    const menu = page.getByTestId("calendar-courses-menu");
    await expect(menu).toBeVisible();
    await expect.poll(() => menu.evaluate((el) => getComputedStyle(el).animationName)).toContain("menuIn");
    await page.getByTestId(`calendar-course-${courseId}`).uncheck();
    await expect(page.getByTestId("calendar-item-cal-hw7")).toHaveCount(0);
    await expect(courses).toHaveText(/0 of 1 courses/);
    await page.getByTestId("calendar-course-all").click();
    await expect(page.getByTestId("calendar-item-cal-hw7")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(courses).toBeFocused();

    // the earlier dates, then a day in the mini month opens its week (the
    // week strip does the same on a phone; it is hidden at this width)
    await page.getByTestId("calendar-earlier").click();
    await expect(page.getByTestId("calendar-item-cal-mid1")).toBeVisible();
    await page.getByTestId("calendar-mini").getByRole("button", { name: /Fri Mar 13/ }).click();
    await expect(cal).toHaveAttribute("data-view", "week");
    await expect(page.getByTestId("calendar-period")).toHaveText("Mar 9 – 15");

    // each view's header: the period's name first, then ‹ Today ›
    const order = async () => page.evaluate(() => ["calendar-period", "calendar-prev", "calendar-today", "calendar-next"]
      .map((id) => document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().left));
    for (const [v, start, back, ahead] of [
      ["week", "Mar 9 – 15", "Mar 2 – 8", "Mar 16 – 22"],
      ["month", "March 2026", "February 2026", "April 2026"],
      ["semester", "Mar 2 – Apr 26", "Feb 2 – Mar 29", "Mar 30 – May 24"],
    ] as const) {
      await page.getByTestId(`calendar-view-${v}`).click();
      await expect(cal).toHaveAttribute("data-view", v);
      const period = page.getByTestId("calendar-period");
      await expect(period).toHaveText(start);
      const xs = await order();
      expect(xs, `${v}: name, then ‹ Today ›`).toEqual([...xs].sort((a, b) => a - b));
      await page.getByTestId("calendar-prev").click();
      await expect(period).toHaveText(back);
      await page.getByTestId("calendar-today").click();
      await expect(period).toHaveText(start);
      await page.getByTestId("calendar-next").click();
      await expect(period).toHaveText(ahead);
      await page.getByTestId("calendar-today").click();
    }

    // every way into the panel: a semester mark, a month pill, a week pill, an agenda row
    const panel = page.getByTestId("calendar-panel");
    const opens = [
      ["semester", page.getByTestId("calendar-mark-cal-mid2")],
      ["month", page.getByTestId("calendar-pill-cal-q4")],
      ["week", page.getByTestId("calendar-pill-cal-hw7")],
    ] as const;
    for (const [v, opener] of opens) {
      await page.getByTestId(`calendar-view-${v}`).click();
      await opener.click();
      await expect(panel).toBeVisible();
      await expect.poll(() => panel.evaluate((el) => getComputedStyle(el).animationName)).toContain("panelIn");
      await page.getByTestId("calendar-panel-close").click();
      await expect(panel).toHaveCount(0);
      await expect(opener).toBeFocused();
    }

    // Edit + Save sends a PATCH; Delete asks once, then sends a DELETE
    await page.getByTestId("calendar-view-agenda").click();
    await page.getByTestId("calendar-item-cal-mid2").getByRole("button", { name: /Midterm 2/ }).click();
    await page.getByTestId("calendar-panel-edit").click();
    await page.getByTestId("calendar-field-title").fill("Midterm 2 (room 101)");
    await page.getByTestId("calendar-panel-save").click();
    await expect.poll(() => writes.find((w) => w.method === "PATCH")?.body ?? "").toContain("Midterm 2 (room 101)");
    const del = page.getByTestId("calendar-panel-delete");
    await del.click();
    await expect(del).toHaveText("Click again to delete");
    await del.click();
    await expect.poll(() => writes.some((w) => w.method === "DELETE" && w.url.includes("cal-mid2"))).toBe(true);
    await expect(panel).toHaveCount(0);

    // More: Add a date sends a POST; the menu's other items are there
    await page.getByTestId("calendar-more").click();
    await expect(page.getByTestId("calendar-more-menu")).toContainText("Export as CSV");
    await page.getByTestId("calendar-add-date").click();
    await expect(page.getByRole("heading", { level: 2, name: "Add a date" })).toBeFocused();
    await page.getByTestId("calendar-field-title").fill("Reading quiz");
    await page.getByTestId("calendar-field-date").fill("2026-03-18");
    await page.getByTestId("calendar-panel-save").click();
    await expect.poll(() => writes.find((w) => w.method === "POST")?.body ?? "").toContain("Reading quiz");
    await expect(panel).toHaveCount(0);
  } finally {
    await context.close();
    await setUserFlag("calendar_v2", USER_LOOP, "off");
  }
});

test("learning loop: a segment's ungraded guess and a self-explanation prompt (A138, A139 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  test.setTimeout(LOOP_TIMEOUT_MS);
  // Both flags on for this student only (feature_flag_targets; the reset wipes them).
  await setUserFlag("segment_prequestion", USER_LOOP, "on");
  await setUserFlag("self_explanation_prompts", USER_LOOP, "on");
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/learn");
    await page.getByTestId("loop-start-guided").click();
    await walkCheckInAndPlan(page, Number(P.PROBE_SESSION_CAP), { approve: false });
    // a fresh multiple-choice pool for the segment's guess, added after the check-in
    await seedTeachPromptItems();
    await page.getByTestId("loop-plan-approve").click();
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "teach");
    await expect(page.getByTestId("loop-prequestion-options")).toBeVisible();
    await page.getByTestId("loop-prequestion-option-B").click();
    await expectAccessible(page, "learn loop: a segment's ungraded guess");

    await page.getByTestId("loop-prequestion-no-idea").click();
    await expect(page.getByTestId("loop-prequestion")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    // spec §13 A122: the first check opens on its worked example, whose hint asks "why"
    await page.getByTestId("loop-check-me").click();
    await expect(page.getByTestId("loop-self-explain")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("loop-hint-button")).toBeEnabled();
    await expectAccessible(page, "learn loop: a self-explanation prompt");
  } finally {
    await context.close();
  }
});

/** spec §13 A128's notes, from the server's own answers with the flags set. */
async function stubDegradedNotes(page: Page) {
  await page.route("**/api/learn/loop/start-session", (route) => withFields(route, { materials_unavailable: true }));
  await page.route("**/api/learn/loop/probe/next", (route) =>
    route.fulfill({ json: { done: true, phase: "plan", no_check_items: true, preparing: true } }),
  );
  // The stubbed check-in never reaches the server, so the lazily started session
  // is never materialised (the first real /probe/next does that). The server's
  // plan read then rightly answers 404 "Session not found", which Tutor V2 shows
  // as a lost session (#866 K26), so the plan read is answered here too.
  await page.route(
    (url) => url.pathname.endsWith("/api/learn/loop/plan"),
    (route) => route.fulfill({ json: { concepts: [], order: [], phase: "plan" } }),
  );
}

// The notices region shows one notice at a time, most important first
// (components/ui/StatusSlot): the pause, then the preparing note, then the
// materials note. Each is scanned as the one on screen.
test("learning loop: the budget pause and the degraded-mode notes", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  const capped = await signIn(browser, USER_CAPPED, "Casey Cap");
  try {
    const { page } = capped;
    await stubDegradedNotes(page);
    await page.goto("/learn");
    await page.getByTestId("loop-start-guided").click();
    await expect(page.getByTestId("loop-budget-paused")).toBeVisible();
    await expect(page.getByTestId("loop-notices")).toHaveAttribute("data-notice", "paused");
    await expect(page.getByTestId("loop-materials-unavailable")).toHaveCount(0);
    await expect(page.getByTestId("loop-preparing-items")).toHaveCount(0);
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "plan");
    await expectAccessible(page, "learn loop: paused (one notice at a time)");
  } finally {
    await capped.context.close();
  }
  const loop = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    const { page } = loop;
    await stubDegradedNotes(page);
    await page.goto("/learn");
    await page.getByTestId("loop-start-guided").click();
    await expect(page.getByTestId("loop-preparing-items")).toBeVisible();
    await expect(page.getByTestId("loop-notices")).toHaveAttribute("data-notice", "preparing");
    await expect(page.getByTestId("loop-materials-unavailable")).toHaveCount(0);
    await expectAccessible(page, "learn loop: preparing questions");
  } finally {
    await loop.context.close();
  }
});

test("review queue: a flashcard, its answer, the rated result and a multiple-choice check", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  try {
    await page.goto("/study");
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
    // #866 Z29: under Tailwind's preflight an unstyled textarea has no border or
    // fill; the reason box is a visible, labelled field
    const reasonBox = page.getByRole("textbox", { name: "In one sentence: why?" });
    await expect(reasonBox).toBeVisible();
    expect(await reasonBox.evaluate((el) => getComputedStyle(el).borderTopWidth)).toBe("1px");
    await expectAccessible(page, "review: a multiple-choice check");
  } finally {
    await context.close();
  }
});

// Tutor redesign phase 4: Review in Study, rebuilt (review_v2): the queue and
// the retention check leave the top of the hub for two rows in its rail, under
// Quick Reviews; each opens in the hub's modal, with the rebuilt head (the
// title, a chip per course and All courses, "n of m").
test("review queue, rebuilt: the rail rows and the queue in its modal (review_v2 on)", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  await setUserFlag("review_v2", USER_CAPPED, "on");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  try {
    await page.goto("/study");
    const review = page.getByTestId("study-rail-review");
    await expect(review).toBeVisible();
    await expect(page.getByTestId("study-rail-retention")).toBeVisible();
    await expect(page.getByTestId("review-due-panel")).toHaveCount(0); // nothing on top of the hub
    await expectAccessible(page, "review, rebuilt: the hub with its rail rows");
    await review.click();
    const dialog = page.getByRole("dialog", { name: "Review" });
    await expect(dialog.getByTestId("review-item")).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
    await expect(dialog.getByTestId("review-budget")).toHaveCount(0);
    await expect(dialog.getByTestId("review-progress")).toHaveText(/^1 of \d+$/);
    await expectAccessible(page, "review, rebuilt: the queue in its modal");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(review).toBeFocused(); // focus returns to the row
    await page.getByTestId("study-rail-retention").click();
    await expect(page.getByRole("dialog", { name: "Retention check" }).getByTestId("retention-open")).toBeVisible();
    await expectAccessible(page, "review, rebuilt: the retention check in its modal");
  } finally {
    await context.close();
  }
});

test("retention check: opened with nothing eligible yet", async ({ browser }) => {
  test.skip(loopOffLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  try {
    await page.goto("/study");
    await expect(page.getByTestId("retention-open")).toBeEnabled();
    // #866 Z29: the course picker is a visible field, not a borderless select
    expect(await page.getByTestId("retention-course").evaluate((el) => getComputedStyle(el).borderTopWidth)).toBe("1px");
    await expectAccessible(page, "review: retention check entry");
    await page.getByTestId("retention-open").click();
    await expect(page.getByTestId("retention-empty")).toBeVisible();
    await expectAccessible(page, "review: retention check, none eligible");
  } finally {
    await context.close();
  }
});
