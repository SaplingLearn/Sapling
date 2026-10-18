/**
 * Journeys (#537 D3): every mapped error code and every edge state, rendered.
 *
 * Until #537 the frontend threw the coded envelope away and showed one generic
 * sentence per HTTP status, so `QUIZ_RATE_LIMITED`, `QUIZ_DAILY_LIMIT_REACHED`
 * and `QUIZ_GENERATION_TIMEOUT` were indistinguishable to a student (R1 §H, gap
 * G12). `lib/quiz/errors.ts` is the fix; this file is the proof that the copy
 * table reaches the screen.
 *
 * WHY route interception rather than the backend. Every code here is a state
 * the real routes reach only by being rate-limited, timing out, or racing a
 * second submit — none of which a journey can provoke deterministically, and
 * some of which (the daily spend cap) would need a doctored `llm_usage` table.
 * The envelope is faked at the network layer instead, byte-identical to
 * `backend/services/quiz_errors.py::quiz_error_body` (see `support/quizStack.ts`),
 * with the `Retry-After` header the 429 raise site sets. Nothing in the backend
 * is touched.
 *
 * The expected strings are IMPORTED from `@/lib/quiz/errors`, not retyped: the
 * contract's §4 table is that module's `QUIZ_ERROR_COPY`, and a spec that
 * duplicated it would go green on the day someone edited both.
 */
import type { Page } from "@playwright/test";

import { QUIZ_ERROR_COPY } from "@/lib/quiz/errors";

import { expect, test } from "./support/fixtures";
import {
  NODE_RECURSION,
  chooseOption,
  fakeNode,
  primeQuizBrowser,
  quizErrorFulfill,
} from "./support/quizStack";
import { USER_ACTIVE } from "./support/stack";

/**
 * The server's own sentence, deliberately different from every mapped copy.
 * A card that rendered THIS would mean the frontend is still echoing
 * `detail`/`error.message` instead of mapping the code — the pre-#537 bug in a
 * new disguise.
 */
const SERVER_SENTENCE = "Server sentence that must never reach the screen.";

const REQUEST_ID = "e2e-request-id-537";

// ── Route helpers ──────────────────────────────────────────────────────────

/** Exact-pathname matcher: `getGraph` may carry `?semester=`, and the quiz
 *  paths must not swallow `/api/quiz/config` or `/api/quiz/attempts`. */
function onPath(path: string) {
  return (url: URL) => url.pathname === path;
}

function onAnswerPath(url: URL): boolean {
  return url.pathname.startsWith("/api/quiz/attempts/") && url.pathname.endsWith("/answer");
}

/** A keyless generate response in the shape `include_answer_key: false` returns
 *  (`_strip_answer_key`: no `correct`, no `explanation`). */
function fakeQuiz(count: number, opts: { requested?: number; quizId?: string } = {}) {
  const questions = Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    question: `Faked question ${i + 1}: which option is marked correct?`,
    concept_tested: "Recursion",
    difficulty: "medium",
    options: ["A", "B", "C", "D"].map(label => ({
      label,
      text: `Faked Q${i + 1} option ${label}`,
    })),
  }));
  return {
    quiz_id: opts.quizId ?? "e2e-faked-attempt",
    questions,
    requested_difficulty: "medium",
    resolved_difficulty: "medium",
    requested_count: opts.requested ?? count,
    delivered_count: count,
  };
}

/** Land on quiz home with the seeded concept as the card, ready to Start. */
async function openQuizHome(page: Page) {
  await primeQuizBrowser(page);
  await page.goto(`/quiz?concept=${NODE_RECURSION}`);
  await expect(page.getByTestId("quiz-start")).toBeVisible({ timeout: 30_000 });
}

/** The error card, with the copy the code maps to and nothing the server said. */
async function expectErrorCard(
  page: Page,
  copy: string,
  opts: { retryable: boolean },
) {
  const card = page.getByTestId("quiz-error");
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText(copy);
  await expect(card).not.toContainText(SERVER_SENTENCE);
  // Never a dead end: Back is always there, Retry only when the code says the
  // student's move is to try the same thing again.
  await expect(page.getByTestId("quiz-error-back")).toBeVisible();
  await expect(page.getByTestId("quiz-error-retry")).toHaveCount(opts.retryable ? 1 : 0);
}

// ───────────────────────────────────────────────────────────────────────────
// Generation failures
// ───────────────────────────────────────────────────────────────────────────

test("429 QUIZ_RATE_LIMITED renders the Retry-After seconds, and Retry re-asks", async ({
  page,
}) => {
  let calls = 0;
  await page.route(onPath("/api/quiz/generate"), route => {
    calls += 1;
    return route.fulfill(
      quizErrorFulfill(429, "QUIZ_RATE_LIMITED", SERVER_SENTENCE, {
        requestId: REQUEST_ID,
        retryAfterSec: 30,
      }),
    );
  });

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();

  // "{n}" comes off the `Retry-After` header, not a hardcoded 60.
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_RATE_LIMITED.replace("{n}", "30"), {
    retryable: true,
  });
  await expect(page.getByTestId("quiz-error")).toContainText(`Reference ${REQUEST_ID}`);

  await page.getByTestId("quiz-error-retry").click();
  await expect.poll(() => calls, { timeout: 15_000 }).toBe(2);
  await expect(page.getByTestId("quiz-error")).toBeVisible();
});

test("429 QUIZ_DAILY_LIMIT_REACHED says the allowance resets tomorrow, with no Retry", async ({
  page,
}) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill(
      quizErrorFulfill(429, "QUIZ_DAILY_LIMIT_REACHED", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_DAILY_LIMIT_REACHED, { retryable: false });
});

test("502 QUIZ_GENERATION_TIMEOUT invites a second try", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill(
      quizErrorFulfill(502, "QUIZ_GENERATION_TIMEOUT", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_GENERATION_TIMEOUT, { retryable: true });
});

test("502 QUIZ_GENERATION_FAILED renders its own copy", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill(
      quizErrorFulfill(502, "QUIZ_GENERATION_FAILED", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_GENERATION_FAILED, { retryable: true });
});

/**
 * The #184 regression, now a coded state rather than a blank panel.
 *
 * The route 502s rather than serving an empty quiz, so a 200 with zero
 * questions is belt-and-braces — but it is the exact shape that used to strand
 * the student on a control-less screen, and the reducer maps it to the same
 * QUIZ_GENERATION_FAILED copy on purpose (`machine.ts::GENERATED`).
 */
test("a zero-question 200 lands on the generation-failed copy, never a blank panel", async ({
  page,
}) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeQuiz(0)),
    }),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_GENERATION_FAILED, { retryable: true });
  await expect(page.getByTestId("quiz-answer-options")).toHaveCount(0);
});

test("404 QUIZ_CONCEPT_NOT_FOUND sends the student back to the list", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill(
      quizErrorFulfill(404, "QUIZ_CONCEPT_NOT_FOUND", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_CONCEPT_NOT_FOUND, { retryable: false });
});

/**
 * A transport failure never reaches a server, so it carries no status and no
 * code — `describeQuizError` has to recognise the bare `TypeError` `fetch`
 * rejects with. `route.abort()` is that failure, faithfully.
 */
test("a dropped connection renders the offline copy", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route => route.abort("failed"));

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expectErrorCard(page, QUIZ_ERROR_COPY.NETWORK, { retryable: true });
});

// ───────────────────────────────────────────────────────────────────────────
// Mid-quiz failures
// ───────────────────────────────────────────────────────────────────────────

test("a 409 on /answer surfaces the already-scored copy mid-quiz", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeQuiz(2)),
    }),
  );
  await page.route(onAnswerPath, route =>
    route.fulfill(
      quizErrorFulfill(409, "QUIZ_ATTEMPT_ALREADY_COMPLETED", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({ timeout: 30_000 });

  await chooseOption(page, "B");
  await page.getByTestId("quiz-submit-answer").click();

  // Not retryable: re-sending the same answer to a scored attempt would 409
  // again, so the card offers the way out and not a loop.
  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_ATTEMPT_ALREADY_COMPLETED, {
    retryable: false,
  });
});

test("a 409 on /submit surfaces the abandoned copy", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeQuiz(2)),
    }),
  );
  await page.route(onAnswerPath, async route => {
    const body = route.request().postDataJSON() as {
      question_index: number;
      question_id: number;
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        question_index: body.question_index,
        question_id: body.question_id,
        is_correct: true,
        correct_index: 1,
        explanation: "",
        next_question: null,
        recorded: true,
      }),
    });
  });
  await page.route(onPath("/api/quiz/submit"), route =>
    route.fulfill(
      quizErrorFulfill(409, "QUIZ_ATTEMPT_ABANDONED", SERVER_SENTENCE),
    ),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({ timeout: 30_000 });

  // At-end mode: two Submits, and the second one scores.
  for (const stem of [1, 2]) {
    await expect(page.getByTestId("quiz-panel")).toContainText(`Faked question ${stem}`);
    await chooseOption(page, "B");
    await page.getByTestId("quiz-submit-answer").click();
  }

  await expectErrorCard(page, QUIZ_ERROR_COPY.QUIZ_ATTEMPT_ABANDONED, { retryable: false });
});

/**
 * `delivered_count < requested_count` is the one "success with a caveat" the
 * generate response can carry (R1 §B). It is a toast, not an error — the quiz
 * runs, it is just shorter than asked for — and the rail has to agree with what
 * actually arrived rather than with what was requested.
 */
test("a short delivery says so once and sizes the rail to what arrived", async ({ page }) => {
  await page.route(onPath("/api/quiz/generate"), route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeQuiz(2, { requested: 3 })),
    }),
  );

  await openQuizHome(page);
  await page.getByTestId("quiz-start").click();
  await expect(page.getByTestId("quiz-answer-options")).toBeVisible({ timeout: 30_000 });

  await expect(page.getByText("Only 2 questions were ready for this concept.")).toBeVisible();
  const rail = page.getByTestId("quiz-progress");
  await expect(rail).toHaveAttribute("aria-label", "Question 1 of 2");
  await expect(rail.locator(".progress-dots__dot")).toHaveCount(2);
  await expect(page.getByTestId("quiz-error")).toHaveCount(0);
});

// ───────────────────────────────────────────────────────────────────────────
// Edge states — every one of them a signpost, never a dead end
// ───────────────────────────────────────────────────────────────────────────

const GRAPH_PATH = `/api/graph/${USER_ACTIVE}`;
const COURSES_PATH = `/api/graph/${USER_ACTIVE}/courses`;

/** Both graph reads faked in one place. `getGraph` may carry `?semester=`, so
 *  the match is on pathname — `getCourses` lives one segment deeper and is
 *  matched separately. */
async function routeGraph(
  page: Page,
  payload: { courses?: unknown[]; nodes?: unknown[] },
) {
  if (payload.courses !== undefined) {
    await page.route(onPath(COURSES_PATH), route =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ courses: payload.courses }),
      }),
    );
  }
  if (payload.nodes !== undefined) {
    await page.route(onPath(GRAPH_PATH), route =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ nodes: payload.nodes, edges: [], stats: {} }),
      }),
    );
  }
}

/** The link an empty state offers must actually go somewhere. Fetched over the
 *  page's own cookie jar rather than navigated to, so the assertion is about the
 *  destination existing and not about what it renders. */
async function expectLinkResolves(page: Page, href: string) {
  const res = await page.request.get(href);
  expect(res.status(), `${href} should be a real page`).toBe(200);
}

test("no courses: the empty state points at the dashboard", async ({ page }) => {
  await routeGraph(page, { courses: [], nodes: [] });

  await primeQuizBrowser(page);
  await page.goto("/quiz");

  const empty = page.getByTestId("quiz-empty-state");
  await expect(empty).toBeVisible({ timeout: 30_000 });
  await expect(empty).toContainText("Add a course to start quizzing");
  const link = empty.getByRole("link", { name: "Go to your dashboard" });
  await expect(link).toHaveAttribute("href", "/dashboard");
  await expectLinkResolves(page, "/dashboard");
});

test("courses but no concepts: the empty tree offers the library and the tutor", async ({
  page,
}) => {
  // Courses fall through to the real (seeded) response; only the graph is empty.
  await routeGraph(page, { nodes: [] });

  await primeQuizBrowser(page);
  await page.goto("/quiz");

  const empty = page.getByTestId("quiz-empty-state");
  await expect(empty).toBeVisible({ timeout: 30_000 });
  await expect(empty).toContainText("Your tree is empty");
  await expect(empty).toContainText("Upload notes or talk to the tutor");
  await expect(empty.getByRole("link", { name: "Go to your library" })).toHaveAttribute(
    "href",
    "/library",
  );
  await expect(empty.getByRole("link", { name: "Talk to the tutor" })).toHaveAttribute(
    "href",
    "/learn",
  );
  await expectLinkResolves(page, "/library");
  await expectLinkResolves(page, "/learn");
});

test("everything mastered: nothing to propose, but the list is still there", async ({ page }) => {
  // `rankCandidates` mirrors get_recommendations — mastered nodes are filtered
  // out, so an all-mastered graph is the "nothing due" state by construction.
  await routeGraph(page, {
    nodes: [
      fakeNode("e2e-mastered-1", "Variables and Types", 0.92, "mastered", "rich-course-cs101"),
      fakeNode("e2e-mastered-2", "Algorithms", 0.88, "mastered", "rich-course-cs101"),
    ],
  });

  await primeQuizBrowser(page);
  await page.goto("/quiz");

  const empty = page.getByTestId("quiz-empty-state");
  await expect(empty).toBeVisible({ timeout: 30_000 });
  await expect(empty).toContainText("Nothing needs review right now");
  await expect(page.getByTestId("quiz-review-due")).toHaveCount(0);

  // The way out is in the page rather than at a URL: it opens the browse list.
  await page.getByTestId("quiz-pick-open").click();
  const list = page.getByTestId("quiz-pick-list");
  await expect(list).toBeVisible();
  await expect(page.getByTestId("quiz-pick-e2e-mastered-1")).toBeVisible();
});
