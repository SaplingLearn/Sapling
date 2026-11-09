/**
 * Journeys (learning-loop spec §13 A140, A141) — varied practice, both flags
 * default off and turned on per student through `feature_flag_targets`
 * (support/db.ts::setUserFlag):
 *
 *  1. drafting — with upload_prereq_edges, varied_isomorphs and
 *     multi_concept_items on for the uploader, an upload drafts each concept's
 *     items with a surface descriptor (the representation in plaintext, the
 *     context encrypted, a different surface per item) and the combination of
 *     the apex "Learning Rate" with its prerequisite "Gradient Descent" (the
 *     scripted relation) under its own key, apex and components;
 *  2. the cue-familiarity dial — after the student answered S, the next check
 *     on the concept poses T2 (a surface not met) over T1 (S's surface, the
 *     older item) with varied_isomorphs on, and T1 with it off (the plain
 *     order, unchanged);
 *  3. the ideas-combined dial — once the student has answered the
 *     prerequisite and the apex right this session (each component proficient
 *     with a strong unassisted answer: the seeded 0.99 prior is a test input,
 *     the strong answers are earned here), the apex's next check poses the
 *     combination, once; its answer is a WEIGHT_MULTI_CONCEPT observation on
 *     the apex, and `learn.multi_concept_served` records the pose.
 *
 * Function mode (SAPLING_MODEL_MODE=function with agents.function_handlers_e2e):
 * the drafter, alignment and key-check handlers script every model call; the
 * grader marks an answer carrying E2E_GRADER_CORRECT_TOKEN correct. Journeys 2
 * and 3 drive the REAL routes (POST /api/learn/loop/check/next and
 * /check/answer) on synthetic assets written by the app's own writers
 * (scripts/seed_learning_varied_practice.py) and read the database back.
 */
import type { APIRequestContext, Browser, Page } from "@playwright/test";
import path from "node:path";

import { queryRaw, seedVariedPractice, setUserFlag } from "./support/db";
import { decryptTexts } from "./support/decrypt";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { learningParams } from "./support/params";
import { mintStorageState } from "./support/session";
import { BACKEND_URL, FRONTEND_URL, USER_ACTIVE, USER_LOOP } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const FIXTURE_NAME = "upload-journey.pdf";
/** Must match backend/agents/function_handlers_e2e.py::E2E_CHECK_ITEM_SURFACES */
const E2E_SURFACES: [string, string][] = [
  ["verbal", "e2e lecture recap"],
  ["applied", "e2e training run"],
  ["numeric", "e2e step sizes"],
  ["visual", "e2e loss curve"],
];
/** Must match backend/agents/function_handlers_e2e.py::E2E_GRADER_CORRECT_TOKEN */
const GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT";
/** learning/multi_concept.py::SEP — the ASCII unit separator a combination's key joins with */
const SEP = "\u001f";

test.skip(killSwitchLane, "the learning loop is off in the kill-switch lane");

async function expectFunctionMode(): Promise<void> {
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as { model_mode?: string };
  expect(health.model_mode, "the stack must run the deterministic model seam").toBe("function");
}

async function uploadFixture(page: Page): Promise<string> {
  await page.goto("/library");
  const uploadButton = page.getByTestId("library-upload");
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();
  await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);
  await expect(page.getByTestId("upload-modal-file-row-0")).toBeVisible();
  await page.getByTestId("upload-modal-submit").click();
  await expect(page.getByTestId("upload-modal-done")).toBeVisible({ timeout: 60_000 });
  const docs = (await queryRaw(
    "SELECT id FROM documents WHERE file_name = $1 AND deleted_at IS NULL",
    [FIXTURE_NAME],
  )) as { id: string }[];
  expect(docs).toHaveLength(1);
  return docs[0].id;
}

async function loopContext(browser: Browser) {
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Loop Learner") });
  return context;
}

type Pose = { question_hash: string; prompt: string; format: string; difficulty: number };

async function checkNext(request: APIRequestContext, sessionId: string): Promise<Pose> {
  const res = await request.post(`${FRONTEND_URL}/api/learn/loop/check/next`, {
    data: { session_id: sessionId, user_id: USER_LOOP },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const body = (await res.json()) as { check: Pose | null };
  expect(body.check, "a check is posed").toBeTruthy();
  return body.check as Pose;
}

async function answerRight(request: APIRequestContext, sessionId: string, pose: Pose): Promise<void> {
  const res = await request.post(`${FRONTEND_URL}/api/learn/loop/check/answer`, {
    data: {
      session_id: sessionId,
      user_id: USER_LOOP,
      question_hash: pose.question_hash,
      answer: `${GRADER_CORRECT_TOKEN} the step size along the gradient`,
    },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const body = (await res.json()) as { graded?: boolean; verdict?: string };
  expect(body.graded).toBe(true);
  expect(body.verdict).toBe("correct");
}

test("an upload with the varied-practice flags on drafts surfaces and the combination (A140, A141)", async ({
  page,
}) => {
  await expectFunctionMode();
  for (const flag of ["upload_prereq_edges", "varied_isomorphs", "multi_concept_items"]) {
    await setUserFlag(flag, USER_ACTIVE, "on");
  }
  const docId = await uploadFixture(page);

  // A140: every item of the upload's concepts states its surface — the
  // representation in plaintext, the context encrypted — a different one per item
  const items = (await queryRaw(
    `SELECT concept_key, surface_representation, surface_context
       FROM check_items
      WHERE $1 = ANY(source_document_ids) AND apex_key IS NULL
      ORDER BY concept_key, created_at, id`,
    [docId],
  )) as { concept_key: string; surface_representation: string | null; surface_context: string | null }[];
  expect(items.length).toBeGreaterThan(0);
  expect(new Set(items.map((i) => i.concept_key))).toEqual(new Set(["gradient descent", "learning rate"]));
  for (const item of items) {
    expect(item.surface_representation).not.toBeNull();
    expect(item.surface_context).not.toBeNull();
    expect(E2E_SURFACES.map(([, c]) => c)).not.toContain(item.surface_context); // ciphertext at rest
  }
  const contexts = await decryptTexts(items.map((i) => i.surface_context as string));
  const surfaces = items.map((i, n) => [i.surface_representation, contexts[n]]);
  for (const s of surfaces) expect(E2E_SURFACES).toContainEqual(s);
  for (const concept of ["gradient descent", "learning rate"]) {
    const mine = surfaces.filter((_, n) => items[n].concept_key === concept).map((s) => s.join("|"));
    expect(new Set(mine).size).toBe(mine.length); // no two of a concept's items share a surface
  }

  // A141: the combination of the apex with its prerequisite, under its own key
  const combos = (await queryRaw(
    `SELECT concept_key, apex_key, component_keys, format, difficulty
       FROM check_items
      WHERE $1 = ANY(source_document_ids) AND apex_key IS NOT NULL
      ORDER BY format`,
    [docId],
  )) as { concept_key: string; apex_key: string; component_keys: string[]; format: string; difficulty: number }[];
  const P = await learningParams(["MULTI_CONCEPT_DIFFICULTY", "MULTI_CONCEPT_ITEMS_PER_COMBO"]);
  expect(combos).toHaveLength(Number(P.MULTI_CONCEPT_ITEMS_PER_COMBO));
  for (const combo of combos) {
    expect(combo.apex_key).toBe("learning rate");
    expect(combo.component_keys).toEqual(["learning rate", "gradient descent"]);
    expect(combo.concept_key).toBe(`learning rate${SEP}gradient descent`);
    expect(combo.difficulty).toBe(Number(P.MULTI_CONCEPT_DIFFICULTY));
  }
  expect(combos.map((c) => c.format).sort()).toEqual(["free", "mc_reason", "teachback"]);
});

for (const varied of [true, false]) {
  test(`the next check prefers an unmet surface only with varied_isomorphs on (A140, ${varied ? "on" : "off"})`, async ({
    browser,
  }) => {
    await expectFunctionMode();
    if (varied) await setUserFlag("varied_isomorphs", USER_LOOP, "on");
    const seeded = (await seedVariedPractice("varied")) as {
      session_id: string;
      hashes: { S: string; T1: string; T2: string };
    };
    const context = await loopContext(browser);
    try {
      const first = await checkNext(context.request, seeded.session_id);
      expect(first.question_hash).toBe(seeded.hashes.S); // the oldest; no surface met yet
      await answerRight(context.request, seeded.session_id, first);
      const second = await checkNext(context.request, seeded.session_id);
      // on: T2, whose surface the student has not met; off: T1, the plain order
      expect(second.question_hash).toBe(varied ? seeded.hashes.T2 : seeded.hashes.T1);
    } finally {
      await context.close();
    }
  });
}

test("a proficient student is posed the combination once and its answer is a partial observation on the apex (A141)", async ({
  browser,
}) => {
  await expectFunctionMode();
  await setUserFlag("multi_concept_items", USER_LOOP, "on");
  const seeded = (await seedVariedPractice("multi")) as {
    session_id: string;
    pre_node: string;
    apex_node: string;
    combo_hashes: string[];
  };
  const P = await learningParams(["WEIGHT_MULTI_CONCEPT", "LOOP_CHECKS_PER_CONCEPT"]);
  const context = await loopContext(browser);
  try {
    // the prerequisite's checks, then the apex's first: single-concept items
    for (let n = 0; n < Number(P.LOOP_CHECKS_PER_CONCEPT) + 1; n += 1) {
      const pose = await checkNext(context.request, seeded.session_id);
      expect(seeded.combo_hashes).not.toContain(pose.question_hash);
      await answerRight(context.request, seeded.session_id, pose);
    }
    // the apex's next check: the combination (two ideas, the session's rotation)
    const combo = await checkNext(context.request, seeded.session_id);
    expect(seeded.combo_hashes).toContain(combo.question_hash);
    expect(combo.prompt).toContain("[e2e-multi][combo]");
    await answerRight(context.request, seeded.session_id, combo);

    const rows = (await queryRaw(
      `SELECT node_id, correct, weight, assisted, max_rung, multi_concept
         FROM node_mastery_events
        WHERE question_hash = $1 AND event_type = 'evidence'`,
      [combo.question_hash],
    )) as {
      node_id: string;
      correct: boolean;
      weight: number;
      assisted: boolean;
      max_rung: number;
      multi_concept: boolean | null;
    }[];
    expect(rows).toHaveLength(1);
    expect(rows[0].node_id).toBe(seeded.apex_node);
    expect(rows[0].correct).toBe(true);
    expect(rows[0].weight).toBeCloseTo(Number(P.WEIGHT_MULTI_CONCEPT), 12);
    // the journal says a combination graded the row (its own item row may go later)
    expect(rows[0].multi_concept).toBe(true);
    const singles = (await queryRaw(
      `SELECT count(*)::int AS n FROM node_mastery_events
        WHERE node_id = ANY($1::text[]) AND event_type = 'evidence'
          AND question_hash <> $2 AND multi_concept IS NOT NULL`,
      [[seeded.pre_node, seeded.apex_node], combo.question_hash],
    )) as { n: number }[];
    expect(singles[0].n).toBe(0); // every single-concept row journals NULL, as before
    // the events writer flushes in the background: poll for the served event
    const served = async () =>
      (await queryRaw(
        "SELECT payload FROM events WHERE event_type = 'learn.multi_concept_served' AND user_id = $1",
        [USER_LOOP],
      )) as { payload: { question_hash: string; components: number } }[];
    await expect.poll(async () => (await served()).length, { timeout: 15_000 }).toBe(1);
    expect((await served())[0].payload.question_hash).toBe(combo.question_hash);
    expect((await served())[0].payload.components).toBe(2);
    const session = (await queryRaw("SELECT loop_state FROM sessions WHERE id = $1", [seeded.session_id])) as {
      loop_state: { steps: Record<string, { multi_concept?: boolean; node_id: string }> };
    }[];
    expect(session[0].loop_state.steps[combo.question_hash].multi_concept).toBe(true);
    expect(session[0].loop_state.steps[combo.question_hash].node_id).toBe(seeded.apex_node);
  } finally {
    await context.close();
  }
});
