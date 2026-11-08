/**
 * Keyboard-only learning loop journey (learning-loop spec §13 A135): the
 * check-in (easy items right, harder ones wrong), the plan, and a check item
 * answered wrong then right — a wrong attempt that earns a hint, then the right
 * answer, submitted — with no mouse. A check item takes one graded submission
 * (A16), so "wrong" is the recorded attempt the hint gate judged. Every new
 * question must take focus (its answer box, described by the question), and
 * every control that goes away must hand focus on: the answer shown after a
 * miss, the plan's heading, "Start with …", the composer after a tutor turn,
 * Continue after a graded answer, Check me when nothing is left, the wrap-up's
 * heading.
 *
 * Default lane only (spec §11.4): under the kill switch the loop routes 404.
 * Function mode supplies every model's text (agents/function_handlers_e2e.py);
 * the grader marks an answer carrying E2E_GRADER_CORRECT correct and any other
 * not yet. Learning constants come from backend/learning/params.py
 * (support/params.ts).
 */
import type { Browser, Page } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_BODY */
const LOOP_HINT_BODY = "Reread the item and name the one thing it wants you to state.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_QUESTION */
const LOOP_HINT_QUESTION = "What is the first thing you need before you can answer this?";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_FEEDBACK_BODY */
const LOOP_FEEDBACK_BODY = "Look at which part of the item your answer addressed.";
/** A genuine attempt (long enough, no non-attempt phrase: learning/gates.py) that
 *  never carries the correct token, so it grades not yet (learn-loop.spec.ts). */
const WORKING_ATTEMPT = "working: I think it is the value the item names";

const JOURNEY_TIMEOUT_MS = 240_000;
const GATE_POLL_MARGIN_MS = 15_000;
const DB_POLL_TIMEOUT_MS = 5_000;

async function signIn(browser: Browser) {
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop") });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page };
}

/** The data-testid of whatever holds focus, or null. */
function focusedTestId(page: Page): Promise<string | null> {
  return page.evaluate(() => (document.activeElement as HTMLElement | null)?.dataset.testid ?? null);
}

/** Press `key` (Tab or Shift+Tab) until `testid` holds focus: the control is
 *  reachable from the keyboard. A bounded walk, failing with the focus trail. */
async function keyTo(page: Page, testid: string, key: "Tab" | "Shift+Tab", max = 60): Promise<void> {
  const trail: (string | null)[] = [];
  for (let i = 0; i < max; i++) {
    if ((await focusedTestId(page)) === testid) return;
    await page.keyboard.press(key);
    trail.push(await focusedTestId(page));
  }
  throw new Error(`${key} never reached [data-testid="${testid}"] in ${max} presses. Focus trail: ${JSON.stringify(trail)}`);
}

/** The question a card poses (its prompt paragraph, which describes the answer box). */
async function questionOf(page: Page, card: "loop-probe-item" | "loop-check-prompt"): Promise<string> {
  return ((await page.getByTestId(card).locator("p").first().textContent()) ?? "").trim();
}

test("keyboard only: the check-in, the plan, and a check item answered wrong (earning a hint) then right", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP", "GATE_INDEPENDENT_MIN_S_NOVICE"]);
  const { context, page } = await signIn(browser);
  try {
    await page.goto("/learn");
    const phase = page.getByTestId("loop-phase");

    // ── Check-in: each question takes focus and is answered from its box ──
    const probeItem = page.getByTestId("loop-probe-item");
    const probeAnswer = page.getByRole("textbox", { name: "Check-in answer" });
    const reference = page.getByTestId("loop-probe-reference");
    await expect(probeItem).toBeVisible();
    let answered = 0;
    let missed = 0;
    while ((await phase.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
      await expect(probeAnswer).toBeFocused();
      await expect(probeAnswer).toHaveAccessibleDescription(await questionOf(page, "loop-probe-item"));
      const qh = await probeItem.getAttribute("data-question-hash");
      const difficulty = Number(await probeItem.getAttribute("data-difficulty"));
      await page.keyboard.type(difficulty === 1 ? GRADER_CORRECT_TOKEN : WORKING_ATTEMPT);
      await page.keyboard.press("Control+Enter"); // submits from the answer box
      answered += 1;
      await expect
        .poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
          (await reference.isVisible()) ||
          ((await probeItem.isVisible()) && (await probeItem.getAttribute("data-question-hash")) !== qh))
        .toBe(true);
      if (await reference.isVisible()) {
        // the answer shown after a miss takes focus (so it is read out); Next follows it
        missed += 1;
        await expect(reference).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(page.getByTestId("loop-probe-next")).toBeFocused();
        await page.keyboard.press("Enter");
        await expect
          .poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
            (await probeItem.getAttribute("data-question-hash")) !== qh)
          .toBe(true);
      }
    }
    expect(missed, "the check-in missed a harder item, so its answer was shown").toBeGreaterThan(0);

    // ── The plan: its heading takes focus; Tab reaches Start learning ──
    await expect(phase).toHaveAttribute("data-phase", "plan");
    await expect(page.getByRole("heading", { name: "Today's plan" })).toBeFocused();
    await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
    await keyTo(page, "loop-plan-approve", "Tab");
    await page.keyboard.press("Enter");
    await expect(phase).toHaveAttribute("data-phase", "teach");

    // ── Teaching: "Start with …" has focus; after the turn the composer does ──
    await expect(page.getByTestId("loop-teach-start")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByTestId("loop-teach-start")).toHaveCount(0);
    await expect(page.getByTestId("tutor-input")).toBeFocused();

    // ── The check: Check me, from the keyboard; the check takes focus ──
    await keyTo(page, "loop-check-me", "Shift+Tab");
    const posed = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/check/next");
    await page.keyboard.press("Enter");
    const pose = (await (await posed).json()).check as { question_hash: string; worked_first?: boolean };
    const check = page.getByTestId("loop-check-prompt");
    const answer = page.getByRole("textbox", { name: "Your answer", exact: true });
    const hintButton = page.getByTestId("loop-hint-button");
    const hintReply = page.getByTestId("loop-hint-reply");
    await expect(check).toHaveAttribute("data-question-hash", pose.question_hash);
    await expect(answer).toBeFocused();
    await expect(answer).toHaveAccessibleDescription(await questionOf(page, "loop-check-prompt"));
    // spec §13 A122: this novice's check opens on its worked example, asked for
    // at once; focus stays in the answer box while it arrives.
    expect(pose.worked_first).toBe(true);
    await expect(hintReply).toContainText(LOOP_HINT_BODY);
    await expect(hintButton).toHaveAttribute("aria-disabled", "false");
    await expect(answer).toBeFocused();
    // The pose and the hint are in the live conversation log too (visually hidden
    // while the card shows them), so a screen reader heard them arrive.
    const log = page.getByRole("log", { name: "Conversation" });
    await expect(log).toContainText(LOOP_HINT_BODY);

    // Wrong first: a wrong attempt in the box, then a hint asked for from the
    // keyboard — the hint records the attempt (/step/attempt; never graded). H5
    // needs that attempt and the (scaled) independent-time dwell: press until it
    // is granted. The button keeps focus while each request runs.
    await page.keyboard.type(WORKING_ATTEMPT);
    await keyTo(page, "loop-hint-button", "Tab");
    await expect
      .poll(
        async () => {
          await page.keyboard.press("Enter");
          await expect(hintButton).toHaveAttribute("aria-disabled", "false");
          await expect(hintButton).toBeFocused();
          return (await hintReply.isVisible()) ? ((await hintReply.textContent()) ?? "") : "";
        },
        { timeout: Number(P.GATE_INDEPENDENT_MIN_S_NOVICE) * 1000 + GATE_POLL_MARGIN_MS, intervals: [500, 1_000, 2_000] },
      )
      .toContain(LOOP_HINT_QUESTION);
    await expect(log).toContainText(LOOP_HINT_QUESTION);
    const sessionId = await phase.getAttribute("data-session-id");
    await expect
      .poll(
        async () => {
          const [row] = (await queryRaw("SELECT loop_state FROM sessions WHERE id = $1", [sessionId])) as {
            loop_state: { steps?: Record<string, { attempted_at?: unknown[] }> };
          }[];
          return row?.loop_state?.steps?.[pose.question_hash]?.attempted_at?.length ?? 0;
        },
        { timeout: DB_POLL_TIMEOUT_MS },
      )
      .toBeGreaterThanOrEqual(1);

    // Then right: back to the box, replace the wrong attempt, submit from the box.
    // The answer is graded, and focus moves to Continue.
    await keyTo(page, "loop-attempt-input", "Shift+Tab");
    await expect(answer).toHaveValue(WORKING_ATTEMPT);
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type(`working: ${GRADER_CORRECT_TOKEN}`);
    await page.keyboard.press("Control+Enter");
    await expect(phase).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_BODY, { timeout: 30_000 });
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    await expect(page.getByTestId("loop-continue")).toBeFocused();
    await expect
      .poll(
        async () =>
          (await queryRaw(
            `SELECT e.correct
               FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id
              WHERE g.user_id = $1 AND e.event_type = 'evidence' AND e.question_hash = $2`,
            [USER_LOOP, pose.question_hash],
          )).map((row) => row.correct),
        { timeout: DB_POLL_TIMEOUT_MS },
      )
      .toEqual([true]);

    // ── Check me again: a new check takes focus; with none left, focus stays on
    // Check me and the note is announced from its live region ──
    await keyTo(page, "loop-check-me", "Tab");
    const posedAgain = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/check/next");
    await page.keyboard.press("Enter");
    const next = (await (await posedAgain).json()) as { check?: { question_hash: string } | null };
    if (next.check) {
      await expect(check).toHaveAttribute("data-question-hash", next.check.question_hash);
      await expect(answer).toBeFocused();
      await expect(answer).toHaveAccessibleDescription(await questionOf(page, "loop-check-prompt"));
    } else {
      const note = page.locator('[aria-live="polite"]').filter({ hasText: /every concept in today's plan|No check is ready/ });
      await expect(note).toBeVisible();
      await expect(page.getByTestId("loop-check-me")).toBeFocused();
    }

    // ── End session from the keyboard: the wrap-up's heading takes focus ──
    await keyTo(page, "loop-close-button", "Shift+Tab");
    await page.keyboard.press("Enter");
    await expect(phase).toHaveAttribute("data-phase", "close");
    await expect(page.getByRole("heading", { name: "Session wrap-up" })).toBeFocused();
  } finally {
    await context.close();
  }
});
