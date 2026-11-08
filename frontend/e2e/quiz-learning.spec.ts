/**
 * The quiz in the learning system (learning-loop spec §13 A143–A147), with
 * its flags turned on for one seeded student each (`setUserFlag`; every flag
 * ships off, and off the quiz is byte-identical — the other quiz specs).
 *
 *   plan, planned, gated, routed   the home proposes from the learner model
 *                                  and says why; the planned questions pass
 *                                  the item gates and are evidence; the
 *                                  results show the skill meter and the next
 *                                  step, and the screen stays accessible.
 *   a plain quiz under the gates   unchecked questions are practice: served,
 *                                  scored, never evidence.
 *   a "Sure" wrong answer          on a verified question's tagged distractor
 *                                  records the misconception under the quiz
 *                                  item id.
 *
 * Function mode: the planned writer, the concept check and the blind solve
 * answer from `backend/agents/function_handlers_e2e.py` (`_e2e_planned`,
 * `_quiz_check_handler`): a planned question's key is
 * `E2E_CHECK_ITEM_FINAL_ANSWER` at the position `E2E_QUIZ_CORRECT_LABELS`
 * gives its slot (B, C, A), and its first distractor carries the slot's TARGET.
 */
import type { Browser, Page } from "@playwright/test";
import { expectAccessible } from "./support/a11y";
import { queryRaw, setUserFlag } from "./support/db";
import { expect, test } from "./support/fixtures";
import {
  CONCEPT_NAME,
  CORRECT_LABELS,
  GENERATE_TIMEOUT,
  NODE_ID,
  QUIZ_LENGTH,
  SUBMIT_TIMEOUT,
  answerAtEnd,
  expectResults,
  openQuizHome,
  preAckDisclaimer,
  startQuiz,
} from "./support/quiz";
import { PREFS_KEY } from "@/lib/quiz/session";
import { mintStorageState } from "./support/session";
import { USER_ACTIVE, USER_LOOP } from "./support/stack";

const QUIZ_FLAGS = [
  "quiz_concept_plan",
  "quiz_planned_questions",
  "quiz_item_gates",
  "quiz_misconceptions",
  "quiz_results_routing",
] as const;

/** The planned E2E stem (`function_handlers_e2e.py::E2E_PLANNED_STEM`). */
const plannedStem = (n: number, concept: string) =>
  `E2E planned question ${n} [e2e-function-model][${concept}]: what does the learning rate control?`;

/** The loop user's seeded concept whose check items carry the key `wrong_token`. */
const LOOP_NODE_ID = "rich-node-loop-binary";
const LOOP_CONCEPT = "Binary Numbers";
const LOOP_KEY = "wrong_token";

async function flagsOn(userId: string, keys: readonly string[]): Promise<void> {
  for (const key of keys) await setUserFlag(key, userId, "on");
}

/** A three-question, adaptive quiz: the plan is three QUESTION lines (the
 *  planned writer answers each), and the learner model picks the difficulty. */
async function adaptiveThree(page: Page): Promise<void> {
  await page.addInitScript(
    ([key]) => {
      window.localStorage.setItem(key, JSON.stringify({ count: 3, difficulty: "adaptive", feedback: "at-end" }));
    },
    [PREFS_KEY],
  );
}

async function startPlanned(page: Page, concept: string): Promise<void> {
  const start = page.getByTestId("quiz-start");
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({ timeout: GENERATE_TIMEOUT });
  await expect(page.getByTestId("quiz-panel")).toContainText(plannedStem(1, concept), {
    timeout: GENERATE_TIMEOUT,
  });
}

async function answerPlanned(page: Page, concept: string, labels: string[], from = 1): Promise<void> {
  for (const [i, label] of labels.entries()) {
    await expect(page.getByTestId("quiz-panel")).toContainText(plannedStem(from + i, concept), {
      timeout: GENERATE_TIMEOUT,
    });
    await page.getByTestId(`quiz-answer-option-${label}`).click();
    await page.getByTestId("quiz-submit-answer").click();
  }
}

async function eventPayloads(userId: string, type: string): Promise<Record<string, unknown>[]> {
  const rows = await queryRaw("SELECT payload FROM events WHERE user_id = $1 AND event_type = $2 ORDER BY created_at", [
    userId,
    type,
  ]);
  return rows.map(r => r.payload as Record<string, unknown>);
}

async function signIn(browser: Browser, userId: string, name: string): Promise<Page> {
  const context = await browser.newContext({ storageState: await mintStorageState(userId, name) });
  const page = await context.newPage();
  await preAckDisclaimer(page);
  return page;
}

test("plan, planned, gated, routed: the learner model chooses, the gates verify, the results route on", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await flagsOn(USER_ACTIVE, ["quiz_concept_plan", "quiz_planned_questions", "quiz_item_gates", "quiz_results_routing"]);
  await preAckDisclaimer(page);
  await adaptiveThree(page);

  // ── A143: the home's suggestion is the learner model's, and it says why ──
  await openQuizHome(page, "/quiz");
  await expect(page.getByTestId("quiz-plan-reason")).toContainText("Skill meter:", { timeout: SUBMIT_TIMEOUT });

  // ── A144 + A145: the planned questions, verified ──────────────────────────
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startPlanned(page, CONCEPT_NAME);
  await answerPlanned(page, CONCEPT_NAME, [...CORRECT_LABELS]);
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(`${QUIZ_LENGTH} of ${QUIZ_LENGTH} correct`, {
    timeout: SUBMIT_TIMEOUT,
  });

  const [gated] = await eventPayloads(USER_ACTIVE, "quiz.items_gated");
  expect(gated).toMatchObject({ questions: QUIZ_LENGTH, verified: QUIZ_LENGTH, aligned: QUIZ_LENGTH, key_agreed: QUIZ_LENGTH });
  const evidence = await queryRaw(
    "SELECT correct, channel FROM node_mastery_events WHERE node_id = $1 AND event_type = 'evidence' ORDER BY created_at, evidence_seq",
    [NODE_ID],
  );
  expect(evidence.map(e => [e.correct, e.channel])).toEqual(Array(QUIZ_LENGTH).fill([true, "mc"]));

  // ── A147: what changed, and where to go next ─────────────────────────────
  const block = page.getByTestId("quiz-results-learning");
  await expect(block).toBeVisible();
  await expect(block.getByTestId("quiz-results-change").first()).toContainText(`${CONCEPT_NAME}: rose from`);
  await expect(block.getByTestId("quiz-results-due")).toBeVisible();
  const learn = block.getByTestId("quiz-next-step-learn");
  await expect(learn).toHaveAttribute("href", /^\/learn\?topic=/);
  await expectAccessible(page, "quiz results with the learning block");
});

test("a plain quiz under the gates is practice: served and scored, never evidence", async ({ page }) => {
  test.setTimeout(120_000);
  await flagsOn(USER_ACTIVE, ["quiz_item_gates"]);
  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startQuiz(page);
  await answerAtEnd(page, CORRECT_LABELS.map((label, i) => ({ n: i + 1, label })));
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(`${QUIZ_LENGTH} of ${QUIZ_LENGTH} correct`, {
    timeout: SUBMIT_TIMEOUT,
  });
  // No passages in function mode and no option the scripted solve can read:
  // every key unsolved, every question practice, nothing written.
  const [gated] = await eventPayloads(USER_ACTIVE, "quiz.items_gated");
  expect(gated).toMatchObject({ questions: QUIZ_LENGTH, practice: QUIZ_LENGTH, key_unsolved: QUIZ_LENGTH });
  const excluded = await eventPayloads(USER_ACTIVE, "quiz.evidence_excluded");
  expect(excluded.map(p => p.excluded_by)).toEqual(Array(QUIZ_LENGTH).fill(["key_unsolved"]));
  const evidence = await queryRaw(
    "SELECT 1 FROM node_mastery_events WHERE node_id = $1 AND event_type = 'evidence'",
    [NODE_ID],
  );
  expect(evidence).toHaveLength(0);
});

test('a "Sure" wrong answer on a tagged distractor records the misconception', async ({ browser }) => {
  test.setTimeout(180_000);
  await flagsOn(USER_LOOP, QUIZ_FLAGS);
  const page = await signIn(browser, USER_LOOP, "Lou Loop");
  await adaptiveThree(page);
  await openQuizHome(page, `/quiz?concept=${LOOP_NODE_ID}`);
  await startPlanned(page, LOOP_CONCEPT);

  // Question 1 targets the concept's vetted key; its first distractor (A)
  // embodies it. Chosen with "Sure": a held misconception, not a guess.
  await page.getByTestId("quiz-confidence-sure").click();
  await page.getByTestId("quiz-answer-option-A").click();
  await page.getByTestId("quiz-submit-answer").click();
  await answerPlanned(page, LOOP_CONCEPT, [CORRECT_LABELS[1], CORRECT_LABELS[2]], 2);
  await expectResults(page);

  const rows = await queryRaw(
    `SELECT m.wrong_key, m.check_item_id, m.count, m.resolved_at, a.question_hash
       FROM misconceptions m JOIN misconception_attempts a ON a.misconception_id = m.id
      WHERE m.user_id = $1 AND m.node_id = $2`,
    [USER_LOOP, LOOP_NODE_ID],
  );
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({ wrong_key: LOOP_KEY, count: 1, resolved_at: null });
  expect(rows[0].check_item_id).toBe(`quiz:${rows[0].question_hash}`);
  const [recorded] = await eventPayloads(USER_LOOP, "quiz.misconception_recorded");
  expect(recorded).toMatchObject({ node_id: LOOP_NODE_ID, wrong_key: LOOP_KEY, count: 1 });
  await page.context().close();
});
