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
import type { Browser, Page } from "@playwright/test";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
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

/** Probe → plan → approve (shared by the journeys). Returns how many probe items were answered. */
async function walkProbeAndPlan(page: Page, P: Params): Promise<number> {
  const phase = page.getByTestId("loop-phase");
  await expect(phase).toHaveAttribute("data-phase", "probe");
  const probeItem = page.getByTestId("loop-probe-item");
  await expect(probeItem).toContainText(LOOP_PROBE_PROMPT);

  let answered = 0;
  while ((await phase.getAttribute("data-phase")) === "probe" && answered < Number(P.PROBE_SESSION_CAP)) {
    const qh = await probeItem.getAttribute("data-question-hash");
    await page.getByTestId("loop-probe-input").fill(GRADER_CORRECT_TOKEN);
    await page.getByTestId("loop-probe-submit").click();
    answered += 1;
    // A correct answer shows no reference card: the server serves a different item
    // or moves the session to the plan. Wait for either.
    await expect
      .poll(async () => {
        if ((await phase.getAttribute("data-phase")) !== "probe") return true;
        if (!(await probeItem.isVisible())) return false;
        const now = await probeItem.getAttribute("data-question-hash");
        return now !== null && now !== qh;
      })
      .toBe(true);
    await expect(page.getByTestId("loop-probe-reference")).toHaveCount(0);
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
    "BKT_L0",
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
  await page.getByTestId("loop-attempt-submit").click();
  const body = JSON.parse((await submitted).postData() ?? "{}");
  expect(body).toMatchObject({ question_hash: checkHash, idk: false, answer: `working: ${GRADER_CORRECT_TOKEN}` });
  await expect(phase).toHaveAttribute("data-phase", "feedback");
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_BODY);
  await expect(page.getByTestId("loop-messages")).toContainText(LOOP_FEEDBACK_QUESTION);
  const learner = page.getByTestId("loop-learner-state");
  await expect.poll(async () => Number(await learner.getAttribute("data-p-known"))).toBeGreaterThan(Number(P.BKT_L0));

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
  expect(Math.max(...states.map((s) => Number(s.p_known)))).toBeGreaterThan(Number(P.BKT_L0));

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
