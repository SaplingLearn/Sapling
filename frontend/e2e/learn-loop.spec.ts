/**
 * Journeys (learning loop, PKG-13) — the launch UI (spec §11.3, §13 A26):
 *  1. a loop user walks probe → plan → teach/check (explicit submission, gated
 *     hint) → feedback → close, and every belief change lands in the database
 *     through apply_graph_update;
 *  2. a reload mid-session resumes the same session and calls no probe route;
 *  3. a capped user (today's spend past the novice allowance) sees tutor chat
 *     paused on /learn while review still serves and grades on /study;
 *  4. every student gets the loop by default (default lane), and the kill switch
 *     restores the legacy Learn screen (kill-switch lane) — PKG-14b, spec §11.4.
 *
 * Lanes (support/fixtures.ts::killSwitchLane, spec §11.4): journeys 1–3 and
 * "every student gets the loop by default" run in the default lane only (no
 * LEARNING_LOOP_ENABLED at all — the code default); "kill switch restores the
 * legacy Learn screen" runs under LEARNING_LOOP_ENABLED=false only.
 *
 * Determinism: function mode (SAPLING_MODEL_MODE=function,
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e) plus
 * LEARNING_GATE_TIME_SCALE=0.01 (scripts/e2e-up.sh; spec §13 A5). The seeded
 * loop users are ordinary students after PKG-14b (their build-phase toggle rows
 * are inert — nothing reads them). The grader is
 * scripted: an answer carrying GRADER_CORRECT_TOKEN grades correct, any other
 * text not yet. Learning constants are read from backend/learning/params.py via
 * support/params.ts — never as literals here.
 *
 * Oracle: the fixtures truncate + re-seed before EVERY test, so the post-suite
 * `python -m e2e_oracles` sees only the last test's rows. The loop journey runs
 * `--check learn_loop --expect-loop-activity` itself, right after its walk
 * (support/oracle.ts): the loop's evidence and zpd.step rows must exist for the
 * steps its session graded, and no assistant message may state the seeded final
 * answer (E2E_LOOP_FINAL_ANSWER) before a release.
 */
import type { Browser, Page, Response } from "@playwright/test";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw, seedGoalContinuationItems } from "./support/db";
import { decryptText } from "./support/decrypt";
import { learningParams } from "./support/params";
import { runOracle } from "./support/oracle";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE, USER_CAPPED, USER_LOOP } from "./support/stack";

/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_PROBE_PROMPT */
const LOOP_PROBE_PROMPT =
  "[e2e-loop] Check item: type the e2e grader's correct token to be marked correct.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_TUTOR_REPLY */
const LOOP_TUTOR_REPLY =
  "Key idea: [e2e-function-model] A recursive function needs a base case it is guaranteed to reach.\n\n" +
  "Try writing the base case for factorial before anything else.\n\n" +
  "Which input should stop the recursion?";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_BODY */
const LOOP_HINT_BODY = "Reread the item and name the one thing it wants you to state.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_HINT_QUESTION */
const LOOP_HINT_QUESTION = "What is the first thing you need before you can answer this?";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_FEEDBACK_BODY */
const LOOP_FEEDBACK_BODY = "Look at which part of the item your answer addressed.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_LOOP_FEEDBACK_QUESTION */
const LOOP_FEEDBACK_QUESTION = "How would you check that part yourself next time?";
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
/** Must match backend/agents/function_handlers_e2e.py::E2E_CLOSE_SUMMARY */
const CLOSE_SUMMARY =
  "[e2e-function-model] Deterministic session close: the student checked " +
  "recursion base cases and moved from unsure to mostly sure; the off-by-one " +
  "boundary is still open.";
/** Must match backend/agents/function_handlers_e2e.py::E2E_CLOSE_IF_THEN */
const CLOSE_IF_THEN =
  "If the next session opens with a recursion check, then write the base case " +
  "before the recursive step.";
// Mirrors backend/db/seed_local_rich.py::CAPPED_FLASHCARD (id, front).
const CAPPED_CARD_ID = "rich-fc-capped-1";
const CAPPED_CARD_FRONT = "What is a bit?";

// Harness constants (†, not learning parameters — see PKG-13 §Named constants).
const LOOP_JOURNEY_TIMEOUT_MS = 240_000;
const GATE_POLL_MARGIN_MS = 15_000;
const DB_POLL_TIMEOUT_MS = 5_000;
/** A genuine attempt's text (long enough, no non-attempt phrase: learning/gates.py)
 *  that does NOT carry the correct token, so it can never grade correct. */
const WORKING_ATTEMPT = "working: I think it is the value the item names";

type Params = Record<string, number | boolean>;

async function signIn(browser: Browser, userId: string, name: string) {
  const context = await browser.newContext({ storageState: await mintStorageState(userId, name) });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  return { context, page };
}

/** A structured turn renders as separate paragraphs: assert each one. */
async function expectTurn(page: Page, text: string) {
  const log = page.getByTestId("loop-messages");
  for (const paragraph of text.split("\n\n")) await expect(log).toContainText(paragraph);
}

/** Probe → plan → approve. The fixture succeeds independently at level1 and
 * misses harder items, so the diagnostic observes a real boundary/limit and
 * still has meaningful frontier work to plan. All-correct can validly skip an
 * empty coursewide plan once every concept is proficient. */
async function walkProbeAndPlan(page: Page, P: Params): Promise<number> {
  const phase = page.getByTestId("loop-phase");
  await expect(phase).toHaveAttribute("data-phase", "probe");
  const probeItem = page.getByTestId("loop-probe-item");
  await expect(probeItem).toContainText(LOOP_PROBE_PROMPT);

  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
    const qh = await probeItem.getAttribute("data-question-hash");
    const difficulty = Number(await probeItem.getAttribute("data-difficulty"));
    expect([1, 2, 3]).toContain(difficulty);
    await page.getByTestId("loop-probe-input").fill(difficulty === 1 ? GRADER_CORRECT_TOKEN : WORKING_ATTEMPT);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    // A correct answer advances; a miss shows corrective feedback until Next.
    // Neither case bypasses the diagnostic or assumes a posterior means mastery.
    await expect
      .poll(async () => {
        if ((await phase.getAttribute("data-phase")) !== "probe") return true;
        if (!(await probeItem.isVisible())) return false;
        const now = await probeItem.getAttribute("data-question-hash");
        return (await page.getByTestId("loop-probe-reference").isVisible()) || (now !== null && now !== qh);
      })
      .toBe(true);
    if (await page.getByTestId("loop-probe-reference").isVisible()) {
      expect(difficulty).toBeGreaterThan(1);
      await page.getByTestId("loop-probe-next").click();
      await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
        (await probeItem.getAttribute("data-question-hash")) !== qh).toBe(true);
    } else {
      expect(difficulty).toBe(1);
      await expect(page.getByTestId("loop-probe-reference")).toHaveCount(0);
    }
  }

  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.locator("[data-testid^='loop-plan-concept-']").first()).toBeVisible();
  await page.getByTestId("loop-plan-approve").click();
  await expect(phase).toHaveAttribute("data-phase", "teach");
  return answered;
}

/** The first teach turn after the plan: the student starts it (/plan/approve runs no turn). */
async function firstTeachTurn(page: Page) {
  await page.getByTestId("loop-teach-start").click();
  await expectTurn(page, LOOP_TUTOR_REPLY);
}

test("loop user completes probe → plan → check (explicit submission) with a gated hint → close, and the loop writes land", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams([
    "PROBE_ITEMS_PER_SKILL_MIN",
    "PROBE_SESSION_CAP",
    "GATE_INDEPENDENT_MIN_S_NOVICE",
  ]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  const loopBodies: { path: string; body: string }[] = [];
  page.on("request", (r) => {
    const { pathname } = new URL(r.url());
    if (pathname.startsWith("/api/learn/loop/")) loopBodies.push({ path: pathname, body: r.postData() ?? "" });
  });

  // ── Probe + plan (no open session after the fixture's re-seed → a new one) ─
  await page.goto("/learn");
  const phase = page.getByTestId("loop-phase");
  const answered = await walkProbeAndPlan(page, P);
  expect(answered).toBeGreaterThanOrEqual(Number(P.PROBE_ITEMS_PER_SKILL_MIN));
  await expect(page.getByTestId("loop-tree-link")).toHaveAttribute("href", /^\/tree/); // the map stays reachable
  await expect(page.getByRole("radiogroup", { name: "Tutor model" })).toHaveCount(0); // no model toggle (A26)

  // ── Teach / check ─────────────────────────────────────────────────────────
  await firstTeachTurn(page);
  // spec §13 A27: PKG-07 activates the concept's next item after LOOP_TEACH_TURNS_BEFORE_CHECK
  // teach turns, or on "Check me" (POST /check/next, no model call).
  const check = page.getByTestId("loop-check-prompt");
  await page.getByTestId("loop-check-me").click();
  await expect(check).toBeVisible();
  await expect(phase).toHaveAttribute("data-phase", "check");
  // The check pose is a template (spec §13 A17): the seeded item prompt, no model reply.
  await expect(check).toContainText(LOOP_PROBE_PROMPT);
  const checkHash = await check.getAttribute("data-question-hash");
  expect(checkHash).toBeTruthy();

  // Hint before any attempt → denied with a reason from learning/gates.py.
  await page.getByTestId("loop-hint-button").click();
  const denied = page.getByTestId("loop-hint-denied");
  await expect(denied).toBeVisible();
  await expect(denied).toHaveAttribute("data-reason", "no_genuine_attempt");

  // The student's working is posted as /step/attempt when they ask for a hint (the
  // gate judges the TEXT) and lands in sessions.loop_state (steps[qh].attempted_at).
  // The independent-time gate (GATE_INDEPENDENT_MIN_S_NOVICE †, × the lane's time
  // scale) is server-side: poll the Hint button until the rung unlocks. No client
  // timer exists to skip it; the bound below is the UNSCALED gate, so the poll is
  // honest whatever the lane scale is.
  await page.getByTestId("loop-attempt-input").fill(WORKING_ATTEMPT);
  const hintButton = page.getByTestId("loop-hint-button");
  const hintReply = page.getByTestId("loop-hint-reply");
  await expect
    .poll(
      async () => {
        await hintButton.click();
        await expect(hintButton).toBeEnabled();
        return (await hintReply.isVisible()) ? ((await hintReply.textContent()) ?? "") : "";
      },
      {
        timeout: Number(P.GATE_INDEPENDENT_MIN_S_NOVICE) * 1000 + GATE_POLL_MARGIN_MS,
        intervals: [500, 1_000, 2_000],
      },
    )
    .toContain(LOOP_HINT_BODY);
  await expect(hintReply).toContainText(LOOP_HINT_QUESTION);
  const sessionRows = async () =>
    (await queryRaw(`SELECT id, loop_state FROM sessions WHERE user_id = $1 AND mode <> 'review'`, [
      USER_LOOP,
    ])) as { id: string; loop_state: { steps?: Record<string, { attempted_at?: unknown[]; rung?: number }> } }[];
  await expect
    .poll(
      async () =>
        (await sessionRows()).some((r) => {
          const step = r.loop_state?.steps?.[checkHash!];
          return (step?.attempted_at?.length ?? 0) >= 1 && (step?.rung ?? 0) >= 1;
        }),
      { timeout: DB_POLL_TIMEOUT_MS },
    )
    .toBe(true);

  // Correct attempt → the explicit-submission route (spec §13 A16), never a chat turn.
  const submitted = page.waitForRequest((r) => r.url().includes("/api/learn/loop/check/answer/stream"));
  await page.getByTestId("loop-attempt-input").fill(`working: ${GRADER_CORRECT_TOKEN}`);
  // The learner chip appears only after grading. Read this active session's
  // concept directly, after the earned hint and immediately before submission.
  const checkedSessionId = await phase.getAttribute("data-session-id");
  expect(checkedSessionId).toBeTruthy();
  const beforeCheck = (await queryRaw(
    `SELECT l.node_id, l.p_known
       FROM sessions s JOIN learner_state l
         ON l.user_id = s.user_id AND l.node_id = s.loop_state->>'concept'
      WHERE s.id = $1 AND s.user_id = $2`,
    [checkedSessionId, USER_LOOP],
  )) as { node_id: string; p_known: number }[];
  expect(beforeCheck).toHaveLength(1);
  const checkedNodeId = beforeCheck[0].node_id;
  const beforeCheckKnown = Number(beforeCheck[0].p_known);
  expect(checkedNodeId).toBeTruthy();
  expect(Number.isFinite(beforeCheckKnown)).toBe(true);
  expect(beforeCheckKnown).toBeGreaterThan(0);
  expect(beforeCheckKnown).toBeLessThan(1);
  await page.getByTestId("loop-attempt-submit").click();
  const body = JSON.parse((await submitted).postData() ?? "{}");
  expect(body).toMatchObject({ question_hash: checkHash, idk: false, answer: `working: ${GRADER_CORRECT_TOKEN}` });
  await expect(phase).toHaveAttribute("data-phase", "feedback");
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_BODY);
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_QUESTION);
  // The diagnostic deliberately includes independent misses, so the initial
  // prior is no longer this check's baseline. Even assisted correct evidence
  // must improve the checked concept from its actual pre-submission belief.
  const learner = page.getByTestId("loop-learner-state");
  await expect(learner).toBeVisible();
  await expect(learner).toHaveAttribute("data-node-id", checkedNodeId);
  await expect.poll(async () => Number(await learner.getAttribute("data-p-known"))).toBeGreaterThan(beforeCheckKnown);
  const afterCheckKnown = Number(await learner.getAttribute("data-p-known"));

  // A15/A16/A26: no loop request carried a model preference, and the answer never went
  // through the chat route.
  expect(loopBodies.filter((b) => b.body.includes("model_pref"))).toEqual([]);
  expect(
    loopBodies.filter((b) => b.path.endsWith("/chat/stream") && b.body.includes(GRADER_CORRECT_TOKEN)),
  ).toEqual([]);

  // ── Close ─────────────────────────────────────────────────────────────────
  await page.getByTestId("loop-close-button").click();
  await expect(phase).toHaveAttribute("data-phase", "close");
  await expect(page.getByTestId("loop-close-summary")).toContainText(CLOSE_SUMMARY);
  await expect(page.getByTestId("loop-close-if-then")).toContainText(CLOSE_IF_THEN);
  // A60: the self-evaluation is a reflection prompt — no input implies it is saved.
  await expect(page.getByTestId("loop-close-self-eval").locator("textarea, input")).toHaveCount(0);
  await expect(page.getByTestId("loop-close-done")).toBeVisible();

  // ── Database: the loop's writes, through apply_graph_update ──────────────
  const states = (await queryRaw(`SELECT node_id, p_known FROM learner_state WHERE user_id = $1`, [
    USER_LOOP,
  ])) as { node_id: string; p_known: number }[];
  expect(states.length).toBeGreaterThan(0);
  const checkedState = states.find((s) => s.node_id === checkedNodeId);
  expect(checkedState, "the explicitly checked concept is persisted").toBeDefined();
  expect(Number(checkedState!.p_known)).toBeGreaterThan(beforeCheckKnown);
  // The DB stores the posterior; UI reads intentionally apply elapsed-time
  // decay. Allow that tiny read-time difference while checking the same node.
  expect(Number(checkedState!.p_known)).toBeCloseTo(afterCheckKnown, 5);

  // The explicit submission was graded (A16): an evidence row carries the check's hash,
  // and every graded probe answer wrote one too.
  const evidence = (await queryRaw(
    `SELECT count(*)::int AS n,
            (count(*) FILTER (WHERE e.question_hash = $2))::int AS checked
       FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id
      WHERE g.user_id = $1 AND e.event_type = 'evidence'`,
    [USER_LOOP, checkHash],
  )) as { n: number; checked: number }[];
  expect(evidence[0].n).toBeGreaterThanOrEqual(answered + 1);
  expect(evidence[0].checked).toBeGreaterThanOrEqual(1);

  const closed = (await queryRaw(
    `SELECT close_json, close_phase FROM sessions WHERE user_id = $1 AND close_json IS NOT NULL`,
    [USER_LOOP],
  )) as { close_json: string; close_phase: string }[];
  expect(closed).toHaveLength(1);
  expect(closed[0].close_json).not.toContain("summary"); // ciphertext at rest
  expect(await decryptText(closed[0].close_json)).toContain(CLOSE_SUMMARY); // decrypts to the record

  const events = (await queryRaw(
    `SELECT DISTINCT event_type FROM events WHERE user_id = $1 AND event_type = ANY($2)`,
    [USER_LOOP, ["zpd.step", "learn.session_closed", "zpd.leak", "learn.probe_done", "learn.plan_approved"]],
  )) as { event_type: string }[];
  expect(events.map((e) => e.event_type).sort()).toEqual([
    "learn.plan_approved",
    "learn.probe_done",
    "learn.session_closed",
    "zpd.step",
  ]); // and NO zpd.leak

  // A15: the tier is chosen in code and recorded on every step.
  const tiers = (await queryRaw(
    `SELECT DISTINCT payload->>'tier' AS tier FROM events WHERE user_id = $1 AND event_type = 'zpd.step'`,
    [USER_LOOP],
  )) as { tier: string | null }[];
  expect(tiers.length).toBeGreaterThan(0);
  for (const t of tiers) expect(["lite", "standard", "deep", "none"]).toContain(t.tier);

  // The learn_loop oracle over THIS walk's rows (before the next test's truncate):
  // non-vacuous by --expect-loop-activity; evidence + zpd.step for the graded step;
  // no pre-release final-answer text in the decrypted transcript.
  const oracle = await runOracle(["--check", "learn_loop", "--expect-loop-activity"]);
  expect(oracle.findings, oracle.stderr).toEqual([]);
  expect(oracle.code).toBe(0);

  await context.close();
});

test("a reload mid-session resumes the same loop session and calls no probe route", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.goto("/learn");
  await walkProbeAndPlan(page, P);
  await firstTeachTurn(page);
  const phase = page.getByTestId("loop-phase");
  const sessionId = await phase.getAttribute("data-session-id");
  expect(sessionId).toBeTruthy();

  // A NEWER open legacy tutor session in the same offering (loop_state is the column
  // default '{}'): GET /sessions must keep it out before its limit, so the reload still
  // resumes the loop session, and the picker never lists the legacy row.
  const [{ offering_id: offeringId }] = (await queryRaw(`SELECT offering_id FROM sessions WHERE id = $1`, [
    sessionId,
  ])) as { offering_id: string }[];
  await queryRaw(
    `INSERT INTO sessions (id, user_id, mode, topic, offering_id, started_at)
     VALUES ('e2e-legacy-open', $1, 'socratic', 'A legacy tutor chat', $2, now() + interval '1 minute')`,
    [USER_LOOP, offeringId],
  );

  // spec §11.3: a reload of /learn mid-session never starts a probe.
  const afterReload: string[] = [];
  page.on("request", (r) => afterReload.push(new URL(r.url()).pathname));
  await page.reload();
  await expect(phase).toHaveAttribute("data-session-id", sessionId!);
  await expect(phase).toHaveAttribute("data-phase", "teach");
  await expectTurn(page, LOOP_TUTOR_REPLY); // restored via the resume route
  const listed = page.getByTestId(`loop-session-${sessionId}`);
  await expect(listed).toBeVisible(); // the picker lists it …
  await expect(listed).toHaveAttribute("aria-current", "true"); // … as the current one
  await expect(page.getByTestId("loop-session-e2e-legacy-open")).toHaveCount(0);
  expect(afterReload.some((p) => p.endsWith("/api/learn/loop/sessions"))).toBe(true);
  expect(
    afterReload.filter((p) => p.includes("/api/learn/loop/probe/") || p.includes("/api/learn/loop/start-session")),
  ).toEqual([]);

  // One open loop session in the database: the resume made none.
  const open = (await queryRaw(
    `SELECT id FROM sessions WHERE user_id = $1 AND mode <> 'review' AND close_json IS NULL
        AND ended_at IS NULL AND loop_state <> '{}'::jsonb`,
    [USER_LOOP],
  )) as { id: string }[];
  expect(open.map((r) => r.id)).toEqual([sessionId]);

  await context.close();
});

test("budget cap: tutor chat pauses on /learn; review still serves and grades on /study", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");

  // ── /learn: the tutor pauses (spec §3.5 hard level; §13 A20/A26) ─────────
  await page.goto("/learn");
  await expect(page.getByTestId("loop-phase")).toBeVisible(); // the loop tree, not the legacy one
  const banner = page.getByTestId("loop-budget-paused");
  // spec §13 A27: at the hard level PKG-07's opener is a template (tier none, no model call)
  // that carries the pause notice — never a 429 — so the banner shows AND the probe still
  // runs (spec §3.5: the probe keeps working at the hard level; grading has its own cap).
  await expect(banner).toBeVisible();
  await expect(page.getByTestId("loop-probe-item")).toBeVisible();
  await expect(banner).toContainText("Practice and review keep working");
  await expect(banner).toContainText("Tutor chat paused until"); // the daily copy (A39: not session-capped)
  expect(await banner.getAttribute("data-reset-at")).toBeTruthy();
  await expect(page.getByTestId("loop-budget-study-link")).toHaveAttribute("href", "/study?mode=cards");
  expect(await page.getByText("[e2e-function-model]").count()).toBe(0); // no model turn ran

  // ── /study: review keeps working at the hard level ───────────────────────
  await page.goto("/study?mode=cards");
  await expect(page.getByTestId("review-due-panel")).toBeVisible();
  await expect(page.getByTestId("review-item")).toContainText(CAPPED_CARD_FRONT);
  await page.getByTestId("review-flip").click();
  await page.getByTestId("review-rate-3").click();
  await expect(page.getByTestId("review-hint")).toBeVisible();
  await expect
    .poll(
      async () =>
        (
          (await queryRaw(
            `SELECT count(*)::int AS n FROM events WHERE user_id = $1 AND event_type = 'review.graded'`,
            [USER_CAPPED],
          )) as { n: number }[]
        )[0].n,
      { timeout: DB_POLL_TIMEOUT_MS },
    )
    .toBe(1);
  const card = (await queryRaw(`SELECT reps, due_at FROM flashcards WHERE id = $1`, [CAPPED_CARD_ID])) as {
    reps: number;
    due_at: string;
  }[];
  expect(Number(card[0].reps)).toBe(1);
  expect(new Date(card[0].due_at).getTime()).toBeGreaterThan(Date.now());

  await context.close();
});

// PKG-14b (spec §11.2, §11.4): the loop is every student's default — the
// build-phase "legacy user" split is gone (no journey depends on the retired
// staff/QA toggle; test_inv_13b).
test("every student gets the loop by default", async ({ page }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  const probe = page.waitForResponse((r) => r.url().includes("/api/learn/loop/review/active"));
  await page.goto("/learn");
  // The default fixture user is an ordinary seeded student (rich-user-active).
  const answered = await probe;
  expect(answered.status()).toBe(200);
  expect(await answered.json()).toEqual({ active: true });
  await expect(page.getByTestId("loop-phase")).toBeVisible();
  await expect(page.getByTestId("tutor-topic-picker")).toHaveCount(0);
  await expect(page.getByTestId("loop-status-error")).toHaveCount(0);
});

test("kill switch restores the legacy Learn screen", async ({ page }) => {
  test.skip(!killSwitchLane, "kill-switch lane only");
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
  });
  // The loop routes 404 (spec §7) — /status needs a session id; a fresh one is fine.
  const status = await page.request.get(
    `/api/learn/loop/status?user_id=${USER_ACTIVE}&session_id=e2e-kill-switch-probe`,
  );
  expect(status.status()).toBe(404);
  const probe = page.waitForResponse((r) => r.url().includes("/api/learn/loop/review/active"));
  await page.goto("/learn");
  // The probe ANSWERS the gate (200 {active: false}), so a legacy visit logs no error.4xx.
  const answered = await probe;
  expect(answered.status()).toBe(200);
  expect(await answered.json()).toEqual({ active: false });
  await expect(page.getByTestId("tutor-topic-picker")).toBeVisible();
  await expect(page.getByTestId("loop-phase")).toHaveCount(0);
  await expect(page.getByTestId("loop-status-error")).toHaveCount(0);
  const errors = (await queryRaw(
    `SELECT count(*)::int AS n FROM events
      WHERE event_type = 'error.4xx' AND payload->>'path' = '/api/learn/loop/review/active'`,
  )) as { n: number }[];
  expect(errors[0].n).toBe(0);
});

// UI regression coverage; the deterministic function model supplies all lesson
// and grading text. This exercises navigation/forms at a real phone width,
// rather than inferring mobile usability from the component's desktop tests.
test("phone learner can check in, answer a check and reach wrap-up without horizontal overflow", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/learn");
  const phase = page.getByTestId("loop-phase");
  await expect(page.getByRole("textbox", { name: "Check-in answer" })).toBeVisible();
  await expect(page.getByTestId("loop-tree-link")).toBeVisible();
  await expect(page.getByTestId("loop-rail")).toHaveCount(0);
  expect(await phase.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await walkProbeAndPlan(page, P);
  await firstTeachTurn(page);
  await page.getByTestId("loop-check-me").click();
  await expect(page.getByTestId("loop-check-prompt")).toBeVisible();
  await page.getByRole("textbox", { name: "Your answer", exact: true }).fill(`working: ${GRADER_CORRECT_TOKEN}`);
  await page.getByTestId("loop-attempt-submit").click();
  await expect(phase).toHaveAttribute("data-phase", "feedback");
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_BODY);
  expect(await phase.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.getByTestId("loop-close-button").click();
  await expect(page.getByTestId("loop-close-done")).toBeVisible();
  await expect(page.getByTestId("loop-close-study-link")).toHaveAttribute("href", "/study?mode=cards");
  await context.close();
});

test("a failed daily-review status read offers recovery without removing flashcards", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_CAPPED, "Casey Cap");
  let first = true;
  await page.route("**/api/learn/loop/review/active?*", async (route) => {
    if (first) {
      first = false;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporarily unavailable" }) });
    } else await route.continue();
  });
  await page.goto("/study?mode=cards");
  await expect(page.getByTestId("review-status-retry")).toBeVisible();
  await expect(page.getByText(CAPPED_CARD_FRONT, { exact: true })).toBeVisible();
  await page.getByTestId("review-status-retry").click();
  await expect(page.getByTestId("review-due-panel")).toBeVisible();
  await expect(page.getByTestId("review-status-retry")).toHaveCount(0);
  await context.close();
});

test("switching sessions cancels a pending tutor stream and retains the chosen session", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.goto("/learn");
  await walkProbeAndPlan(page, P);
  const phase = page.getByTestId("loop-phase");
  const original = await phase.getAttribute("data-session-id");
  expect(original).toBeTruthy();
  const [{ offering_id: offeringId }] = (await queryRaw("SELECT offering_id FROM sessions WHERE id = $1", [original])) as { offering_id: string }[];
  // A second genuinely open loop session, as another tab could have started.
  await queryRaw(
    `INSERT INTO sessions (id, user_id, mode, topic, offering_id, started_at, loop_state)
     VALUES ('e2e-loop-other-session', $1, 'socratic', 'Other session', $2, now() + interval '1 minute', '{"phase":"teach"}'::jsonb)`,
    [USER_LOOP, offeringId],
  );
  await page.reload();
  await expect(page.getByTestId("loop-session-e2e-loop-other-session")).toBeVisible();
  await page.getByTestId(`loop-session-${original}`).click();
  await expect(phase).toHaveAttribute("data-session-id", original!);
  let release = () => {};
  let entered = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  const requested = new Promise<void>((resolve) => { entered = resolve; });
  await page.route("**/api/learn/loop/chat/stream", async (route) => {
    entered();
    await held;
    try {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"type":"token","data":{"delta":"STALE_SESSION_FEEDBACK"}}\n\ndata: {"type":"done","data":{"reply":"STALE_SESSION_FEEDBACK","phase":"feedback","graph_update":{},"mastery_changes":[]}}\n\n',
      });
    } catch {
      // Chromium can discard the intercepted request after AbortController.
    }
  });
  await page.getByTestId("tutor-input").fill("Explain this concept");
  await page.getByTestId("tutor-send").click();
  await requested;
  const aborted = page.waitForEvent("requestfailed", (request) => request.url().includes("/api/learn/loop/chat/stream"));
  await page.getByTestId("loop-session-e2e-loop-other-session").click();
  expect((await aborted).failure()?.errorText).toContain("ERR_ABORTED");
  await expect(phase).toHaveAttribute("data-session-id", "e2e-loop-other-session");
  release();
  await expect(phase).toHaveAttribute("data-phase", "teach");
  await expect(page.getByText("STALE_SESSION_FEEDBACK", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
  await context.close();
});

test("a phone learner confirms a goal, sees prerequisite planning and retains it after reload", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/learn");
  const phase = page.getByTestId("loop-phase");
  await expect(page.getByTestId("loop-set-goal")).toBeEnabled();
  await page.getByTestId("loop-set-goal").click();
  const editor = page.getByRole("form", { name: "Learning goal" });
  const objective = "Understand how bitwise operators use binary numbers";
  await editor.getByRole("textbox", { name: /Your objective/ }).fill(objective);
  await expect(editor.getByTestId("loop-goal-save")).toBeDisabled(); // prose does not infer targets
  await editor.getByRole("checkbox", { name: "Bitwise Operators", exact: true }).check();
  const goalResponse = page.waitForResponse((response) => response.url().includes("/api/learn/loop/goal") && response.request().method() === "POST");
  await editor.getByTestId("loop-goal-save").click();
  const scoped = await (await goalResponse).json();
  expect(scoped.goal.text).toBe(objective);
  expect(scoped.goal.target_node_ids).toHaveLength(1);
  expect(scoped.goal_version).toBeGreaterThan(0);
  await expect(page.getByTestId("loop-goal-summary")).toContainText(objective);
  expect(await phase.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

  // Honest unknown answers produce foundational work; they do not pretend the
  // learner mastered the target just to make a goal-specific plan appear.
  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
    await expect(page.getByTestId("loop-probe-idk")).toBeVisible();
    await page.getByTestId("loop-probe-idk").click();
    answered += 1;
    await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" || await page.getByTestId("loop-probe-reference").isVisible()).toBe(true);
    if (await page.getByTestId("loop-probe-next").isVisible()) await page.getByTestId("loop-probe-next").click();
    await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" || await page.getByTestId("loop-probe-idk").isVisible()).toBe(true);
  }
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.getByTestId("loop-diagnosis")).toBeVisible();
  await expect(page.getByTestId("loop-diagnosis")).toContainText(/could not bound|not been independently assessed/);
  const prerequisite = page.locator('[data-testid^="loop-plan-concept-"]').filter({ hasText: "Binary Numbers" });
  await expect(prerequisite).toContainText("Prerequisite for your goal");
  await expect(page.locator('[data-testid^="loop-plan-concept-"]').filter({ hasText: "Two's Complement" })).toHaveCount(0);
  expect(await phase.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

  const sessionId = await phase.getAttribute("data-session-id");
  const [stored] = await queryRaw("SELECT loop_state FROM sessions WHERE id = $1", [sessionId]);
  expect(JSON.stringify(stored.loop_state)).not.toContain(objective); // goal prose is encrypted, IDs remain usable
  await page.reload();
  await expect(phase).toHaveAttribute("data-session-id", sessionId!);
  await expect(phase).toHaveAttribute("data-phase", "plan");
  await expect(page.getByTestId("loop-goal-summary")).toContainText(objective);
  await expect(prerequisite).toContainText("Prerequisite for your goal");
  const approval = page.waitForRequest((request) => request.url().includes("/api/learn/loop/plan/approve"));
  await page.getByTestId("loop-plan-approve").click();
  expect((await approval).postDataJSON().goal_version).toBe(scoped.goal_version);
  await expect(phase).toHaveAttribute("data-phase", "teach");
  await expect(page.getByTestId("loop-set-goal")).toHaveCount(0); // locked once teaching begins
  await context.close();
});

test("an earned hint arriving late cannot reopen a graded check in the same session", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  const P = await learningParams(["PROBE_SESSION_CAP", "GATE_INDEPENDENT_MIN_S_NOVICE"]);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  let actionStarted = false;
  await page.route("**/api/learn/loop/action", async (route) => {
    actionStarted = true;
    await held;
    try {
      await route.fulfill({ json: { reply: "OBSOLETE_HINT_FOR_GRADED_CHECK", phase: "hint", graph_update: {}, mastery_changes: [] } });
    } catch { /* the context may have closed after an earlier assertion */ }
  });
  try {
    await page.goto("/learn");
    await walkProbeAndPlan(page, P);
    await firstTeachTurn(page);
    await page.getByTestId("loop-check-me").click();
    await expect(page.getByTestId("loop-check-prompt")).toBeVisible();
    await page.getByTestId("loop-attempt-input").fill(WORKING_ATTEMPT);
    const hint = page.getByTestId("loop-hint-button");
    // The real attempt/dwell gate must grant the hint. Only its later text
    // response is held, modeling an in-flight action rather than bypassing help.
    await expect.poll(async () => {
      if (!actionStarted && await hint.isEnabled()) await hint.click();
      return actionStarted;
    }, { timeout: Number(P.GATE_INDEPENDENT_MIN_S_NOVICE) * 1000 + GATE_POLL_MARGIN_MS, intervals: [100, 500] }).toBe(true);
    await page.getByTestId("loop-attempt-idk").click();
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    const delivered = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/learn/loop/action");
    release();
    await (await delivered).finished();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("loop-continue")).toBeVisible();
    await expect(page.getByTestId("loop-check-prompt")).toHaveCount(0);
    await expect(page.getByText("OBSOLETE_HINT_FOR_GRADED_CHECK", { exact: true })).toHaveCount(0);
  } finally {
    release();
    await context.close();
  }
});

test("phone retention entry creates no pose until requested and respects real delayed eligibility", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  await page.setViewportSize({ width: 320, height: 844 });
  let opens = 0;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/learn/loop/posttest/start") opens += 1; });
  await page.goto("/study?mode=cards");
  await expect(page.getByTestId("retention-open")).toBeEnabled();
  expect(opens).toBe(0);
  const response = page.waitForResponse((result) => new URL(result.url()).pathname === "/api/learn/loop/posttest/start");
  await page.getByTestId("retention-open").click();
  const opened = await response;
  expect(opened.status()).toBe(200);
  // This freshly re-seeded learner has no aged evidence. Do not backdate it,
  // override the clock or manufacture a delayed-retention success.
  expect((await opened.json()).items).toEqual([]);
  await expect(page.getByTestId("retention-empty")).toContainText("eligible unseen");
  expect(opens).toBe(1);
  const geometry = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
  expect(geometry.content).toBeLessThanOrEqual(geometry.viewport);
  await context.close();
});

test("independent prerequisite recovery unlocks a fresh goal plan requiring approval in the same session", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  await seedGoalContinuationItems("diagnostic");
  const P = await learningParams(["PROBE_SESSION_CAP", "LOOP_CHECKS_PER_CONCEPT"]);
  expect(Number(P.LOOP_CHECKS_PER_CONCEPT)).toBe(2); // this fixture exercises recheck then independent alternate format
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  let approvals = 0;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/learn/loop/plan/approve") approvals += 1; });
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/learn");
    await expect(page.getByTestId("loop-set-goal")).toBeEnabled();
    await page.getByTestId("loop-set-goal").click();
    const editor = page.getByRole("form", { name: "Learning goal" });
    const objective = "Understand bitwise operations after checking binary foundations";
    await editor.getByTestId("loop-goal-text").fill(objective);
    await editor.getByRole("checkbox", { name: "Bitwise Operators", exact: true }).check();
    const goalResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/learn/loop/goal");
    await editor.getByTestId("loop-goal-save").click();
    const goal = await (await goalResponse).json();
    const phase = page.getByTestId("loop-phase");
    let missedFoundation = false;
    let answered = 0;
    while (await phase.getAttribute("data-phase") === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
      const probe = page.getByTestId("loop-probe-item");
      await expect(page.getByTestId("loop-probe-submit")).toBeVisible();
      const hash = await probe.getAttribute("data-question-hash");
      const difficulty = Number(await probe.getAttribute("data-difficulty"));
      const foundation = (await probe.textContent())?.includes("Binary Numbers") === true;
      const miss = foundation && difficulty === 3 && !missedFoundation;
      await page.getByTestId("loop-probe-input").fill(miss ? WORKING_ATTEMPT : GRADER_CORRECT_TOKEN);
      await page.getByTestId("loop-probe-submit").click();
      answered += 1;
      if (miss) missedFoundation = true;
      await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
        await page.getByTestId("loop-probe-reference").isVisible() ||
        (await probe.getAttribute("data-question-hash")) !== hash).toBe(true);
      if (await page.getByTestId("loop-probe-reference").isVisible()) {
        expect(miss).toBe(true);
        await page.getByTestId("loop-probe-next").click();
        await expect.poll(async () => (await phase.getAttribute("data-phase")) !== "probe" ||
          (await probe.getAttribute("data-question-hash")) !== hash).toBe(true);
      }
    }
    expect(missedFoundation).toBe(true);
    await expect(phase).toHaveAttribute("data-phase", "plan");
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-binary")).toContainText("Prerequisite for your goal");
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-bitwise")).toHaveCount(0);
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-twos")).toHaveCount(0);
    // Add fresh authored questions, never evidence. Only actual grader/writer
    // responses below may establish the independent recovery needed to unlock.
    await seedGoalContinuationItems("practice");
    const sessionId = await phase.getAttribute("data-session-id");
    await page.getByTestId("loop-plan-approve").click();
    await expect(phase).toHaveAttribute("data-phase", "teach");
    await firstTeachTurn(page);
    const hashes: string[] = [];
    for (const expectedFormat of ["free", "teachback"]) {
      await page.getByTestId("loop-check-me").click();
      const check = page.getByTestId("loop-check-prompt");
      await expect(check).toBeVisible();
      await expect(check).toHaveAttribute("data-format", expectedFormat);
      const hash = await check.getAttribute("data-question-hash");
      expect(hash).toBeTruthy();
      const rows = await queryRaw("SELECT difficulty FROM check_items WHERE question_hash = $1", [hash]);
      expect(Number(rows[0].difficulty)).toBe(3);
      hashes.push(hash!);
      await page.getByTestId("loop-attempt-input").fill(GRADER_CORRECT_TOKEN);
      await page.getByTestId("loop-attempt-submit").click();
      await expect(phase).toHaveAttribute("data-phase", "feedback");
      await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    }
    const [stored] = await queryRaw("SELECT loop_state FROM sessions WHERE id = $1 AND user_id = $2", [sessionId, USER_LOOP]) as {
      loop_state: { steps: Record<string, { goal_observation: Record<string, unknown> }> };
    }[];
    const first = stored.loop_state.steps[hashes[0]].goal_observation;
    const second = stored.loop_state.steps[hashes[1]].goal_observation;
    expect(first).toMatchObject({ same_session_recheck: true, independent: false, difficulty: 3 });
    expect(second).toMatchObject({ same_session_recheck: false, independent: true, max_rung: 0, previously_seen: false, difficulty: 3 });
    const continued = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/learn/loop/check/next");
    await page.getByTestId("loop-check-me").click();
    expect(await (await continued).json()).toMatchObject({ phase: "plan", plan_done: false, goal_progress: { status: "continue_available" } });
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-bitwise")).toContainText("Your selected goal");
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-binary")).toHaveCount(0);
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-twos")).toHaveCount(0);
    expect(approvals).toBe(1); // a fresh frontier never silently approves itself
    await page.reload();
    await expect(phase).toHaveAttribute("data-session-id", sessionId!);
    await expect(page.getByTestId("loop-goal-summary")).toContainText(objective);
    await expect(page.getByTestId("loop-plan-concept-rich-node-loop-bitwise")).toBeVisible();
    const approved = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/learn/loop/plan/approve");
    await page.getByTestId("loop-plan-approve").click();
    expect((await approved).postDataJSON()).toMatchObject({ goal_version: goal.goal_version, concept_ids: ["rich-node-loop-bitwise"] });
    await expect(phase).toHaveAttribute("data-phase", "teach");
    await expect(page.getByTestId("loop-teach-start")).toContainText("Bitwise Operators");
    await firstTeachTurn(page);
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    const [active] = await queryRaw("SELECT loop_state->>'concept' AS concept FROM sessions WHERE id = $1 AND user_id = $2", [sessionId, USER_LOOP]);
    expect(active.concept).toBe("rich-node-loop-bitwise");
    expect(approvals).toBe(2);
  } finally { await context.close(); }
});

test("a new goal session respects an earlier helped prerequisite miss even when its check-in omits that prerequisite", async ({ browser }) => {
  test.skip(killSwitchLane, "loop path: default lane only");
  test.setTimeout(LOOP_JOURNEY_TIMEOUT_MS);
  // Entirely synthetic inputs, installed before activity. Every subsequent
  // attempt, hint, grade, posterior and session transition uses real app routes.
  await seedGoalContinuationItems("readiness");
  const P = await learningParams([
    "PROBE_SESSION_CAP", "PROBE_MAX_SKILLS", "BKT_PROFICIENT",
    "GATE_INDEPENDENT_MIN_S_NOVICE",
  ]);
  expect(Number(P.PROBE_MAX_SKILLS)).toBe(3); // the three targets intentionally fill the check-in
  const binary = "rich-node-loop-binary";
  const bitwise = "rich-node-loop-bitwise";
  const twos = "rich-node-loop-twos";
  // The sanctioned graph writer chooses the independent fixture node's ID.
  const placeValueRows = await queryRaw(
    "SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = 'rich-course-cs101' AND concept_name = 'Binary Place Value'",
    [USER_LOOP],
  );
  expect(placeValueRows).toHaveLength(1);
  const placeValue = String(placeValueRows[0].id);
  const { context, page } = await signIn(browser, USER_LOOP, "Lou Loop");
  const phase = page.getByTestId("loop-phase");

  async function setTargets(names: string[], text: string) {
    await expect(page.getByTestId("loop-set-goal")).toBeEnabled();
    await page.getByTestId("loop-set-goal").click();
    const editor = page.getByRole("form", { name: "Learning goal" });
    await editor.getByTestId("loop-goal-text").fill(text);
    // New sessions begin coursewide, so selection order is the explicit order
    // confirmed by this learner. Do not rely on alphabetical graph ordering.
    for (const name of names) await editor.getByRole("checkbox", { name, exact: true }).check();
    const response = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/goal");
    await editor.getByTestId("loop-goal-save").click();
    const saved = await response;
    expect(saved.status()).toBe(200);
    const goal = await saved.json();
    await expect(editor).toBeHidden();
    await expect(page.getByTestId("loop-goal-summary")).toContainText(text);
    return goal;
  }

  async function completeCheckIn(correct: boolean) {
    const item = page.getByTestId("loop-probe-item");
    let answered = 0;
    while (await phase.getAttribute("data-phase") === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
      await expect(page.getByTestId("loop-probe-submit")).toBeVisible();
      const hash = await item.getAttribute("data-question-hash");
      const result = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/probe/answer");
      if (correct) {
        await page.getByTestId("loop-probe-input").fill(GRADER_CORRECT_TOKEN);
        await page.getByTestId("loop-probe-submit").click();
      } else {
        await page.getByTestId("loop-probe-idk").click();
      }
      const graded = await result;
      expect(graded.status()).toBe(200);
      expect(await graded.json()).toMatchObject({ graded: true, correct });
      answered += 1;
      await expect.poll(async () => await phase.getAttribute("data-phase") !== "probe" ||
        await page.getByTestId("loop-probe-reference").isVisible() ||
        await item.getAttribute("data-question-hash") !== hash).toBe(true);
      if (await page.getByTestId("loop-probe-reference").isVisible()) {
        await page.getByTestId("loop-probe-next").click();
        await expect.poll(async () => await phase.getAttribute("data-phase") !== "probe" ||
          await item.getAttribute("data-question-hash") !== hash).toBe(true);
      }
    }
    expect(answered).toBeGreaterThan(0);
    await expect(phase).toHaveAttribute("data-phase", "plan");
  }

  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/learn");
    await setTargets(["Binary Numbers"], "Check binary foundations first");
    await completeCheckIn(true);
    await expect(page.getByTestId(`loop-plan-concept-${binary}`)).toBeVisible();
    await expect(page.getByTestId(`loop-plan-concept-${bitwise}`)).toHaveCount(0);
    // Add questions only, using the existing sanctioned asset fixture at the
    // real plan. No new learner state, releases or history are installed.
    await seedGoalContinuationItems("practice");
    await page.getByTestId("loop-plan-approve").click();
    await expect(phase).toHaveAttribute("data-phase", "teach");
    await firstTeachTurn(page);
    const firstSession = await phase.getAttribute("data-session-id");
    expect(firstSession).toBeTruthy();
    await page.getByTestId("loop-check-me").click();
    const check = page.getByTestId("loop-check-prompt");
    await expect(check).toBeVisible();
    await expect(check).toHaveAttribute("data-format", "free");
    const hash = await check.getAttribute("data-question-hash");
    expect(hash).toBeTruthy();
    const [asset] = await queryRaw("SELECT difficulty FROM check_items WHERE question_hash = $1", [hash]);
    expect(Number(asset.difficulty)).toBe(3);

    // Earn each actual rung with new work and normal server dwell gates. Poll
    // denials only; once a rung grants, wait for its real hint action to finish.
    for (const rung of [1, 2]) {
      await page.getByTestId("loop-attempt-input").fill(`${WORKING_ATTEMPT}; revision ${rung}`);
      const button = page.getByTestId("loop-hint-button");
      const hintActions: Response[] = [];
      const captureHintAction = (response: Response) => {
        if (new URL(response.url()).pathname !== "/api/learn/loop/action" || response.request().method() !== "POST") return;
        const body = response.request().postDataJSON();
        if (body.session_id === firstSession && body.user_id === USER_LOOP && body.action_type === "hint") hintActions.push(response);
      };
      page.on("response", captureHintAction);
      try {
        let granted: number | undefined;
        await expect.poll(async () => {
          if (granted !== undefined) return granted; // never grant another rung while checking this one
          await expect(button).toBeEnabled();
          const response = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/hint");
          await button.click();
          const gate = await response;
          expect(gate.status()).toBe(200);
          expect(gate.request().postDataJSON()).toMatchObject({ session_id: firstSession, user_id: USER_LOOP, question_hash: hash });
          const result = await gate.json();
          if (typeof result.rung === "number") granted = result.rung;
          await expect(button).toBeEnabled();
          return granted ?? 0;
        }, { timeout: Number(P.GATE_INDEPENDENT_MIN_S_NOVICE) * 1000 + GATE_POLL_MARGIN_MS,
          intervals: [100, 500, 1_000] }).toBe(rung);
        await expect.poll(() => hintActions.length).toBe(1);
        expect(hintActions[0].status()).toBe(200);
        const served = await hintActions[0].json();
        expect(served).toMatchObject({ phase: "hint", learner_state: expect.arrayContaining([expect.objectContaining({ node_id: binary })]) });
        expect(typeof served.reply).toBe("string");
        expect(served.reply.trim().length).toBeGreaterThan(0);
        await expect(check).toHaveAttribute("data-question-hash", hash!);
        // H1 may use the asset's deterministic source anchor and H2 its hint
        // question. Assert the actual served response, not a generic model body.
        await expect(page.getByTestId("loop-hint-reply")).toHaveText(served.reply);
      } finally {
        page.off("response", captureHintAction);
      }
    }
    const submitted = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learn/loop/check/answer/stream");
    await page.getByTestId("loop-attempt-input").fill(WORKING_ATTEMPT);
    await page.getByTestId("loop-attempt-submit").click();
    expect((await submitted).status()).toBe(200);
    await expect(phase).toHaveAttribute("data-phase", "feedback");
    await expect(page.getByTestId("tutor-stop")).toHaveCount(0);
    const [failure] = await queryRaw(
      `SELECT e.correct, e.assisted, e.max_rung, e.planning_observation, l.p_known
         FROM node_mastery_events e JOIN graph_nodes g ON g.id = e.node_id
         JOIN learner_state l ON l.node_id = g.id AND l.user_id = g.user_id
        WHERE g.user_id = $1 AND e.node_id = $2 AND e.question_hash = $3 AND e.event_type = 'evidence'`,
      [USER_LOOP, binary, hash],
    );
    expect(failure).toMatchObject({ correct: false, assisted: true, max_rung: 2,
      planning_observation: { node_id: binary, question_hash: hash, difficulty: 3,
        correct: false, assisted: true, max_rung: 2, independent: false,
        synthetic_idk: false, previously_seen: false, same_session_recheck: false } });
    expect(Number(failure.p_known)).toBeGreaterThan(Number(P.BKT_PROFICIENT));
    await page.getByTestId("loop-close-button").click();
    await expect(phase).toHaveAttribute("data-phase", "close");
    await page.getByTestId("loop-new-session").click();
    await expect(phase).toHaveAttribute("data-phase", "probe");
    await expect.poll(async () => {
      const id = await phase.getAttribute("data-session-id");
      return !!id && id !== firstSession;
    }).toBe(true);
    const secondSession = await phase.getAttribute("data-session-id");
    expect(secondSession).toBeTruthy();
    expect(secondSession).not.toBe(firstSession);
    const objective = "Work toward bitwise and two's complement with place value review";
    const goal = await setTargets(["Bitwise Operators", "Two's Complement", "Binary Place Value"], objective);
    expect(goal.goal.target_node_ids).toEqual([bitwise, twos, placeValue]);
    await completeCheckIn(false);

    // This fresh check-in cannot itself explain the prerequisite block: none
    // of its observations concerns Binary. The earlier journal must supply it.
    const current = await page.request.get(`/api/learn/loop/plan?${new URLSearchParams({
      user_id: USER_LOOP, session_id: secondSession!,
    })}`);
    expect(current.status()).toBe(200);
    const plan = await current.json();
    expect(plan.goal).toEqual(goal.goal);
    expect(plan.goal_version).toBe(goal.goal_version);
    // The full goal scope still honestly lists the prerequisite as untested;
    // it is absent from the three served strands, not erased from the scope.
    expect(plan.diagnosis.skills.find((s: { node_id: string }) => s.node_id === binary))
      .toMatchObject({ status: "untested", observations: 0, independent_observations: 0 });
    const [second] = await queryRaw("SELECT loop_state->'probe' AS probe FROM sessions WHERE id = $1 AND user_id = $2", [secondSession, USER_LOOP]) as {
      probe: { skills: string[]; history: { node_id: string }[] };
    }[];
    expect(second.probe.skills).toEqual([bitwise, twos, placeValue]);
    expect(second.probe.history.length).toBeGreaterThan(0);
    expect(second.probe.history.map((row) => row.node_id)).not.toContain(binary);
    const [stillHigh] = await queryRaw("SELECT p_known FROM learner_state WHERE user_id = $1 AND node_id = $2", [USER_LOOP, binary]);
    expect(Number(stillHigh.p_known)).toBeGreaterThan(Number(P.BKT_PROFICIENT));
    expect(plan.concepts.map((c: { node_id: string }) => c.node_id)).not.toContain(bitwise);
    expect(plan.goal_progress.unresolved_prerequisite_ids).toContain(binary);
    await expect(page.getByTestId(`loop-plan-concept-${binary}`)).toContainText("Prerequisite for your goal");
    await expect(page.getByTestId(`loop-plan-concept-${bitwise}`)).toHaveCount(0);
    await page.reload();
    await expect(phase).toHaveAttribute("data-session-id", secondSession!);
    await expect(page.getByTestId("loop-goal-summary")).toContainText(objective);
    await expect(page.getByTestId(`loop-plan-concept-${binary}`)).toBeVisible();
    await expect(page.getByTestId(`loop-plan-concept-${bitwise}`)).toHaveCount(0);
    // Neither closing nor opening another session erased the immutable miss.
    const rows = await queryRaw("SELECT planning_observation FROM node_mastery_events WHERE node_id = $1 AND question_hash = $2 AND event_type = 'evidence'", [binary, hash]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ planning_observation: failure.planning_observation });
  } finally { await context.close(); }
});
