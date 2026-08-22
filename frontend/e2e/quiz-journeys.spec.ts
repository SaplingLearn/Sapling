/**
 * The behaviours the #537 quiz redesign added, driven end to end.
 *
 * `quiz.spec.ts` next door pins the four BACKEND contracts (mastery, failed
 * generation, resubmit, config mirroring). This file pins what the redesign is
 * actually FOR — the things the old screen either could not do or did wrongly:
 *
 *   resume                  a quiz you walked away from is offered back, at the
 *                           question you left it on (R-3).
 *   leave-and-return        the one door out saves the attempt and comes back
 *                           to where the quiz was launched from (R-10).
 *   ask-without-abandoning  the tutor opens OVER the question instead of
 *                           navigating to /learn and throwing the attempt away
 *                           (R-6) — the single worst behaviour of the old screen.
 *   missed review           the results screen can explain a wrong answer and
 *                           start a focused re-practice (R-5).
 *   entry points            each link shape arrives in the state it promised (§6).
 *   exits                   nothing lands on /learn; every way out is deliberate
 *                           (R-10).
 *   keyboard                the whole quiz is playable without a mouse (§5 B2).
 *
 * ── THE GENERATION BUDGET (read before adding a test) ─────────────────────
 *
 * `POST /api/quiz/generate` is rate limited per user, in-process
 * (`services/quiz_config.py::QUIZ_GENERATE_RATE_LIMIT`, enforced at
 * routes/quiz.py via `services/request_limits.check_rate_limit`). The limiter
 * is a module-level dict, so the per-test TRUNCATE + re-seed does NOT reset it
 * and the whole lane — every spec, every worker — shares ONE window that only
 * a backend restart clears.
 *
 * Production allows 8 per 300s, which the combined quiz lane blew through in
 * its first full run: D3's specs sort before this one, so the last four tests
 * here 429'd with a failure that reads as "answer options never appeared".
 * `scripts/e2e-up.sh` and `e2e.yml` now export `QUIZ_GENERATE_RATE_LIMIT=1000`
 * for the E2E stacks (#537) — a function-mode generation is a scripted
 * constant that costs nothing — so the ceiling is no longer the binding
 * constraint. Keep real generations deliberate anyway: each one is a full
 * round trip, and a stubbed `page.route` response is seconds faster. That is
 * why the four exit destinations are still asserted from the runs that already
 * reach those screens rather than from four runs of their own:
 *
 *   Back to your tree  → the leave-and-return journey
 *   Back to dashboard  → the ask-without-abandoning journey
 *   Done → /quiz       → the keyboard journey (route) + the Done test (query)
 *   Cancel             → its own test (quiz home only, no generation)
 *
 * Fixture constants, the function-mode contract note and the shared gestures
 * live in `support/quiz.ts`.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { USER_ACTIVE } from "./support/stack";
import {
  CONCEPT_NAME,
  CORRECT_LABELS,
  COURSE_CODE_CS,
  COURSE_ID_CS,
  GENERATE_TIMEOUT,
  NODE_ID,
  QUIZ_LENGTH,
  STREAM_TIMEOUT,
  SUBMIT_TIMEOUT,
  TUTOR_REPLY,
  answerAsYouGo,
  answerAtEnd,
  appAttempts,
  chooseAndSubmit,
  expectLocation,
  expectOnQuestion,
  expectPathname,
  expectResults,
  explanationOf,
  focusedTestId,
  locationContaining,
  openQuizHome,
  optionTextOf,
  preAckDisclaimer,
  startQuiz,
  stemOf,
  tabUntilFocused,
  wrongLabelFor,
} from "./support/quiz";

/** The whole scripted quiz, answered correctly, in `at-end` order. */
const ALL_CORRECT = CORRECT_LABELS.map((label, i) => ({ n: i + 1, label }));

/** Where a tree-sourced quiz says it came from (§6, Tree.tsx::onQuiz). */
const TREE_RETURN = `/tree?node=${NODE_ID}`;
const TREE_ENTRY =
  `/quiz?concept=${NODE_ID}&from=tree&return=${encodeURIComponent(TREE_RETURN)}`;
/** …and a dashboard-sourced one (§6, Dashboard.tsx's quiz CTAs). */
const DASHBOARD_ENTRY =
  `/quiz?concept=${NODE_ID}&from=dashboard&return=${encodeURIComponent("/dashboard")}`;

/** Mirrors `lib/quiz/session.ts`'s QUEUE_COUNT / QUEUE_MAX (R-4). */
const QUEUE_COUNT = 3;
const QUEUE_MAX = 5;

/** The `mastery_tier` values `graph_service.get_recommendations` proposes. */
const DUE_TIERS = ["struggling", "learning", "unexplored"];

/** The envelope `/api/quiz/generate` ships on a 502 (services/quiz_errors.py). */
const GENERATION_FAILED_BODY = JSON.stringify({
  error: {
    code: "QUIZ_GENERATION_FAILED",
    message: "Stubbed by the E2E lane's generation budget.",
    request_id: "e2e-stubbed-generation",
  },
  detail: "Stubbed by the E2E lane's generation budget.",
  request_id: "e2e-stubbed-generation",
});

type SeedNode = {
  id: string;
  concept_name: string;
  course_id: string | null;
  mastery_score: number;
  mastery_tier: string;
  times_studied: number;
};

/**
 * The ranking quiz home renders, derived from the database rather than
 * restated as a literal.
 *
 * This is the same rule `lib/quiz/proposals.ts` mirrors from
 * `graph_service.get_recommendations` (tier ∈ struggling/learning/unexplored,
 * `mastery_score` asc, id as the tie-break, primary prefers a concept actually
 * studied). Deriving it here means the arrival-state assertions below pin the
 * MIRROR against real data — if the client rule ever drifts from the backend's,
 * these counts stop agreeing.
 */
async function proposalsFromDb() {
  const rows = ((await queryRaw(
    `SELECT id, concept_name, course_id, mastery_score, mastery_tier, times_studied
       FROM graph_nodes
      WHERE user_id = $1`,
    [USER_ACTIVE],
  )) as Record<string, unknown>[]).map(r => ({
    id: String(r.id),
    concept_name: String(r.concept_name),
    course_id: r.course_id === null ? null : String(r.course_id),
    mastery_score: Number(r.mastery_score),
    mastery_tier: String(r.mastery_tier),
    times_studied: Number(r.times_studied ?? 0),
  })) as SeedNode[];

  const due = rows
    .filter(n => DUE_TIERS.includes(n.mastery_tier))
    .sort((a, b) => a.mastery_score - b.mastery_score || a.id.localeCompare(b.id));

  return {
    due,
    count: due.length,
    courseCount: new Set(due.map(n => n.course_id).filter(Boolean)).size,
    primary: due.find(n => n.times_studied > 0) ?? due[0],
    inCourse: (courseId: string) => due.filter(n => n.course_id === courseId),
  };
}

// ── 1. Resume ──────────────────────────────────────────────────────────────

test("resume: an unfinished quiz is offered back at the question it was left on, and Discard hides it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startQuiz(page);

  // One answer in — recorded server-side as it happens (R-2), which is what
  // makes the strip's count come off the attempt rather than off localStorage.
  await answerAtEnd(page, [ALL_CORRECT[0]]);
  await expectOnQuestion(page, 2);

  // Walk away and come back to quiz home.
  await openQuizHome(page, "/quiz");
  const strip = page.getByTestId("quiz-resume-strip");
  await expect(strip).toBeVisible({ timeout: SUBMIT_TIMEOUT });
  await expect(strip).toContainText(
    `You left a quiz on ${CONCEPT_NAME} — 1 of ${QUIZ_LENGTH} answered`,
  );

  await page.getByTestId("quiz-resume").click();
  // Back on the FIRST UNANSWERED item, not at the start.
  await expectOnQuestion(page, 2);

  // The rail agrees: three questions, and "here" is the second one.
  // `ProgressDots` gives the dots no testids (they are a picture of the aria
  // label); its class names are the primitive's public API, contract §3.
  // Question one's ANSWERED state is deliberately not asserted here — the
  // dedicated resume test below owns that expectation.
  const rail = page.getByTestId("quiz-progress");
  await expect(rail).toHaveAttribute("aria-label", `Question 2 of ${QUIZ_LENGTH}`);
  const dots = rail.locator(".progress-dots__dot");
  await expect(dots).toHaveCount(QUIZ_LENGTH);
  await expect(dots.nth(1)).toHaveClass(/progress-dots__dot--current/);
  await expect(dots.nth(2)).toHaveClass(/progress-dots__dot--todo/);

  // Discard is client-side only — there is no abandon endpoint (R-3, gap G4).
  await openQuizHome(page, "/quiz");
  await expect(strip).toBeVisible({ timeout: SUBMIT_TIMEOUT });
  await page.getByTestId("quiz-resume-discard").click();
  await expect(strip).toHaveCount(0);
  await expect(page.getByTestId("quiz-proposal")).toBeVisible();

  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  // Hidden, not abandoned: the row is still open, waiting for the 24h sweep.
  expect(attempts[0].completed_at).toBeNull();
  expect(attempts[0].abandoned_at).toBeNull();
});

/**
 * REGRESSION GUARD — a resumed quiz used to forget everything the server does
 * not store. Fixed by `c3580e95` (#537 A2); this rode in as `test.fixme` and
 * is now live. The diagnosis is kept because it is what the test is watching.
 *
 * R-3 makes localStorage the only home for the half of a session the backend
 * has never heard of: the verdicts (the resume payload carries `is_correct`
 * but no `correct_index` and no explanation), the scope and queue, and the
 * ORIGIN. `machine.ts::resumeFrom` reads all of it off the stored record.
 *
 * The record used to be gone by the time Resume was pressed. Mounting quiz
 * home starts a fresh `home`-phase session, and `useQuizSession`'s config
 * effect applies `SET_CONFIG` as soon as `GET /api/quiz/config` resolves;
 * `apply` persists every accepted event, and `session.ts::persistSession`
 * CLEARED storage for any phase outside the live set — `home` included. So the
 * first thing quiz home did was delete the resume record it was about to
 * offer. `persistSession` now saves or does nothing; only SUBMITTED and EXIT
 * clear (§4).
 *
 * What never broke (and is asserted green above) is everything the server
 * knows: the attempt is found through `GET /api/quiz/attempts`, the strip
 * counts the recorded responses, and Resume lands on the first unanswered
 * question. What was lost is invisible until you look for it — which is what
 * this test does, on the two symptoms that are actually observable:
 *
 *   1. the rail shows question one as unanswered (no verdict came back);
 *   2. the origin falls back to the URL, so a quiz launched from the
 *      dashboard exits to the tree.
 *
 * Symptom 2 is MASKED on a tree-sourced quiz, because the nav fallback
 * (`exits.ts::returnToSource` → `/tree?node=<conceptId>`) happens to produce
 * the same label and the same destination the tree entry would have. A
 * dashboard entry is the case that tells them apart, which is why this test
 * uses one.
 */
test(
  "#537: a resumed quiz restores the verdicts and the origin it was left with",
  async ({ page }) => {
    test.setTimeout(180_000);
    await preAckDisclaimer(page);
    await openQuizHome(page, DASHBOARD_ENTRY);
    await startQuiz(page);
    await answerAtEnd(page, [ALL_CORRECT[0]]);
    await expectOnQuestion(page, 2);

    await openQuizHome(page, "/quiz");
    await page.getByTestId("quiz-resume").click();
    await expectOnQuestion(page, 2);

    // 1. The verdict for question one came back with the session, so the rail
    //    can say it is answered.
    const dots = page.getByTestId("quiz-progress").locator(".progress-dots__dot");
    await expect(dots.nth(0)).toHaveClass(/progress-dots__dot--done/);

    // 2. …and so did the origin.
    await answerAtEnd(page, ALL_CORRECT.slice(1));
    await expectResults(page);
    const back = page.getByTestId("quiz-back-to-source");
    await expect(back).toHaveText("Back to dashboard");
    await back.click();
    await expectLocation(page, "/dashboard");
  },
);

// ── 2. Leave and return ────────────────────────────────────────────────────

test("leave-and-return: leaving saves the attempt, lands on the entry source, and the quiz can be finished from there", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);

  await openQuizHome(page, TREE_ENTRY);
  await expect(page.getByTestId("quiz-proposal")).toContainText("From your tree");
  await startQuiz(page);
  await answerAtEnd(page, [ALL_CORRECT[0]]);
  await expectOnQuestion(page, 2);

  // The ONE door out of a live attempt.
  await page.getByTestId("quiz-leave").click();
  const dialog = page.getByTestId("quiz-leave-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "Your answers so far are saved. You can pick it up again from Quiz home.",
  );
  await page.getByTestId("quiz-leave-confirm").click();

  // Back where the link came from — the tree, focused on the concept (§6/C1).
  await expectLocation(page, TREE_RETURN);
  await expect(page.getByRole("button", { name: "Quick quiz" })).toBeVisible({
    timeout: SUBMIT_TIMEOUT,
  });
  await expect(page.getByRole("heading", { level: 2, name: CONCEPT_NAME }).first()).toBeVisible();

  // Return through quiz home (arriving as plain nav) and pick it back up.
  await openQuizHome(page, "/quiz");
  await page.getByTestId("quiz-resume").click();
  await expectOnQuestion(page, 2);
  await answerAtEnd(page, ALL_CORRECT.slice(1));
  await expectResults(page);

  // This run also carries the "Back to your tree" EXIT (R-10): the secondary
  // exit names the tree and lands on the concept that was quizzed. NOTE it
  // does not prove the tree ORIGIN survived the round trip — the nav fallback
  // produces the identical label and destination. The dashboard-entry resume
  // test above owns that distinction.
  const backToSource = page.getByTestId("quiz-back-to-source");
  await expect(backToSource).toHaveText("Back to your tree");
  await backToSource.click();
  await expectLocation(page, TREE_RETURN);

  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  expect(attempts[0].completed_at).not.toBeNull();
  expect(Number(attempts[0].total)).toBe(QUIZ_LENGTH);
});

// ── 3. Ask about this, without abandoning the attempt ──────────────────────

test("ask-without-abandoning: the tutor opens over the question, streams, closes, and the quiz finishes intact", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await preAckDisclaimer(page);
  // Entered from the dashboard, so this run also carries the "Back to
  // dashboard" exit at the end (R-10).
  await openQuizHome(page, DASHBOARD_ENTRY);

  // "Ask about this" needs a verdict, so this runs in as-you-go — chosen the
  // way a student would, through the Adjust dialog, which starts in one press.
  await page.getByTestId("quiz-adjust").click();
  const adjust = page.getByTestId("quiz-adjust-dialog");
  await expect(adjust).toBeVisible();
  await page.getByTestId("quiz-seg-feedback-as-you-go").click();
  await expect(adjust).toContainText(
    "After each answer you'll see whether it was right and which answer was correct, before moving on.",
  );
  await page.getByTestId("quiz-adjust-start").click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({
    timeout: GENERATE_TIMEOUT,
  });
  await expectOnQuestion(page, 1);

  // Get it wrong on purpose.
  const chosen = wrongLabelFor(1);
  const correct = CORRECT_LABELS[0];
  await chooseAndSubmit(page, chosen);
  const verdict = page.getByTestId("quiz-review-verdict");
  await expect(verdict).toContainText(`Not quite — the answer is ${correct}.`, {
    timeout: SUBMIT_TIMEOUT,
  });
  await expect(verdict).toContainText(explanationOf(1, correct));

  await page.getByTestId("quiz-ask").click();
  const sheet = page.getByTestId("quiz-ask-panel");
  await expect(sheet).toBeVisible();

  // The seed IS the contract with the tutor (R-6): the stem, both answers and
  // the explanation, composed on screen and sent as the first message.
  const seed = page.getByTestId("quiz-ask-seed");
  await expect(seed).toContainText(stemOf(1));
  await expect(seed).toContainText(`You chose ${chosen} ·`);
  await expect(seed).toContainText(optionTextOf(1, chosen));
  await expect(seed).toContainText(`The answer is ${correct} ·`);
  await expect(seed).toContainText(optionTextOf(1, correct));
  await expect(seed).toContainText(explanationOf(1, correct));

  // The streamed reply, byte-for-byte the function-mode constant.
  await expect(sheet).toContainText(TUTOR_REPLY, { timeout: STREAM_TIMEOUT });

  await page.getByTestId("quiz-ask-panel-close").click();
  await expect(sheet).toHaveCount(0);

  // THE POINT: the question is exactly as it was left — same item, same
  // choice, same verdict. The old screen navigated away and lost all of it.
  await expectOnQuestion(page, 1);
  await expect(verdict).toContainText(`Not quite — the answer is ${correct}.`);
  await expect(page.getByTestId(`quiz-answer-option-${chosen}`)).toHaveAttribute(
    "aria-checked",
    "true",
  );

  // …and the attempt finishes normally from there.
  await page.getByTestId("quiz-next").click();
  await answerAsYouGo(page, 2, CORRECT_LABELS[1], "Correct.");
  await answerAsYouGo(page, 3, CORRECT_LABELS[2], "Correct.");
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(
    `${QUIZ_LENGTH - 1} of ${QUIZ_LENGTH} correct`,
    { timeout: SUBMIT_TIMEOUT },
  );

  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  expect(attempts[0].completed_at).not.toBeNull();
  expect(Number(attempts[0].score)).toBe(QUIZ_LENGTH - 1);

  // The dashboard exit (R-10): a quiz reached from the dashboard says so, and
  // goes back there rather than to the tree — or, as before #537, to /learn.
  const back = page.getByTestId("quiz-back-to-source");
  await expect(back).toHaveText("Back to dashboard");
  await back.click();
  await expectLocation(page, "/dashboard");
});

// ── 4. The missed-question review ──────────────────────────────────────────

test("missed review: the results screen explains the wrong answer and asks for a focused re-practice", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startQuiz(page);

  const chosen = wrongLabelFor(1);
  const correct = CORRECT_LABELS[0];
  const submitResponse = page.waitForResponse(
    r => r.url().includes("/api/quiz/submit") && r.request().method() === "POST",
  );
  await answerAtEnd(page, [
    { n: 1, label: chosen },
    ALL_CORRECT[1],
    ALL_CORRECT[2],
  ]);
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(
    `${QUIZ_LENGTH - 1} of ${QUIZ_LENGTH} correct`,
    { timeout: SUBMIT_TIMEOUT },
  );
  // Not a clean sweep, so no "nothing to review" line.
  await expect(page.getByTestId("quiz-results-perfect")).toHaveCount(0);

  // The row's testid suffix is `SubmitResult.results[].question_id`, which only
  // the wire knows — read it off the response rather than guessing, which also
  // pins `MissedList.buildMissedItems`' string/number join.
  const scored = (await (await submitResponse).json()) as {
    results: { question_id: string; correct: boolean }[];
  };
  const missedIds = scored.results.filter(r => !r.correct).map(r => String(r.question_id));
  expect(missedIds).toHaveLength(1);
  const questionId = missedIds[0];

  const list = page.getByTestId("quiz-missed-list");
  await expect(list).toContainText("One to look at");
  const item = page.getByTestId(`quiz-missed-${questionId}`);
  await expect(item).toContainText(stemOf(1));
  await expect(item).toContainText(`You chose ${chosen} · the answer is ${correct}`);

  // The explanation is a disclosure — present in the DOM (so `aria-controls`
  // never dangles) but hidden until asked for.
  const explain = page.getByTestId(`quiz-missed-explain-${questionId}`);
  const explanation = item.locator(`#quiz-missed-explanation-${questionId}`);
  await expect(explain).toHaveText("Show explanation");
  await expect(explain).toHaveAttribute("aria-expanded", "false");
  await expect(explanation).toBeHidden();
  await explain.click();
  await expect(explain).toHaveText("Hide explanation");
  await expect(explain).toHaveAttribute("aria-expanded", "true");
  await expect(explanation).toHaveText(explanationOf(1, correct));
  await explain.click();
  await expect(explanation).toBeHidden();

  // The same tutor sheet the question screen opens, seeded from this row.
  await page.getByTestId(`quiz-missed-ask-${questionId}`).click();
  const sheet = page.getByTestId("quiz-ask-panel");
  await expect(sheet).toBeVisible();
  await expect(page.getByTestId("quiz-ask-seed")).toContainText(stemOf(1));
  await expect(page.getByTestId("quiz-ask-seed")).toContainText(`You chose ${chosen} ·`);
  await page.getByTestId("quiz-ask-panel-close").click();
  await expect(sheet).toHaveCount(0);

  // R-5: "practise the one you missed" is a NEW attempt on the same concept,
  // one question, same difficulty. (No endpoint re-serves a specific question
  // — gap G5 — so what the client ASKS FOR is the whole of the contract.)
  //
  // The request is stubbed rather than served: the assertion is on the request
  // the client makes, which is where R-5 actually lives, and the stubbed 502
  // then exercises the mapped-copy path on the way out. (The E2E stacks raise
  // the generate limiter — see the header — so this is hermeticity, not budget.)
  await page.route("**/api/quiz/generate", route =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: GENERATION_FAILED_BODY,
    }),
  );
  const generateRequest = page.waitForRequest(
    r => r.url().includes("/api/quiz/generate") && r.method() === "POST",
  );
  const practise = page.getByTestId("quiz-practise-missed");
  await expect(practise).toHaveText("Practise the one you missed");
  await practise.click();
  const body = (await generateRequest).postDataJSON() as {
    concept_node_id: string;
    num_questions: number;
    difficulty: string;
    include_answer_key: boolean;
  };
  expect(body.concept_node_id).toBe(NODE_ID);
  expect(body.num_questions).toBe(1);
  expect(body.difficulty).toBe("medium");
  expect(body.include_answer_key).toBe(false);

  await expect(page.getByTestId("quiz-error")).toBeVisible({ timeout: GENERATE_TIMEOUT });
  await expect(page.getByTestId("quiz-error")).toContainText(
    "We couldn't put a quiz together for this concept right now. Try again in a moment.",
  );
  // The stub really did stand in for the route: no second attempt row exists.
  expect(await appAttempts()).toHaveLength(1);
});

// ── 5. Entry points ────────────────────────────────────────────────────────

test("entry points: each link shape arrives in the state it promised", async ({ page }) => {
  test.setTimeout(180_000);
  const ranking = await proposalsFromDb();
  expect(ranking.count, "the rich seed has concepts worth proposing").toBeGreaterThan(0);

  await preAckDisclaimer(page);

  // (a) The tree's node panel — driven through the real page and the real
  //     link, so `Tree.tsx::onQuiz`'s href is under test too (§6).
  await page.goto(`/tree?node=${NODE_ID}`);
  await page.getByRole("button", { name: "Quick quiz" }).click();
  const arrived = new URLSearchParams(
    (await locationContaining(page, `concept=${NODE_ID}`)).split("?")[1] ?? "",
  );
  expect(arrived.get("from")).toBe("tree");
  expect(arrived.get("return")).toBe(TREE_RETURN);
  let proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toBeVisible({ timeout: SUBMIT_TIMEOUT });
  await expect(proposal).toContainText(CONCEPT_NAME);
  await expect(proposal).toContainText("From your tree");

  // (b) A tree SUBJECT ROOT — practise the course, as a queue (R-4).
  const csDue = ranking.inCourse(COURSE_ID_CS);
  expect(csDue.length, "CS101 has concepts due").toBeGreaterThan(0);
  await openQuizHome(page, `/quiz?course=${COURSE_ID_CS}&from=tree`);
  proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toContainText(`Practice ${COURSE_CODE_CS}`);
  await expect(proposal).toContainText(`${Math.min(csDue.length, QUEUE_MAX)} concepts due`);
  await expect(proposal).toContainText(`${QUEUE_COUNT} questions each`);

  // (c) The dashboard's "Review what's due".
  await openQuizHome(page, "/quiz?scope=due&from=dashboard");
  proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toContainText("Review everything due");
  await expect(proposal).toContainText(
    `${ranking.count} concepts across ${ranking.courseCount} courses · ` +
      `starting with the ${Math.min(ranking.count, QUEUE_MAX)} weakest`,
  );

  // (d) A note.
  await openQuizHome(page, `/quiz?concept=${NODE_ID}&from=notes&note=rich-note-cs-1`);
  proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toContainText(CONCEPT_NAME);
  await expect(proposal).toContainText("From your note");

  // (e) Plain nav — no target, so the ranked primary is the offer. The name is
  //     derived from the database through the same rule the client mirrors.
  await openQuizHome(page, "/quiz");
  await expect(page.getByTestId("quiz-home")).toContainText("Ready for you");
  await expect(page.getByTestId("quiz-proposal")).toContainText(ranking.primary.concept_name);
});

// ── 6. Exits ───────────────────────────────────────────────────────────────
//
// The other three destinations ride on the runs that already reach them (one
// journey per destination keeps the lane short): "Back to your tree" on
// leave-and-return, "Back to dashboard" on ask-without-abandoning, and
// "Done → /quiz" on the keyboard pass. Cancel is the one that needs no quiz.

test("exits: Cancel honours the entry source, and falls back to the dashboard without one", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await preAckDisclaimer(page);

  await openQuizHome(page, TREE_ENTRY);
  await page.getByTestId("quiz-cancel").click();
  await expectLocation(page, TREE_RETURN);

  // Cancelling out of a quiz you never started, with nowhere to go back to,
  // lands on the dashboard — never on the tree you didn't come from (§5 B1.8),
  // and never on /learn, which is where every pre-#537 exit went.
  await openQuizHome(page, "/quiz");
  await page.getByTestId("quiz-cancel").click();
  await expectLocation(page, "/dashboard");
});

// ── 7. Keyboard only ───────────────────────────────────────────────────────

test("keyboard: the whole quiz is playable without a mouse", async ({ page }) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);

  // Start is reachable by Tab and activates on Enter.
  await tabUntilFocused(page, "quiz-start");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({
    timeout: GENERATE_TIMEOUT,
  });
  await expectOnQuestion(page, 1);
  // The question screen takes focus itself, which is what makes the shortcuts
  // audible before the student has clicked anything.
  await expect.poll(() => focusedTestId(page), { timeout: SUBMIT_TIMEOUT }).toBe("quiz-panel");

  // Escape is the leave door, and "Keep going" is the focused default.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("quiz-leave-dialog")).toBeVisible();
  await expect
    .poll(() => focusedTestId(page), { timeout: SUBMIT_TIMEOUT })
    .toBe("quiz-leave-cancel");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("quiz-leave-dialog")).toHaveCount(0);
  // …and it hands the keyboard back to the quiz.
  await expect.poll(() => focusedTestId(page), { timeout: SUBMIT_TIMEOUT }).toBe("quiz-panel");

  // 1–6 choose, Enter submits. The correct labels B, C, A are options 2, 3, 1.
  const digits = ["2", "3", "1"];
  for (let i = 0; i < QUIZ_LENGTH; i++) {
    await expectOnQuestion(page, i + 1);
    await page.keyboard.press(digits[i]);
    await expect(page.getByTestId(`quiz-answer-option-${CORRECT_LABELS[i]}`)).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await page.keyboard.press("Enter");
  }

  // at-end mode, so the last Enter scores the attempt outright.
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText(
    `${QUIZ_LENGTH} of ${QUIZ_LENGTH} correct`,
    { timeout: SUBMIT_TIMEOUT },
  );

  // This run also carries the "Done" exit (R-10): back to quiz home, with no
  // stale results underneath. The ROUTE is asserted here; that the deep link's
  // query is dropped with it is a separate claim, owned by the test below.
  await tabUntilFocused(page, "quiz-done");
  await page.keyboard.press("Enter");
  await expectPathname(page, "/quiz");
  await expect(page.getByTestId("quiz-home")).toBeVisible();
  await expect(page.getByTestId("quiz-results")).toHaveCount(0);
});

/**
 * REGRESSION GUARD — "Done" used to leave the deep link behind. It took three
 * attempts, and each one failed HERE, on this lane, in a different way; the two
 * assertions below are one per failure mode, which is why both are kept.
 *
 * R-10 is "Done → `/quiz`".
 *
 *  1. `router.push("/quiz")` — no movement. `/quiz?concept=<id>` → `/quiz` is
 *     route-tree-identical (only client-side search params differ), which App
 *     Router resolves to a no-op and never commits.
 *  2. `router.replace(...)` (`c3580e95`) — no movement either, same reason.
 *  3. `window.history.replaceState(window.history.state, …)` (`4a80da2d`) —
 *     URL clean, CARD still pinned to the finished concept. Next patches the
 *     History API and bails out of its own hook on its own state:
 *
 *         if (data?.__NA || data?._N) return originalReplaceState(data, _, url)
 *
 *     (`next/dist/client/components/app-router.js`, 16.2.9 — the guard that
 *     stops Next's internal navigations looping.) `window.history.state` is the
 *     state Next itself wrote, `__NA: true` and all, so the address bar moved
 *     while `applyUrlFromHistoryPushReplace(url)` never ran and
 *     `useSearchParams()` kept returning `?concept=`. `QuizScreen:49-50` derives
 *     `entry` from `searchParams.toString()`, so the card stayed on the concept
 *     just finished.
 *  4. `window.history.replaceState(null, …)` (`4048a793`) — green, both halves.
 *     `copyNextJsInternalHistoryState` copies `__NA` and
 *     `__PRIVATE_NEXTJS_INTERNALS_TREE` off the current entry itself, so passing
 *     null preserves exactly what passing the live state was trying to preserve
 *     by hand — and the router sync runs.
 *
 * So: assert the URL (fails for #1-#2) AND the card (fails for #3). A future
 * regression in either half is then named rather than guessed at.
 *
 * ON COMPARING THE CARD TO THE DATABASE — two assertions were tried here and
 * both were unsound, so they are written down rather than repeated. A 3/3 run
 * moves the quizzed concept's mastery AND its `times_studied`, and the ranking
 * rule on both sides (`proposals.ts::primaryOf`, this file's `proposalsFromDb`)
 * is "weakest STUDIED concept, else weakest overall". So:
 *
 *   - reading the ranking BEFORE the quiz compares the screen against a
 *     snapshot the quiz has since invalidated;
 *   - "the card is not the concept just finished" is false by design — once
 *     the student studies it, that concept legitimately becomes the primary;
 *   - reading the ranking after the quiz but WITHOUT a reload compares fresh
 *     DB rows against a screen still rendering the graph copy it fetched at
 *     mount, before the quiz.
 *
 * The reload settles all three: it remounts, so both sides rank the same rows.
 */
test("#537: Done drops the deep link and returns a clean quiz home", async ({ page }) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await startQuiz(page);
  await answerAtEnd(page, ALL_CORRECT);
  await expectResults(page);

  await page.getByTestId("quiz-done").click();
  await expectLocation(page, "/quiz");
  await expect(page.getByTestId("quiz-home")).toBeVisible();
  await expect(page.getByTestId("quiz-results")).toHaveCount(0);

  // Then RELOAD, which is the harm the deep link actually did: home used to
  // come back on the finished concept because the query was still in the URL.
  // It is also the only honest place to compare the card against the database —
  // a reload remounts, so home re-fetches the graph and both sides then rank
  // the SAME rows. (Without it they cannot agree: home is still showing the
  // copy it fetched before the quiz, where nothing was studied yet, while the
  // DB now has `times_studied = 1` on the concept just finished. Both use the
  // same rule — `primaryOf` / this file's mirror, "weakest studied, else
  // weakest" — so the disagreement is purely which snapshot each one read.)
  await page.reload();
  await expectLocation(page, "/quiz");
  const ranking = await proposalsFromDb();
  await expect(page.getByTestId("quiz-proposal")).toContainText(ranking.primary.concept_name, {
    timeout: SUBMIT_TIMEOUT,
  });
  await expect(page.getByTestId("quiz-results")).toHaveCount(0);
});
