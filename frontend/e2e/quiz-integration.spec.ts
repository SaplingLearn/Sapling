/**
 * Journeys (#537 D3): the features the quiz redesign TOUCHES, end to end
 * against the real local stack.
 *
 * `quiz.spec.ts` / `quiz-journeys.spec.ts` (D2) pin the quiz's own three
 * screens. This file pins everything the redesign reaches into and could
 * silently break: the tree's node panel and its new `?node=` return path, the
 * gamification read that feeds the results screen's XP line, the achievement
 * counter submit bumps, the tutor handoff that used to throw the attempt away,
 * the notetaker's disabled-until-linked gate, and semester scoping over deep
 * links.
 *
 * Everything below writes through the real UI and reads back over a DIFFERENT
 * layer — raw SQL (`support/db.ts::queryRaw`) or the API via `page.request` —
 * so a passing assertion is never the app echoing itself.
 *
 * Determinism: the stack must be booted with
 *
 *   SAPLING_MODEL_MODE=function \
 *   SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up
 *
 * The scripted quiz is a fixed three questions whose correct labels are B, C, A
 * (`agents/function_handlers_e2e.py::E2E_QUIZ_CORRECT_LABELS`) and the tutor
 * always answers `E2E_TUTOR_REPLY`. Both constants are mirrored in
 * `support/quizStack.ts` — KEEP IN SYNC. Every journey asserts the scripted stem
 * before it answers, which doubles as the loud guard that the stack really is in
 * function mode rather than talking to live Gemini.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import {
  CORRECT_LABELS,
  NODE_BIO_DNA,
  NODE_BIO_DNA_NAME,
  NODE_RECURSION,
  NODE_RECURSION_NAME,
  NOTE_CS_WEEK1,
  NOTE_CS_WEEK1_TITLE,
  SEEDED_RECURSION_ATTEMPT,
  SEEDED_RECURSION_MASTERY,
  TUTOR_REPLY,
  answerAtEnd,
  chooseOption,
  primeQuizBrowser,
  scriptedStem,
} from "./support/quizStack";
import { USER_ACTIVE } from "./support/stack";

/** routes/quiz.py: 3 correct of 3 → delta = 3 × 0.03 = +0.09. */
const ALL_CORRECT_DELTA = 3 * 0.03;

/** The one attempt row this journey created — the seeded baseline attempts are
 *  namespaced `rich-*` and the route mints uuid4 ids. */
async function appAttemptsFor(nodeId: string) {
  return (await queryRaw(
    `SELECT id, score, total, completed_at
       FROM quiz_attempts
      WHERE concept_node_id = $1 AND id NOT LIKE 'rich-%'
      ORDER BY created_at ASC`,
    [nodeId],
  )) as { id: string; score: number | null; total: number | null; completed_at: string | null }[];
}

async function masteryOf(nodeId: string): Promise<number> {
  const rows = await queryRaw("SELECT mastery_score FROM graph_nodes WHERE id = $1", [nodeId]);
  expect(rows).toHaveLength(1);
  return Number(rows[0].mastery_score);
}

// ───────────────────────────────────────────────────────────────────────────
// 1. The tree round trip
// ───────────────────────────────────────────────────────────────────────────

/**
 * The loop the redesign exists to close (R-10 / C1): leave the tree from a
 * node, take the quiz, and come BACK to that node's open panel with the result
 * on it. Before #537 every quiz exit pushed a hardcoded `/learn`.
 *
 * Three separate proofs that mastery moved: the DB score, the panel's new
 * Recent-quizzes row, and the results screen the student actually saw.
 */
test("a quiz launched from the tree moves mastery and returns to the node panel", async ({
  page,
}) => {
  test.setTimeout(240_000);

  const masteryBefore = await masteryOf(NODE_RECURSION);
  expect(masteryBefore).toBeCloseTo(SEEDED_RECURSION_MASTERY, 10);
  expect(await appAttemptsFor(NODE_RECURSION)).toHaveLength(0);

  await primeQuizBrowser(page);

  // `?node=<id>` is the focus param C1 added — the tree selects that node
  // exactly as a tap would, which is what makes it a usable return path.
  await page.goto(`/tree?node=${NODE_RECURSION}`);
  await expect(page.getByRole("heading", { name: NODE_RECURSION_NAME })).toBeVisible();

  const recent = page.getByTestId("tree-node-recent-quizzes");
  await expect(recent).toBeVisible();
  // The seeded baseline attempt is already there, so "a new row appeared" is a
  // real delta rather than "the block finally rendered".
  await expect(page.getByTestId(`tree-node-recent-quiz-${SEEDED_RECURSION_ATTEMPT}`)).toBeVisible();

  await page.getByRole("button", { name: "Quick quiz" }).click();

  // The href the panel builds carries the origin AND the way back (§6).
  await expect(page).toHaveURL(/\/quiz\?/);
  const entry = new URL(page.url()).searchParams;
  expect(entry.get("concept")).toBe(NODE_RECURSION);
  expect(entry.get("from")).toBe("tree");
  expect(entry.get("return")).toBe(`/tree?node=${NODE_RECURSION}`);

  // Quiz home opens on the deep-linked concept, badged with where it came from.
  const proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toBeVisible({ timeout: 30_000 });
  await expect(proposal).toContainText(NODE_RECURSION_NAME);
  await expect(proposal).toContainText("From your tree");

  await page.getByTestId("quiz-start").click();
  await answerAtEnd(page, CORRECT_LABELS);

  const results = page.getByTestId("quiz-results");
  await expect(results).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("quiz-results-score")).toHaveText("3 of 3 correct");
  await expect(page.getByTestId("quiz-results-perfect")).toBeVisible();

  // ── DB: the score really moved, by exactly the all-correct delta ─────────
  const masteryAfter = await masteryOf(NODE_RECURSION);
  expect(masteryAfter).toBeGreaterThan(masteryBefore);
  expect(masteryAfter).toBeCloseTo(SEEDED_RECURSION_MASTERY + ALL_CORRECT_DELTA, 10);

  const attempts = await appAttemptsFor(NODE_RECURSION);
  expect(attempts).toHaveLength(1);
  expect(Number(attempts[0].score)).toBe(3);
  expect(attempts[0].completed_at).not.toBeNull();
  const attemptId = attempts[0].id;

  // ── The exit honours the origin ──────────────────────────────────────────
  const back = page.getByTestId("quiz-back-to-source");
  await expect(back).toHaveText("Back to your tree");
  await back.click();
  await expect(page).toHaveURL(new RegExp(`/tree\\?node=${NODE_RECURSION}$`));

  // ── …and the panel it lands on shows the attempt that just happened ──────
  await expect(page.getByRole("heading", { name: NODE_RECURSION_NAME })).toBeVisible();
  const newRow = page.getByTestId(`tree-node-recent-quiz-${attemptId}`);
  await expect(newRow).toBeVisible({ timeout: 30_000 });
  await expect(newRow).toContainText("3/3");
  // `formatMasteryDelta` renders +9% for 0.25 → 0.34. The sign is the point:
  // an all-correct quiz can never render a negative move.
  await expect(newRow).toContainText("+9% mastery");
  await expect(page.getByTestId(`tree-node-recent-quiz-${SEEDED_RECURSION_ATTEMPT}`)).toBeVisible();
});

// ───────────────────────────────────────────────────────────────────────────
// 2. XP, streak and the achievement counter
// ───────────────────────────────────────────────────────────────────────────

/**
 * `POST /api/quiz/submit` pays XP, bumps the streak and re-evaluates the
 * `quizzes_completed` achievement stat. It now also RETURNS the first two
 * (G8's `gamification` block), but the client has not migrated to them: R-9
 * still renders a second read of `GET /api/gamification/me`, and this journey
 * pins that the line the student sees is that read, not an invention. When the
 * client swaps to `result.gamification` (R-9a) these assertions still hold —
 * the inline block IS that snapshot, by construction.
 *
 * The achievement half reuses gamification.spec.ts's posture (drive the state,
 * then assert the rendered surface) against the one live `quizzes_completed`
 * badge, "Quiz Master" (`20260731194102_achievement_catalog.sql`, target 100).
 */
test("finishing a quiz moves XP, the streak line and the quizzes-completed counter", async ({
  page,
}) => {
  test.setTimeout(240_000);

  const readMe = async () => {
    const res = await page.request.get(`/api/gamification/me?user_id=${USER_ACTIVE}`);
    expect(res.ok()).toBe(true);
    return (await res.json()) as { total_xp: number; streak: number };
  };
  const readQuizMasterProgress = async () => {
    const res = await page.request.get(`/api/profile/${USER_ACTIVE}/achievements`);
    expect(res.ok()).toBe(true);
    const body = (await res.json()) as {
      available: { slug: string; progress: { current: number; target: number } | null }[];
    };
    const badge = body.available.find(a => a.slug === "quiz-master");
    expect(badge, "the live quizzes_completed badge should be unearned and available").toBeTruthy();
    expect(badge!.progress).not.toBeNull();
    return badge!.progress!;
  };

  const xpBefore = await readMe();
  const progressBefore = await readQuizMasterProgress();

  await primeQuizBrowser(page);
  await page.goto(`/quiz?concept=${NODE_RECURSION}`);
  await expect(page.getByTestId("quiz-start")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("quiz-start").click();
  await answerAtEnd(page, CORRECT_LABELS);
  await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: 60_000 });

  // ── The API is the authority for the delta the line claims ───────────────
  const xpAfter = await readMe();
  expect(xpAfter.total_xp).toBeGreaterThan(xpBefore.total_xp);
  const delta = xpAfter.total_xp - xpBefore.total_xp;

  // R-9: the line is omitted rather than invented when either read failed. Both
  // reads succeed here (the same cookie jar just made them), so the line MUST be
  // present — an absent one would mean the hook's own reads are broken.
  const xpLine = page.getByTestId("quiz-results-xp");
  await expect(xpLine).toBeVisible();
  await expect(xpLine).toHaveText(`+${delta} XP · ${xpAfter.streak}-day streak`);

  // ── The achievement stat counted exactly this one quiz ───────────────────
  const progressAfter = await readQuizMasterProgress();
  expect(progressAfter.target).toBe(progressBefore.target);
  expect(progressAfter.current).toBe(progressBefore.current + 1);

  // …and the badge grid renders the moved counter.
  await page.goto("/achievements");
  const quizMaster = page.getByRole("button", { name: /Quiz Master/ });
  await expect(quizMaster).toBeVisible({ timeout: 30_000 });
  await expect(quizMaster).toContainText(`${progressAfter.current} / ${progressAfter.target}`);
});

// ───────────────────────────────────────────────────────────────────────────
// 3. The tutor handoff
// ───────────────────────────────────────────────────────────────────────────

/**
 * "Ask about this" is the behavioural point of the redesign (R-6). The old
 * screen navigated to `/learn?topic=…`, which abandoned the attempt outright.
 * The sheet opens OVER the question; the attempt cannot notice it happened.
 *
 * Pinned here: the seed carries the real texts (stem, the chosen and correct
 * option TEXTS, the explanation — not just their letters), the tutor really
 * streams, a follow-up streams again, closing leaves the question and the
 * verdict untouched with the attempt still open in the database, the quiz still
 * finishes, and the session the handoff opened is really in the tutor's list.
 */
test("Ask about this seeds the tutor, streams, and leaves the attempt intact", async ({ page }) => {
  test.setTimeout(240_000);

  const sessionsBefore = await page.request.get(`/api/learn/sessions/${USER_ACTIVE}?limit=50`);
  expect(sessionsBefore.ok()).toBe(true);
  const beforeIds = new Set(
    ((await sessionsBefore.json()) as { sessions: { id: string }[] }).sessions.map(s => s.id),
  );

  // As-you-go is the mode that reveals a verdict mid-quiz — "Ask about this"
  // needs one, so it only renders in the `answered` phase.
  await primeQuizBrowser(page, { feedback: "as-you-go" });
  await page.goto(`/quiz?concept=${NODE_RECURSION}`);
  await expect(page.getByTestId("quiz-start")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("quiz-start").click();

  const panel = page.getByTestId("quiz-panel");
  await expect(panel).toContainText(scriptedStem(1), { timeout: 60_000 });

  // Deliberately wrong: the scripted answer to question 1 is B.
  await chooseOption(page, "A");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-review-verdict")).toContainText(
    "Not quite — the answer is B.",
  );

  await page.getByTestId("quiz-ask").click();
  const sheet = page.getByTestId("quiz-ask-panel");
  await expect(sheet).toBeVisible();

  // The seed is the contract with the tutor: everything it needs to answer
  // "why was I wrong", in TEXTS rather than letters.
  const seed = page.getByTestId("quiz-ask-seed");
  await expect(seed).toContainText(scriptedStem(1));
  await expect(seed).toContainText("You chose A ·");
  await expect(seed).toContainText("Q1 option A");
  await expect(seed).toContainText("The answer is B ·");
  await expect(seed).toContainText("Q1 option B");
  await expect(seed).toContainText(
    "Scripted E2E fixture: option B is the marked answer for question 1.",
  );

  // The streamed reply, byte-for-byte the function-mode constant.
  await expect(sheet.getByText(TUTOR_REPLY)).toHaveCount(1, { timeout: 60_000 });

  // A follow-up streams again into the same session.
  await page.getByTestId("quiz-ask-input").fill("Can you give me one more example?");
  await page.getByTestId("quiz-ask-send").click();
  await expect(sheet).toContainText("Can you give me one more example?");
  await expect(sheet.getByText(TUTOR_REPLY)).toHaveCount(2, { timeout: 60_000 });

  // ── Closing puts the student back on the exact same item ─────────────────
  await page.getByTestId("quiz-ask-panel-close").click();
  await expect(sheet).toHaveCount(0);
  await expect(panel).toContainText(scriptedStem(1));
  await expect(page.getByTestId("quiz-review-verdict")).toContainText(
    "Not quite — the answer is B.",
  );

  // …and the attempt is still open in the database, not orphaned or scored.
  await expect
    .poll(async () => (await appAttemptsFor(NODE_RECURSION)).length, { timeout: 10_000 })
    .toBe(1);
  const midAttempt = (await appAttemptsFor(NODE_RECURSION))[0];
  expect(midAttempt.completed_at).toBeNull();

  // ── The quiz still finishes from where it was left ───────────────────────
  await page.getByTestId("quiz-next").click();
  for (const [offset, label] of [CORRECT_LABELS[1], CORRECT_LABELS[2]].entries()) {
    await expect(panel).toContainText(scriptedStem(offset + 2), { timeout: 30_000 });
    await chooseOption(page, label);
    await page.getByTestId("quiz-submit-answer").click();
    await expect(page.getByTestId("quiz-review-verdict")).toContainText("Correct.");
    await page.getByTestId("quiz-next").click();
  }

  await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("quiz-results-score")).toHaveText("2 of 3 correct");

  const finished = (await appAttemptsFor(NODE_RECURSION))[0];
  expect(finished.id).toBe(midAttempt.id);
  expect(finished.completed_at).not.toBeNull();
  expect(Number(finished.score)).toBe(2);

  // ── The handoff was real: the tutor now lists the session it opened ──────
  const sessionsAfter = await page.request.get(`/api/learn/sessions/${USER_ACTIVE}?limit=50`);
  expect(sessionsAfter.ok()).toBe(true);
  const after = (await sessionsAfter.json()) as {
    sessions: { id: string; topic: string; mode: string }[];
  };
  const created = after.sessions.filter(s => !beforeIds.has(s.id));
  expect(created).toHaveLength(1);
  expect(created[0].topic).toBe(NODE_RECURSION_NAME);
  expect(created[0].mode).toBe("socratic");
});

// ───────────────────────────────────────────────────────────────────────────
// 4. The notetaker gate
// ───────────────────────────────────────────────────────────────────────────

/**
 * "Generate quiz" on a note is disabled until the note has a linked concept
 * (`routes/notes.py` 400s otherwise), and #537 kept that gate while rewriting
 * where the button LANDS: a `from=notes` deep link with a `return` that reopens
 * this note, and a results exit labelled "Back to your note".
 *
 * The seeded notes have no concept links, so the disabled state is the starting
 * state rather than something this journey has to manufacture.
 */
test("the note's Generate quiz gate holds, and the round trip reopens the note", async ({
  page,
}) => {
  test.setTimeout(240_000);

  await primeQuizBrowser(page);
  await page.goto(`/notetaker?note=${NOTE_CS_WEEK1}`);

  // `?note=<id>` is the arrival half of the round trip; it opens this note.
  await expect(page.getByPlaceholder("Untitled note")).toHaveValue(NOTE_CS_WEEK1_TITLE, {
    timeout: 30_000,
  });

  const generate = page.getByRole("button", { name: "Generate quiz" });
  await expect(page.getByText("No concepts linked yet.")).toBeVisible();
  await expect(generate).toBeDisabled();

  // Link one concept through the real picker.
  await page.getByRole("button", { name: "Link concept" }).click();
  const picker = page.getByRole("dialog").filter({ hasText: "Pick a concept to link" });
  await expect(picker).toBeVisible();
  await picker.getByRole("button", { name: new RegExp(`^${NODE_RECURSION_NAME}\\b`) }).click();
  await expect(picker).toHaveCount(0);
  await expect(page.getByLabel(`Unlink ${NODE_RECURSION_NAME}`)).toBeVisible();

  await expect(generate).toBeEnabled();
  await generate.click();

  // §6: concept id (not a name), the origin, and the way back to THIS note.
  await expect(page).toHaveURL(/\/quiz\?/, { timeout: 30_000 });
  const entry = new URL(page.url()).searchParams;
  expect(entry.get("concept")).toBe(NODE_RECURSION);
  expect(entry.get("from")).toBe("notes");
  expect(entry.get("note")).toBe(NOTE_CS_WEEK1);
  expect(entry.get("return")).toBe(`/notetaker?note=${NOTE_CS_WEEK1}`);

  const proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toBeVisible({ timeout: 30_000 });
  await expect(proposal).toContainText(NODE_RECURSION_NAME);
  await expect(proposal).toContainText("From your note");

  await page.getByTestId("quiz-start").click();
  await answerAtEnd(page, CORRECT_LABELS);
  await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: 60_000 });

  const back = page.getByTestId("quiz-back-to-source");
  await expect(back).toHaveText("Back to your note");
  await back.click();

  await expect(page).toHaveURL(new RegExp(`/notetaker\\?note=${NOTE_CS_WEEK1}$`));
  await expect(page.getByPlaceholder("Untitled note")).toHaveValue(NOTE_CS_WEEK1_TITLE, {
    timeout: 30_000,
  });
});

// ───────────────────────────────────────────────────────────────────────────
// 5. Semester scoping
// ───────────────────────────────────────────────────────────────────────────

/**
 * §6: a deep link into a term the student is not looking at says so ONCE and
 * then gets out of the way — the ordinary home renders underneath, and the
 * "pick something specific" list offers only in-scope courses.
 *
 * The seed makes CS101 an awkward probe: rich-user-active is enrolled in it in
 * BOTH Fall 2025 and Spring 2026, so no term excludes it while still leaving
 * concepts on screen. BIO110 is the honest one — Fall 2025 only — so Spring 2026
 * scopes it out while CS101 and MATH210 stay, which is exactly the "toast plus
 * the ordinary home" state this pins. (A Fall 2026 scope would exclude CS101 but
 * leaves the student with ENG150, which has no concepts at all: that is the
 * empty-tree state, a different screen.)
 */
test("a deep link outside the active semester toasts and falls back to the ordinary home", async ({
  page,
}) => {
  await primeQuizBrowser(page, { semester: "Spring 2026" });
  await page.goto(`/quiz?concept=${NODE_BIO_DNA}`);

  await expect(page.getByText("That concept isn't in your current semester")).toBeVisible({
    timeout: 30_000,
  });

  // Not a dead end: the ordinary proposal is underneath, and it is NOT the
  // out-of-scope concept.
  const proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toBeVisible();
  await expect(proposal).not.toContainText(NODE_BIO_DNA_NAME);

  // The pick list groups only the in-scope courses.
  await page.getByTestId("quiz-pick-open").click();
  const list = page.getByTestId("quiz-pick-list");
  await expect(list).toBeVisible();
  await expect(list).toContainText("CS101");
  await expect(list).toContainText("MATH210");
  await expect(list).not.toContainText("BIO110");
  await expect(page.getByTestId(`quiz-pick-${NODE_BIO_DNA}`)).toHaveCount(0);
  await expect(page.getByTestId(`quiz-pick-${NODE_RECURSION}`)).toBeVisible();
});

test("All semesters resolves the same deep link to its concept card", async ({ page }) => {
  // The empty string is the "All semesters" default (#360) — scoping is opt-in.
  await primeQuizBrowser(page, { semester: "" });
  await page.goto(`/quiz?concept=${NODE_BIO_DNA}`);

  const proposal = page.getByTestId("quiz-proposal");
  await expect(proposal).toBeVisible({ timeout: 30_000 });
  await expect(proposal).toContainText(NODE_BIO_DNA_NAME);
  await expect(page.getByText("That concept isn't in your current semester")).toHaveCount(0);
});

// ───────────────────────────────────────────────────────────────────────────
// Screenshots for the lead — opt-in, never part of a normal run
// ───────────────────────────────────────────────────────────────────────────

/**
 * `QUIZ_SHOTS=<dir> npx playwright test e2e/quiz-integration.spec.ts -g screenshots`
 *
 * Skipped by default so CI and every ordinary local run stay artifact-free; the
 * shots are a review aid, not an assertion. Uses the real app against the real
 * stack at the review viewport (1440×900).
 */
test("screenshots for the lead", async ({ page }) => {
  const dir = process.env.QUIZ_SHOTS?.trim();
  test.skip(!dir, "set QUIZ_SHOTS=<output dir> to capture the review screenshots");
  test.setTimeout(240_000);

  await page.setViewportSize({ width: 1440, height: 900 });
  // As-you-go so the answered state has a verdict to show, and so the results
  // screen's missed list has something in it.
  await primeQuizBrowser(page, { feedback: "as-you-go" });

  await page.goto(`/quiz?concept=${NODE_RECURSION}&from=tree&return=%2Ftree`);
  await expect(page.getByTestId("quiz-proposal")).toBeVisible({ timeout: 30_000 });
  // The definition paragraph arrives from an agent call (R-8), so the card
  // settles a beat after Start becomes clickable. Wait for the function-mode
  // blurb so the shot isn't of a half-written card — tolerantly, because a card
  // showing the built fallback sentence is a valid state to photograph too.
  await expect(page.getByTestId("quiz-start")).toBeEnabled();
  await page
    .getByTestId("quiz-proposal")
    .getByText("[e2e-function-model]")
    .waitFor({ state: "visible", timeout: 20_000 })
    .catch(() => {});
  await page.screenshot({ path: `${dir}/shot-home.png`, fullPage: false });

  await page.getByTestId("quiz-start").click();
  const panel = page.getByTestId("quiz-panel");
  await expect(panel).toContainText(scriptedStem(1), { timeout: 60_000 });
  await chooseOption(page, "B");
  await page.screenshot({ path: `${dir}/shot-question.png`, fullPage: false });

  // Question 2's answer is C, so choosing B is the wrong-answer reveal.
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-review-verdict")).toContainText("Correct.");
  await page.getByTestId("quiz-next").click();
  await expect(panel).toContainText(scriptedStem(2), { timeout: 30_000 });
  await chooseOption(page, "B");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-review-verdict")).toContainText(
    "Not quite — the answer is C.",
  );
  await expect(page.getByTestId("quiz-ask")).toBeVisible();
  await page.screenshot({ path: `${dir}/shot-answered.png`, fullPage: false });

  await page.getByTestId("quiz-next").click();
  await expect(panel).toContainText(scriptedStem(3), { timeout: 30_000 });
  await chooseOption(page, "A");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-review-verdict")).toContainText("Correct.");
  await page.getByTestId("quiz-next").click();

  await expect(page.getByTestId("quiz-results")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("quiz-missed-list")).toBeVisible();
  await page.screenshot({ path: `${dir}/shot-results.png`, fullPage: false });
});
