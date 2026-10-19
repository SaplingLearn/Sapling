/**
 * Journey (redesign prompt 04): the Clov tutor view of /learn.
 *
 * `/learn?view=tutor` is a VIEW of the same learning-loop controller, offered
 * only while the tutor_view flag is on for the student. The journey proves:
 *  1. with nothing open, the welcome waits for an explicit choice — no session
 *     is started by the visit or by a starter prompt;
 *  2. "Start check-in" runs the ordinary loop: check-in → plan approval →
 *     teaching, in the same session the studio would show;
 *  3. Stop and a failed stream each leave an interrupted turn whose Retry
 *     re-sends it ONCE: the database holds exactly one user row for the turn
 *     (ciphertext at rest, decrypting to the text), and the reply renders.
 *
 * Determinism: function mode (SAPLING_MODEL_MODE=function,
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e) and
 * LEARNING_GATE_TIME_SCALE=0.01, as learn-loop.spec.ts. The flag is set
 * through the admin API the /admin tab uses (feature-flags.spec.ts).
 */
import type { Browser, Page } from "@playwright/test";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptTexts } from "./support/decrypt";
import { learningParams } from "./support/params";
import { setUserFlag } from "./support/flags";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_TUTOR_REPLY (first paragraph). */
const LOOP_TUTOR_REPLY_START = "Key idea: [e2e-function-model] A recursive function needs a base case it is guaranteed to reach.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
const WORKING_ATTEMPT = "working: I think it is the value the item names";
const JOURNEY_TIMEOUT_MS = 240_000;

async function signIn(browser: Browser, userId: string, name: string) {
  const context = await browser.newContext({ storageState: await mintStorageState(userId, name) });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page };
}

/** Check-in → plan → approve, answering level-1 items correctly (as learn-loop.spec.ts). */
async function checkInAndApprove(page: Page, cap: number) {
  const phase = page.getByTestId("loop-phase");
  const probeItem = page.getByTestId("loop-probe-item");
  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < cap) {
    await expect(probeItem).toBeVisible();
    const qh = await probeItem.getAttribute("data-question-hash");
    const difficulty = Number(await probeItem.getAttribute("data-difficulty"));
    await page.getByTestId("loop-probe-input").fill(difficulty === 1 ? GRADER_CORRECT_TOKEN : WORKING_ATTEMPT);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    await expect
      .poll(async () => {
        if ((await phase.getAttribute("data-phase")) !== "probe") return true;
        if (await page.getByTestId("loop-probe-reference").isVisible()) return true;
        return (await probeItem.getAttribute("data-question-hash")) !== qh;
      })
      .toBe(true);
    if (await page.getByTestId("loop-probe-reference").isVisible()) {
      await page.getByTestId("loop-probe-next").click();
      // Wait for the next item or the end of the check-in before looping:
      // /probe/next may end the check-in, and the old form then unmounts.
      await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
        (await probeItem.getAttribute("data-question-hash")) !== qh).toBe(true);
    }
  }
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
}

/** This session's stored user rows with exactly `text` (decrypted), plus the raw values. */
async function storedUserTurns(sessionId: string, text: string) {
  const rows = (await queryRaw(
    "SELECT content FROM messages WHERE session_id = $1 AND role = 'user' ORDER BY created_at",
    [sessionId],
  )) as { content: string }[];
  const plain = await decryptTexts(rows.map((r) => r.content));
  const matching = rows.filter((_, i) => plain[i] === text);
  return { count: matching.length, raw: matching.map((r) => r.content) };
}

test("tutor view: the welcome waits, Start check-in runs the same loop, and Stop / a failed stream retry once without a duplicate turn", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  await setUserFlag(browser, "tutor_view", USER_LOOP, "on");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  const starts: string[] = [];
  const answers: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/learn/loop/start-session")) starts.push(r.url());
    if (r.url().includes("/api/learn/loop/check/answer")) answers.push(r.url());
  });

  // 1. Nothing open: the welcome, and nothing starts until the student chooses.
  await page.goto("/learn?view=tutor");
  const root = page.getByTestId("loop-phase");
  await expect(root).toHaveAttribute("data-view", "tutor");
  await expect(page.getByTestId("tutor-welcome")).toBeVisible();
  await page.getByTestId("tutor-starter-0").click();
  await expect(page.getByTestId("tutor-welcome-composer-input")).toHaveValue("Explain ");
  expect(starts).toEqual([]);
  expect(await root.getAttribute("data-session-id")).toBe("");

  // 2. The guided session is the ordinary loop.
  await page.getByTestId("tutor-welcome-start").click();
  await expect(root).toHaveAttribute("data-phase", "probe");
  expect(starts).toHaveLength(1);
  await checkInAndApprove(page, Number(P.PROBE_SESSION_CAP));
  const sessionId = (await root.getAttribute("data-session-id"))!;
  expect(sessionId).toBeTruthy();
  await expect(page).toHaveURL(/\/learn\?view=tutor$/); // the view survives; nothing else is in the URL

  // 3a. Stop before the reply: the request is held in the browser, so the
  // server never saw it. One Retry re-sends it; one user row is stored.
  const stopped = "Why does a base case stop recursion? (stopped once)";
  let entered = () => {};
  let release = () => {};
  const requested = new Promise<void>((resolve) => { entered = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/learn/loop/chat/stream", async (route) => {
    entered();
    await held;
    try {
      await route.abort();
    } catch {
      // Chromium already discarded the request when the page aborted it.
    }
  });
  await page.getByTestId("tutor-input").fill(stopped);
  await page.getByTestId("tutor-send").click();
  await requested;
  await page.getByTestId("tutor-stop").click();
  await expect(page.getByTestId("tutor-interrupted")).toContainText("You stopped this reply.");
  release();
  await page.unroute("**/api/learn/loop/chat/stream");
  await page.getByTestId("tutor-retry").click();
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_TUTOR_REPLY_START);
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);
  await expect.poll(async () => (await storedUserTurns(sessionId, stopped)).count).toBe(1);
  const stored = await storedUserTurns(sessionId, stopped);
  expect(stored.raw[0]).not.toBe(stopped); // ciphertext at rest

  // 3b. A stream that fails before any token: the turn is kept and marked;
  // Retry sends it once more and only once.
  const failed = "Can you give me another example? (failed once)";
  await page.route("**/api/learn/loop/chat/stream", (route) => route.abort("connectionfailed"), { times: 1 });
  await page.getByTestId("tutor-input").fill(failed);
  await page.getByTestId("tutor-send").click();
  await expect(page.getByTestId("tutor-interrupted")).toContainText("This reply was interrupted.");
  await page.getByTestId("tutor-retry").click();
  await expect(page.getByTestId("tutor-interrupted")).toHaveCount(0);
  await expect.poll(async () => (await storedUserTurns(sessionId, failed)).count).toBe(1);
  const shown = page.getByTestId("tutor-messages").locator(".fa26-message--user", { hasText: failed });
  await expect(shown).toHaveCount(1);

  // The same session, still teaching: a tutor turn may activate a check (the
  // server's done.check), but nothing here submitted or graded an answer.
  await expect(root).toHaveAttribute("data-session-id", sessionId);
  expect(["teach", "check"]).toContain(await root.getAttribute("data-phase"));
  expect(answers).toEqual([]);
  await context.close();
});
