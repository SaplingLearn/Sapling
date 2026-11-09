/**
 * 02 — quiz / study / flashcards / notetaker / library
 * (docs/figma/inventory/02-quiz-study-notes-library.md).
 *
 * Every mutating call a recipe makes is either mocked (with its method) or
 * held, so the shared showcase DB never changes under the run. The quiz flow
 * is fully faked (generate → answer → submit), which keeps verdicts, mastery
 * and XP deterministic and writes no attempts. The tutor, the note agents,
 * scans, uploads and imports are faked the same way.
 */
import { Buffer } from "node:buffer";

import { expect, type Locator, type Page, type Route } from "@playwright/test";

import { QUIZ_ERROR_COPY } from "@/lib/quiz/errors";

import { chooseOption, fakeNode, quizErrorFulfill } from "../../support/quizStack";
import { USER_ACTIVE as U } from "../../support/stack";
import { COURSE_CS101, NODE_RECURSION, storage, visible } from "../helpers";
import type { RecipeBook } from "../types";

// ── Seed ids (backend/db/seed_local_rich.py) ─────────────────────────────────

const COURSE_MATH = "rich-course-math210";
const NODE_BIO_DNA = "rich-node-bio-dna";
const NOTE_CS = "rich-note-cs-week1";
const NOTE_MATH = "rich-note-math-vectors";
const DOC_MATH = "rich-doc-math-notes";

const QUIZ_TREE = `/quiz?concept=${NODE_RECURSION}&from=tree&return=%2Ftree`;
const LONG = 60_000;

// ── Routing primitives ───────────────────────────────────────────────────────

type PathMatch = string | RegExp;

/** Route one method + exact pathname (string) or pathname regex. */
async function on(
  page: Page,
  method: string | null,
  path: PathMatch,
  handler: (route: Route) => Promise<void> | void,
): Promise<void> {
  await page.route(
    (url) => (typeof path === "string" ? url.pathname === path : path.test(url.pathname)),
    async (route) => {
      if (method && route.request().method() !== method) return route.fallback();
      await handler(route);
    },
  );
}

function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function json(page: Page, method: string | null, path: PathMatch, body: unknown, status = 200) {
  await on(page, method, path, (route) => fulfillJson(route, body, status));
}

/** A failure whose `detail` is a human sentence, so `humanizeError` shows it. */
async function fail(page: Page, method: string | null, path: PathMatch, detail: string, status = 500) {
  await json(page, method, path, { detail }, status);
}

/** Never answer → the UI stays in its in-flight state. */
async function holdOn(page: Page, method: string | null, path: PathMatch) {
  await on(page, method, path, () => {
    /* intentionally never fulfilled */
  });
}

/** Pass the real response through `mutate`. */
async function patchJson(
  page: Page,
  method: string | null,
  path: PathMatch,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mutate: (body: any) => unknown,
) {
  await on(page, method, path, async (route) => {
    const res = await route.fetch();
    await fulfillJson(route, mutate(await res.json()), res.status());
  });
}

function sseBody(events: { event: string; data: unknown }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

async function sse(page: Page, method: string, path: PathMatch, events: { event: string; data: unknown }[]) {
  await on(page, method, path, (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: sseBody(events) }),
  );
}

async function toast(page: Page, t: string | RegExp, timeout = 15_000) {
  await expect(page.getByRole("status").filter({ hasText: t }).first()).toBeVisible({ timeout });
}

// ── Quiz fakes ───────────────────────────────────────────────────────────────

const LABELS = ["A", "B", "C", "D"];

interface FakeQ {
  id: number;
  question: string;
  difficulty: string;
  options: string[];
  /** Correct option index (MCQ). */
  correct: number;
  explanation: string;
  type?: "multiple_choice" | "short_answer" | "numeric" | "symbolic";
  /** Written: the expected answer, and what else grades as right. */
  answer?: string;
  accept?: string[];
  material_context?: "course_material" | "catalog" | "general";
}

/** The showcase quiz (agents/function_handlers_showcase.py), correct B, C, B. */
const MCQ: FakeQ[] = [
  {
    id: 1,
    question:
      "A recursive function computes the sum of a list by adding the first element to the sum of the rest. What happens if the base case is removed?",
    difficulty: "medium",
    options: [
      "It returns 0 for every input",
      "It recurses until the call stack overflows",
      "It returns only the first element",
      "It silently skips the last element",
    ],
    correct: 1,
    explanation:
      "Without a base case nothing stops the descent: each call makes another call on a shorter list, and the empty list never returns a value. The stack grows until the runtime gives up.",
  },
  {
    id: 2,
    question: "Which of these problems is a natural fit for recursion rather than a simple loop?",
    difficulty: "easy",
    options: [
      "Summing the integers from 1 to n",
      "Finding the largest value in a flat array",
      "Walking every node of a binary tree",
      "Counting the characters in a string",
    ],
    correct: 2,
    explanation:
      "A tree is defined in terms of itself — each child is a tree — so the traversal mirrors the structure. The other three are flat sequences a loop handles more directly.",
  },
  {
    id: 3,
    question: "In a recursive call, what is actually stored on the call stack for each pending invocation?",
    difficulty: "hard",
    options: [
      "Only the return value",
      "The function's local state and where to resume",
      "A copy of the entire program",
      "Nothing — recursion reuses one frame",
    ],
    correct: 1,
    explanation:
      "Each call gets its own frame holding its arguments, locals and the return address. That is why deep recursion costs memory, and why an unbounded descent overflows.",
  },
];
const RIGHT = ["B", "C", "B"];

const W_SHORT: FakeQ = {
  id: 11,
  type: "short_answer",
  question: "What do we call the condition that stops a recursive function from calling itself again?",
  difficulty: "medium",
  options: [],
  correct: -1,
  answer: "the base case",
  accept: ["base case", "the base case"],
  explanation: "The base case returns a value directly, so the chain of pending calls can unwind.",
};
const W_NUMERIC: FakeQ = {
  id: 12,
  type: "numeric",
  question: "factorial(n) recurses once per level until n = 0. How many calls does factorial(4) make in total?",
  difficulty: "medium",
  options: [],
  correct: -1,
  answer: "5",
  accept: ["5"],
  explanation: "factorial(4), (3), (2), (1) and the base case factorial(0): five calls.",
};
const W_SYMBOLIC: FakeQ = {
  id: 13,
  type: "symbolic",
  question: "T(n) = T(n − 1) + 2 with T(0) = 2. Write T(n) as an expression in n.",
  difficulty: "hard",
  options: [],
  correct: -1,
  answer: "2(n + 1)",
  accept: ["2(n + 1)", "2n + 2"],
  explanation: "Each level adds 2 on top of T(0) = 2, so T(n) = 2n + 2.",
};

const isWritten = (q: FakeQ) => Boolean(q.type && q.type !== "multiple_choice");

function wire(q: FakeQ) {
  return {
    id: q.id,
    question: q.question,
    type: q.type ?? "multiple_choice",
    difficulty: q.difficulty,
    concept_tested: "Recursion",
    options: isWritten(q) ? [] : q.options.map((text, i) => ({ label: LABELS[i], text })),
    ...(q.material_context ? { material_context: q.material_context } : {}),
  };
}

function gamificationMe(totalXp: number) {
  return {
    level: 7,
    next_level: 8,
    stage: "sapling",
    total_xp: totalXp,
    xp_into_level: totalXp - 1100,
    xp_for_level: 300,
    level_pct: Math.round(((totalXp - 1100) / 300) * 100),
    streak: 4,
    longest_streak: 9,
    daily_goal_xp: 50,
    today_xp: totalXp - 1240,
    earned_count: 6,
    total_count: 24,
  };
}

interface FakeQuizOpts {
  questions?: FakeQ[];
  /** `requested_count` (defaults to what was delivered). */
  requested?: number;
  generate?: "ok" | "hold";
  answer?: "ok" | "hold";
  submit?: "ok" | "hold";
  /** false → GET /api/gamification/me fails, so the XP line is omitted. */
  xp?: boolean;
}

/** Fake every quiz write: deterministic grading, mastery and XP, no attempts. */
async function fakeQuiz(page: Page, o: FakeQuizOpts = {}): Promise<void> {
  const quizzes = new Map<string, FakeQ[]>();
  const answers = new Map<string, Map<number, { label: string; correct: boolean }>>();
  let generated = 0;
  let submitted = false;

  await on(page, "POST", "/api/quiz/generate", async (route) => {
    if (o.generate === "hold") return;
    const req = (route.request().postDataJSON() ?? {}) as { source_attempt_id?: string };
    let qs = o.questions ?? MCQ;
    let source: { attempt_id: string; reserved_count: number; regenerated_count: number } | undefined;
    if (req.source_attempt_id) {
      const prev = answers.get(req.source_attempt_id) ?? new Map();
      const missed = (quizzes.get(req.source_attempt_id) ?? qs).filter((q) => prev.get(q.id)?.correct === false);
      qs = missed.length ? missed : [qs[0]];
      source = { attempt_id: req.source_attempt_id, reserved_count: qs.length, regenerated_count: 0 };
    }
    generated += 1;
    const quizId = `figma-attempt-${generated}`;
    quizzes.set(quizId, qs);
    answers.set(quizId, new Map());
    await fulfillJson(route, {
      quiz_id: quizId,
      questions: qs.map(wire),
      requested_difficulty: "medium",
      resolved_difficulty: "medium",
      requested_count: o.requested ?? qs.length,
      delivered_count: qs.length,
      ...(source ? { source } : {}),
    });
  });

  await on(page, "POST", /^\/api\/quiz\/attempts\/[^/]+\/answer$/, async (route) => {
    if (o.answer === "hold") return;
    const quizId = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[4]);
    const body = route.request().postDataJSON() as {
      question_index: number;
      question_id: number;
      selected_index?: number | null;
      answer_text?: string;
    };
    const q = (quizzes.get(quizId) ?? MCQ).find((x) => x.id === body.question_id) ?? MCQ[0];
    const written = isWritten(q);
    const text = (body.answer_text ?? "").trim();
    const correct = written
      ? (q.accept ?? []).some((a) => a.toLowerCase() === text.toLowerCase())
      : body.selected_index === q.correct;
    answers.get(quizId)?.set(q.id, {
      label: written ? text : LABELS[body.selected_index ?? 0],
      correct,
    });
    await fulfillJson(route, {
      question_index: body.question_index,
      question_id: body.question_id,
      is_correct: correct,
      correct_index: written ? -1 : q.correct,
      explanation: q.explanation,
      next_question: null,
      recorded: true,
      ...(written ? { answer_text: text, correct_answer: q.answer } : {}),
    });
  });

  await on(page, "POST", "/api/quiz/submit", async (route) => {
    if (o.submit === "hold") return;
    const { quiz_id: quizId } = route.request().postDataJSON() as { quiz_id: string };
    const qs = quizzes.get(quizId) ?? MCQ;
    const got = answers.get(quizId) ?? new Map();
    const results = qs.map((q) => {
      const a = got.get(q.id);
      return {
        question_id: String(q.id),
        selected: a?.label ?? "",
        correct: a?.correct ?? false,
        correct_answer: isWritten(q) ? (q.answer ?? "") : LABELS[q.correct],
        explanation: q.explanation,
      };
    });
    const score = results.filter((r) => r.correct).length;
    const before = 0.25;
    submitted = true;
    await fulfillJson(route, {
      score,
      total: qs.length,
      mastery_before: before,
      mastery_after: Math.round((before + score * 0.03 - (qs.length - score) * 0.02) * 1000) / 1000,
      results,
    });
  });

  await on(page, "GET", "/api/gamification/me", (route) =>
    o.xp === false
      ? fulfillJson(route, { detail: "Gamification is unavailable." }, 500)
      : fulfillJson(route, gamificationMe(submitted ? 1270 : 1240)),
  );
}

interface Prefs {
  feedback?: "as-you-go" | "at-end";
  count?: number;
  questionFormat?: string;
  semester?: string;
}

async function prime(page: Page, p: Prefs = {}): Promise<void> {
  const kv: Record<string, string> = {
    sapling_quiz_prefs: JSON.stringify({
      count: p.count ?? 3,
      difficulty: "medium",
      feedback: p.feedback ?? "at-end",
      ...(p.questionFormat ? { questionFormat: p.questionFormat } : {}),
    }),
  };
  if (p.semester !== undefined) kv.sapling_active_semester = p.semester;
  await storage(page, kv);
}

async function openQuiz(page: Page, url = QUIZ_TREE): Promise<void> {
  await page.goto(url);
  await visible(page, "quiz-proposal", LONG);
  await expect(page.getByTestId("quiz-start")).toBeEnabled({ timeout: LONG });
}

/** Prime + fake + open + Start, landing on question 1. */
async function startQuiz(page: Page, prefs: Prefs = {}, o: FakeQuizOpts = {}, url = QUIZ_TREE) {
  await prime(page, prefs);
  await fakeQuiz(page, o);
  await openQuiz(page, url);
  await page.getByTestId("quiz-start").click();
  await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: LONG });
}

async function onQuestion(page: Page, q: FakeQ) {
  await expect(page.getByTestId("quiz-panel")).toContainText(q.question.slice(0, 50), { timeout: 30_000 });
}

/** At-end walk: choose + Submit per label; the last Submit goes to scoring. */
async function walkAtEnd(page: Page, labels: string[]) {
  for (let i = 0; i < labels.length; i++) {
    await onQuestion(page, MCQ[i]);
    await chooseOption(page, labels[i]);
    await page.getByTestId("quiz-submit-answer").click();
  }
}

/** As-you-go: choose + Submit + wait for the verdict. */
async function answerShown(page: Page, i: number, label: string) {
  await onQuestion(page, MCQ[i]);
  await chooseOption(page, label);
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-review-verdict")).not.toBeEmpty({ timeout: 30_000 });
}

/** Quiz → results with question 2 missed (2 of 3). */
async function toResults(page: Page, o: FakeQuizOpts = {}, labels = ["B", "A", "B"], url = QUIZ_TREE) {
  await startQuiz(page, {}, o, url);
  await walkAtEnd(page, labels);
  await visible(page, "quiz-results", LONG);
}

// ── Tutor (AskPanel) fakes ───────────────────────────────────────────────────

const ASK_REPLY =
  "You picked **It returns 0 for every input**, which would need a base case to return that 0. " +
  "Without one, every call makes another call on a shorter list and nothing ever returns — so the " +
  "frames pile up until the stack overflows. The empty list is exactly where the base case belongs.";

function chatEvent(type: string, data: Record<string, unknown> | null = null, message = "") {
  return { event: type, data: { type, step: type, message, data } };
}

function tokens(text: string) {
  return (text.match(/\S+\s*/g) ?? []).map((delta) => chatEvent("token", { delta }));
}

async function fakeTutor(page: Page, mode: "hold-start" | "hold-reply" | "reply" | "error") {
  if (mode === "hold-start") {
    await holdOn(page, "POST", "/api/learn/start-session/stream");
    return;
  }
  await sse(page, "POST", "/api/learn/start-session/stream", [
    chatEvent("done", { reply: "", graph_update: null, mastery_changes: [], session_id: "figma-ask-session" }),
  ]);
  if (mode === "hold-reply") {
    await holdOn(page, "POST", "/api/learn/chat/stream");
    return;
  }
  if (mode === "reply") {
    await sse(page, "POST", "/api/learn/chat/stream", [
      ...tokens(ASK_REPLY),
      chatEvent("done", { reply: ASK_REPLY, graph_update: null, mastery_changes: [] }),
    ]);
    await json(page, "POST", "/api/learn/chat", { reply: ASK_REPLY, graph_update: null, mastery_changes: [] });
    return;
  }
  await sse(page, "POST", "/api/learn/chat/stream", [
    ...tokens("You picked It returns 0 for every input, which would need a base case to"),
    chatEvent("error", { retryable: false }, "The tutor was interrupted."),
  ]);
  await fail(page, "POST", "/api/learn/chat", "The tutor is unavailable.");
}

/** As-you-go, miss question 1, open "Ask about this". */
async function openAsk(page: Page) {
  await startQuiz(page, { feedback: "as-you-go" });
  await answerShown(page, 0, "A");
  await page.getByTestId("quiz-ask").click();
  await visible(page, "quiz-ask-panel");
}

// ── Quiz home fakes ──────────────────────────────────────────────────────────

const GRAPH = `/api/graph/${U}`;
const COURSES = `/api/graph/${U}/courses`;

function inProgressAttempt() {
  return {
    quiz_id: "figma-resume",
    status: "in_progress",
    concept_node_id: NODE_RECURSION,
    concept_name: "Recursion",
    course_id: COURSE_CS101,
    score: null,
    total: 3,
    difficulty: "medium",
    mastery_before: null,
    mastery_after: null,
    mastery_delta: null,
    created_at: "2026-03-11T11:40:00Z",
    completed_at: null,
  };
}

// ── Study / flashcards ───────────────────────────────────────────────────────

const STUDY_CACHED = `/api/study-guide/${U}/cached`;
const STUDY_EXAMS = `/api/study-guide/${U}/exams`;
const STUDY_GUIDE = `/api/study-guide/${U}/guide`;
const STUDY_REGEN = "/api/study-guide/regenerate";

/** Guide pane listbox triggers, in DOM order: course, exam. */
const guidePicker = (page: Page, i: 0 | 1) => page.locator('button[aria-haspopup="listbox"]').nth(i);

async function pickCourseCs(page: Page) {
  await page.goto("/study");
  await expect(page.getByText("Pick a course to get started")).toBeVisible({ timeout: LONG });
  await guidePicker(page, 0).click();
  await page.getByRole("option", { name: /CS101/ }).first().click();
}

/** Open the seeded cached guide off the Recent guides rail. */
async function openRecentGuide(page: Page) {
  await page.goto("/study");
  const entry = page.getByRole("button", { name: /Midterm Exam/ }).first();
  await expect(entry).toBeVisible({ timeout: LONG });
  await entry.click();
}

const FLASHCARDS = /^\/api\/flashcards\/user\/[^/]+$/;

async function openCards(page: Page) {
  await page.goto("/study?mode=cards");
  await expect(page.getByText(/Card 1 of \d+/)).toBeVisible({ timeout: LONG });
}

async function openImport(page: Page): Promise<Locator> {
  await openCards(page);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Import flashcards", { timeout: 15_000 });
  return dialog;
}

const PASTE = [
  "Mitochondria\tSite of aerobic respiration; makes most of the cell's ATP",
  "Ribosome\tTranslates mRNA into a polypeptide chain",
  "Golgi apparatus\tModifies, sorts and packages proteins for secretion",
  "Lysosome\tMembrane-bound sac of digestive enzymes",
].join("\n");

async function pasteCards(dialog: Locator, text = PASTE) {
  await dialog.locator("textarea").fill(text);
}

function railRow(page: Page, code: string) {
  return page.locator("aside").getByRole("button", { name: new RegExp(`^${code}`) });
}

// ── Notetaker ────────────────────────────────────────────────────────────────

const NOTES_LIST = /^\/api\/notes\/user\/[^/]+$/;
const noteConcepts = (id = NOTE_CS) => `/api/notes/${id}/concepts`;

const LINKED = [
  { id: NODE_RECURSION, concept_name: "Recursion", mastery_tier: "struggling", mastery_score: 0.25, course_id: COURSE_CS101 },
  { id: "figma-linked-variables", concept_name: "Variables and Types", mastery_tier: "mastered", mastery_score: 0.86, course_id: COURSE_CS101 },
  { id: "figma-linked-control", concept_name: "Control Flow", mastery_tier: "learning", mastery_score: 0.52, course_id: COURSE_CS101 },
];

const NOTE_SUMMARY =
  "The note works through recursion as self-reference with a stopping condition, using `factorial` and a list sum as the worked examples. The open question at the end — why the base case has to return a value rather than just stop — is the thread worth picking up next.";
const NOTE_CHAT_REPLY =
  "Your note has the shape right. The bit still missing is what the base case hands back: it has to return a real value, because every call above it is waiting to add something to that result.";

async function openNote(page: Page, id = NOTE_CS) {
  await page.goto(`/notetaker?note=${id}`);
  await expect(page.getByRole("textbox", { name: "Untitled note" })).toBeVisible({ timeout: LONG });
}

const noteBody = (page: Page) => page.getByPlaceholder("Start writing — Sapling will pick up concepts as you go.");

async function openFullscreenChat(page: Page) {
  await openNote(page);
  await page.getByTitle("Fullscreen editor").click();
  await expect(page.getByText("Quick questions")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(600); // pane fade-in
}

async function sendNoteChat(page: Page) {
  const input = page.getByPlaceholder("Ask a quick question…");
  await input.fill("Why does the base case have to return a value?");
  await input.press("Enter");
}

// ── Library / upload ─────────────────────────────────────────────────────────

const DOCS = `/api/documents/user/${U}`;
const UPLOAD = "/api/documents/upload";

async function openLibrary(page: Page) {
  await page.goto("/library");
  await visible(page, `library-doc-${DOC_MATH}`, LONG);
}

async function openDetail(page: Page) {
  await openLibrary(page);
  await page.getByTestId(`library-doc-${DOC_MATH}`).click();
  await visible(page, "library-detail-delete");
}

const PDF = {
  name: "lecture-05-recursion.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.alloc(1_258_291, 32),
};

async function openUpload(page: Page) {
  await openLibrary(page);
  await page.getByTestId("library-upload").click();
  await visible(page, "upload-modal");
}

async function queueFile(page: Page) {
  await openUpload(page);
  await page.getByTestId("upload-modal-file-input").setInputFiles(PDF);
  await visible(page, "upload-modal-file-row-0");
}

function uploadEvent(type: string, step: string, message: string, data: unknown = null) {
  return { event: type, data: { type, step, message, data } };
}

function uploadDone(category = "lecture_notes") {
  return [
    uploadEvent("status", "received", "Received lecture-05-recursion.pdf"),
    uploadEvent("progress", "extracting", "Extracting text…"),
    uploadEvent("progress", "extracted", "Extracted 18,412 characters"),
    uploadEvent("progress", "classifying", "Classifying…"),
    uploadEvent("progress", "classified", `Classified as ${category.replace("_", " ")}`),
    uploadEvent("progress", "summarizing", "Extracting summary…"),
    uploadEvent("progress", "concepts", "3 concepts"),
    uploadEvent("progress", "merging", "Merging into your graph…"),
    uploadEvent("progress", "merged", "Merged"),
    uploadEvent("result", "complete", "Processing complete", {
      id: "figma-upload-doc",
      classification: { category, is_syllabus: category === "syllabus", confidence: 0.96 },
      summary: {
        headline: "Recursion, the call stack, and when to reach for it",
        abstract:
          "Lecture notes covering recursive problem decomposition: how a function expressed in terms of itself terminates, what each pending call costs on the stack, and the tree and divide-and-conquer shapes where recursion reads more clearly than iteration.",
      },
      concepts: {
        concepts: [
          { name: "Recursion", description: "A function defined in terms of a smaller call to itself.", importance: 0.9 },
          { name: "Base Case", description: "The condition that returns without recursing.", importance: 0.8 },
          { name: "Call Stack", description: "The frames holding each pending call.", importance: 0.7 },
        ],
      },
    }),
    uploadEvent("status", "done", "Done", { document_id: "figma-upload-doc" }),
  ];
}

async function uploadToDone(page: Page, category = "lecture_notes") {
  await sse(page, "POST", UPLOAD, uploadDone(category));
  await queueFile(page);
  await page.getByTestId("upload-modal-submit").click();
  await visible(page, "upload-modal-done", 30_000);
}

// ─────────────────────────────────────────────────────────────────────────────

export const RECIPES_STUDY: RecipeBook = {
  // ════════════════════════════ /quiz — home ════════════════════════════════

  "quiz/disclaimer-modal": {
    run: async (page) => {
      await page.addInitScript(() => window.localStorage.removeItem("sapling_disclaimer_ack"));
      await page.goto(QUIZ_TREE);
      await expect(page.getByRole("dialog").filter({ hasText: "Got it" })).toBeVisible({ timeout: LONG });
    },
  },

  "quiz/home-loading": {
    run: async (page) => {
      await holdOn(page, "GET", GRAPH);
      await holdOn(page, "GET", COURSES);
      await page.goto("/quiz");
      await visible(page, "quiz-home", LONG);
      await expect(page.getByTestId("quiz-home").locator(".skeleton").first()).toBeVisible();
    },
  },

  "quiz/home-error": {
    run: async (page) => {
      await fail(page, "GET", GRAPH, "We couldn't reach your knowledge tree.");
      await page.goto("/quiz");
      await visible(page, "quiz-home-error", LONG);
      await visible(page, "quiz-home-retry");
    },
  },

  "quiz/home-no-courses": {
    run: async (page) => {
      await json(page, "GET", COURSES, { courses: [] });
      await json(page, "GET", GRAPH, { nodes: [], edges: [], stats: {} });
      await page.goto("/quiz");
      await expect(page.getByTestId("quiz-empty-state")).toContainText("Add a course to start quizzing", { timeout: LONG });
    },
  },

  "quiz/home-empty-tree": {
    run: async (page) => {
      await json(page, "GET", GRAPH, { nodes: [], edges: [], stats: {} });
      await page.goto("/quiz");
      await expect(page.getByTestId("quiz-empty-state")).toContainText("Your tree is empty", { timeout: LONG });
    },
  },

  "quiz/home-all-mastered": {
    run: async (page) => {
      await json(page, "GET", GRAPH, {
        nodes: [
          fakeNode("figma-m-1", "Variables and Types", 0.92, "mastered", COURSE_CS101),
          fakeNode("figma-m-2", "Control Flow", 0.88, "mastered", COURSE_CS101),
          fakeNode("figma-m-3", "Functions", 0.9, "mastered", COURSE_CS101),
          fakeNode("figma-m-4", "Algorithms", 0.86, "mastered", COURSE_CS101),
        ],
        edges: [],
        stats: {},
      });
      await page.goto("/quiz");
      await expect(page.getByTestId("quiz-empty-state")).toContainText("Nothing needs review right now", { timeout: LONG });
      await visible(page, "quiz-pick-list");
    },
  },

  "quiz/home-ready": {
    run: async (page) => {
      await page.goto(QUIZ_TREE);
      await visible(page, "quiz-proposal");
      await expect(page.getByTestId("quiz-start")).toBeEnabled();
    },
  },

  "quiz/home-definition-pending": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/graph/${U}/concept-description`);
      await openQuiz(page);
      await visible(page, "quiz-definition-pending");
    },
  },

  "quiz/home-definition-fallback": {
    run: async (page) => {
      await fail(page, "POST", `/api/graph/${U}/concept-description`, "Descriptions are unavailable.");
      await openQuiz(page);
      await expect(page.locator(".quiz-home__definition")).toContainText(/connected concept/, { timeout: 30_000 });
    },
  },

  "quiz/home-deeplink-tree": {
    run: async (page) => {
      await openQuiz(page);
      await expect(page.getByTestId("quiz-proposal")).toContainText("From your tree");
    },
  },

  "quiz/home-deeplink-note": {
    run: async (page) => {
      await openQuiz(
        page,
        `/quiz?concept=${NODE_RECURSION}&from=notes&note=${NOTE_CS}&return=${encodeURIComponent(`/notetaker?note=${NOTE_CS}`)}`,
      );
      await expect(page.getByTestId("quiz-proposal")).toContainText("From your note");
    },
  },

  "quiz/home-deeplink-link": {
    run: async (page) => {
      await openQuiz(page, `/quiz?concept=${NODE_RECURSION}`);
      await expect(page.getByTestId("quiz-proposal")).toContainText("Suggested for you");
    },
  },

  "quiz/home-course-queue": {
    run: async (page) => {
      await openQuiz(page, `/quiz?course=${COURSE_CS101}&from=dashboard&return=%2Fdashboard`);
      await expect(page.getByTestId("quiz-proposal-name")).toContainText("Practice CS101");
    },
  },

  "quiz/home-due-queue": {
    run: async (page) => {
      await openQuiz(page, "/quiz?scope=due&from=dashboard&return=%2Fdashboard");
      await expect(page.getByTestId("quiz-proposal-name")).toContainText("Review everything due");
    },
  },

  "quiz/home-unresolved-toast": {
    run: async (page) => {
      await prime(page, { semester: "Spring 2026" });
      await page.goto(`/quiz?concept=${NODE_BIO_DNA}`);
      await toast(page, "That concept isn't in your current semester", LONG);
    },
  },

  "quiz/home-your-pick": {
    run: async (page) => {
      await openQuiz(page, "/quiz");
      await page.getByTestId("quiz-pick-list").locator('[data-testid^="quiz-pick-"]').first().click();
      await visible(page, "quiz-pick-reset");
      await page.waitForTimeout(800); // card entrance + returned-row tint settle
    },
  },

  "quiz/home-course-filtered": {
    run: async (page) => {
      await openQuiz(page, "/quiz");
      await page.getByTestId(`quiz-course-${COURSE_MATH}`).click();
      await expect(page.getByTestId(`quiz-course-${COURSE_MATH}`)).toHaveAttribute("aria-pressed", "true");
    },
  },

  "quiz/home-search-empty": {
    run: async (page) => {
      await openQuiz(page, "/quiz");
      await page.getByTestId("quiz-topic-search").fill("thermodynamics");
      await visible(page, "quiz-topic-search-empty");
    },
  },

  "quiz/home-resume-strip": {
    run: async (page) => {
      await patchJson(page, "GET", "/api/quiz/attempts", (body) => ({
        ...body,
        total: (body.total ?? 0) + 1,
        attempts: [inProgressAttempt(), ...(body.attempts ?? [])],
      }));
      await json(page, "GET", "/api/quiz/attempts/figma-resume", {
        quiz_id: "figma-resume",
        status: "in_progress",
        resumable: true,
        difficulty: "medium",
        concept_node_id: NODE_RECURSION,
        questions: MCQ.map(wire),
        responses: [{ question_index: 0, selected_index: 1, is_correct: true, answered_at: "2026-03-11T11:41:00Z" }],
        score: null,
        total: 3,
        created_at: "2026-03-11T11:40:00Z",
      });
      await page.goto("/quiz");
      await expect(page.getByTestId("quiz-resume-strip")).toContainText("1 of 3 answered", { timeout: LONG });
    },
  },

  "quiz/adjust-dialog": {
    run: async (page) => {
      await prime(page, { feedback: "as-you-go" });
      await openQuiz(page);
      await page.getByTestId("quiz-adjust").click();
      await visible(page, "quiz-adjust-dialog");
      await visible(page, "quiz-seg-count");
    },
  },

  "quiz/adjust-config-loading": {
    run: async (page) => {
      await holdOn(page, "GET", "/api/quiz/config");
      await page.goto(QUIZ_TREE);
      await visible(page, "quiz-proposal", LONG);
      await page.getByTestId("quiz-adjust").click();
      await visible(page, "quiz-adjust-dialog");
      await expect(page.getByTestId("quiz-adjust-dialog").locator(".skeleton").first()).toBeVisible();
    },
  },

  "quiz/adjust-at-end-note": {
    run: async (page) => {
      await prime(page, { feedback: "as-you-go" });
      await openQuiz(page);
      await page.getByTestId("quiz-adjust").click();
      await page.getByTestId("quiz-seg-feedback-at-end").click();
      await expect(page.getByTestId("quiz-adjust-dialog")).toContainText("Answers stay hidden while you work");
    },
  },

  "quiz/adjust-format-mixed": {
    run: async (page) => {
      await patchJson(page, "GET", "/api/quiz/config", (body) => ({
        ...body,
        question_types: ["multiple_choice", "short_answer", "numeric", "symbolic", "mixed"],
      }));
      await openQuiz(page);
      await page.getByTestId("quiz-adjust").click();
      await page.getByTestId("quiz-seg-format-mixed").click();
      await visible(page, "quiz-format-mixed-note");
    },
  },

  // ════════════════════════════ /quiz — question ════════════════════════════

  "quiz/generating": {
    run: async (page) => {
      await prime(page);
      await fakeQuiz(page, { generate: "hold" });
      await openQuiz(page);
      await page.getByTestId("quiz-start").click();
      await visible(page, "quiz-generating", 30_000);
    },
  },

  "quiz/q-mcq-active-empty": {
    run: async (page) => {
      await startQuiz(page);
      await onQuestion(page, MCQ[0]);
      await expect(page.getByTestId("quiz-submit-answer")).toBeDisabled();
    },
  },

  "quiz/q-mcq-selected": {
    run: async (page) => {
      await startQuiz(page);
      await onQuestion(page, MCQ[0]);
      await chooseOption(page, "B");
      await expect(page.getByTestId("quiz-submit-answer")).toBeEnabled();
    },
  },

  "quiz/q-submitting-answer": {
    run: async (page) => {
      await startQuiz(page, {}, { answer: "hold" });
      await onQuestion(page, MCQ[0]);
      await chooseOption(page, "B");
      await page.getByTestId("quiz-submit-answer").click();
      await expect(page.getByTestId("quiz-submit-answer")).toBeDisabled();
      await expect(page.getByTestId("quiz-answer-option-B")).toHaveAttribute("aria-checked", "true");
    },
  },

  "quiz/q-mcq-correct": {
    run: async (page) => {
      await startQuiz(page, { feedback: "as-you-go" });
      await answerShown(page, 0, "B");
      await expect(page.getByTestId("quiz-review-verdict")).toContainText("Correct");
      await visible(page, "quiz-next");
    },
  },

  "quiz/q-mcq-incorrect": {
    run: async (page) => {
      await startQuiz(page, { feedback: "as-you-go" });
      await answerShown(page, 0, "A");
      await expect(page.getByTestId("quiz-review-verdict")).toContainText("Not quite — the answer is B.");
    },
  },

  "quiz/q-at-end-answered": {
    run: async (page) => {
      await startQuiz(page);
      await walkAtEnd(page, ["B"]);
      await onQuestion(page, MCQ[1]);
      await expect(page.getByTestId("quiz-progress")).toHaveAttribute("aria-label", "Question 2 of 3");
      await expect(page.getByTestId("quiz-review-verdict")).toBeEmpty();
    },
  },

  "quiz/q-last-see-results": {
    run: async (page) => {
      await startQuiz(page, { feedback: "as-you-go" });
      await answerShown(page, 0, "B");
      await page.getByTestId("quiz-next").click();
      await answerShown(page, 1, "C");
      await page.getByTestId("quiz-next").click();
      await answerShown(page, 2, "B");
      await expect(page.getByTestId("quiz-next")).toHaveText("See results");
    },
  },

  "quiz/q-scoring": {
    run: async (page) => {
      await startQuiz(page, {}, { submit: "hold" });
      await walkAtEnd(page, RIGHT);
      await expect(page.getByText("Scoring…")).toBeVisible({ timeout: 30_000 });
    },
  },

  "quiz/q-material-context": {
    run: async (page) => {
      await startQuiz(page, {}, {
        questions: MCQ.map((q) => ({ ...q, material_context: "course_material" as const })),
      });
      await expect(page.getByTestId("quiz-material-context")).toContainText("Course material provided");
    },
  },

  "quiz/q-flagged": {
    run: async (page) => {
      await startQuiz(page);
      await onQuestion(page, MCQ[0]);
      await page.getByTestId("quiz-flag").click();
      await toast(page, "Noted — thanks.");
      await expect(page.getByTestId("quiz-flag")).toHaveAttribute("aria-pressed", "true");
    },
  },

  "quiz/q-short-delivery-toast": {
    run: async (page) => {
      await startQuiz(page, { count: 5 }, { questions: MCQ.slice(0, 2), requested: 5 });
      await toast(page, "Only 2 questions were ready for this concept.");
    },
  },

  "quiz/q-written-short": {
    run: async (page) => {
      await startQuiz(page, { questionFormat: "short_answer" }, { questions: [W_SHORT, W_NUMERIC, W_SYMBOLIC] });
      await page.getByTestId("quiz-written-answer").fill("the base case");
      await expect(page.getByTestId("quiz-format-hint")).toContainText("Write a brief answer");
    },
  },

  "quiz/q-written-numeric": {
    run: async (page) => {
      await startQuiz(page, { questionFormat: "numeric" }, { questions: [W_NUMERIC, W_SYMBOLIC, W_SHORT] });
      await page.getByTestId("quiz-written-answer").fill("5");
      await expect(page.getByTestId("quiz-written-readback")).toContainText("Reads as 5");
    },
  },

  "quiz/q-written-symbolic": {
    run: async (page) => {
      await startQuiz(page, { questionFormat: "symbolic" }, { questions: [W_SYMBOLIC, W_SHORT, W_NUMERIC] });
      await page.getByTestId("quiz-written-answer").fill("2(n + 1)");
      await expect(page.getByTestId("quiz-written-readback")).toContainText("2(n + 1)");
      await visible(page, "quiz-key-brackets");
    },
  },

  "quiz/q-written-incorrect": {
    run: async (page) => {
      await startQuiz(page, { feedback: "as-you-go", questionFormat: "short_answer" }, {
        questions: [W_SHORT, W_NUMERIC, W_SYMBOLIC],
      });
      await page.getByTestId("quiz-written-answer").fill("the recursive step");
      await page.getByTestId("quiz-submit-answer").click();
      await expect(page.getByTestId("quiz-review-verdict")).toContainText(
        "Not quite — the expected answer is the base case.",
        { timeout: 30_000 },
      );
    },
  },

  "quiz/leave-dialog": {
    run: async (page) => {
      await startQuiz(page);
      await onQuestion(page, MCQ[0]);
      await page.getByTestId("quiz-leave").click();
      await visible(page, "quiz-leave-dialog");
    },
  },

  "quiz/ask-sheet-seed": {
    run: async (page) => {
      await fakeTutor(page, "hold-start");
      await openAsk(page);
      await expect(page.getByTestId("quiz-ask-seed")).toContainText("You chose A");
    },
  },

  "quiz/ask-sheet-streaming": {
    run: async (page) => {
      await fakeTutor(page, "hold-reply");
      await openAsk(page);
      await expect(page.getByTestId("quiz-ask-panel").getByText("Thinking…")).toBeVisible({ timeout: 15_000 });
    },
  },

  "quiz/ask-sheet-reply+followup": {
    run: async (page) => {
      await fakeTutor(page, "reply");
      await openAsk(page);
      await expect(page.getByTestId("quiz-ask-panel")).toContainText("the empty list is exactly where", {
        ignoreCase: true,
        timeout: 30_000,
      });
      await page.getByTestId("quiz-ask-input").fill("Why does it overflow instead of looping forever?");
      await expect(page.getByTestId("quiz-ask-send")).toBeEnabled();
    },
  },

  "quiz/ask-sheet-error": {
    run: async (page) => {
      await fakeTutor(page, "error");
      await openAsk(page);
      await visible(page, "quiz-ask-retry", 30_000);
      await expect(page.getByTestId("quiz-ask-panel")).toContainText("Interrupted");
    },
  },

  "quiz/error-retryable": {
    run: async (page) => {
      await prime(page);
      await on(page, "POST", "/api/quiz/generate", (route) =>
        route.fulfill(
          quizErrorFulfill(502, "QUIZ_GENERATION_TIMEOUT", "upstream timeout", { requestId: "req-7f3a9c21" }),
        ),
      );
      await openQuiz(page);
      await page.getByTestId("quiz-start").click();
      await expect(page.getByTestId("quiz-error")).toContainText(QUIZ_ERROR_COPY.QUIZ_GENERATION_TIMEOUT, { timeout: 30_000 });
      await visible(page, "quiz-error-retry");
    },
  },

  "quiz/error-terminal": {
    run: async (page) => {
      await prime(page);
      await on(page, "POST", "/api/quiz/generate", (route) =>
        route.fulfill(quizErrorFulfill(429, "QUIZ_DAILY_LIMIT_REACHED", "daily cap")),
      );
      await openQuiz(page);
      await page.getByTestId("quiz-start").click();
      await expect(page.getByTestId("quiz-error")).toContainText(QUIZ_ERROR_COPY.QUIZ_DAILY_LIMIT_REACHED, { timeout: 30_000 });
      await expect(page.getByTestId("quiz-error-retry")).toHaveCount(0);
    },
  },

  // ════════════════════════════ /quiz — results ═════════════════════════════

  "quiz/results-missed": {
    run: async (page) => {
      await toResults(page);
      await expect(page.getByTestId("quiz-results-score")).toHaveText("2 of 3 correct");
      await visible(page, "quiz-missed-2");
      await visible(page, "quiz-results-xp", 15_000);
      await page.waitForTimeout(1_500); // growth animation
    },
  },

  "quiz/results-missed-explain-open": {
    run: async (page) => {
      await toResults(page);
      await page.getByTestId("quiz-missed-explain-2").click();
      await expect(page.getByTestId("quiz-missed-explain-2")).toHaveAttribute("aria-expanded", "true");
    },
  },

  "quiz/results-ask-sheet": {
    run: async (page) => {
      await fakeTutor(page, "reply");
      await toResults(page);
      await page.getByTestId("quiz-missed-ask-2").click();
      await expect(page.getByTestId("quiz-ask-seed")).toContainText("You chose A", { timeout: 15_000 });
      await expect(page.getByTestId("quiz-ask-panel")).toContainText("exactly where", { timeout: 30_000 });
    },
  },

  "quiz/results-perfect": {
    run: async (page) => {
      await toResults(page, {}, RIGHT);
      await visible(page, "quiz-results-perfect");
      await visible(page, "quiz-again");
      await page.waitForTimeout(1_500);
    },
  },

  "quiz/results-no-xp": {
    run: async (page) => {
      await toResults(page, { xp: false });
      await expect(page.getByTestId("quiz-results-score")).toBeVisible();
      await expect(page.getByTestId("quiz-results-xp")).toHaveCount(0);
    },
  },

  "quiz/results-queue-next": {
    run: async (page) => {
      await toResults(page, {}, ["B", "A", "B"], `/quiz?course=${COURSE_CS101}&from=dashboard&return=%2Fdashboard`);
      await visible(page, "quiz-next-concept");
    },
  },

  "quiz/results-missed-rerun": {
    run: async (page) => {
      await toResults(page);
      await page.getByTestId("quiz-practise-missed").click();
      await onQuestion(page, MCQ[1]);
      await chooseOption(page, "C");
      await page.getByTestId("quiz-submit-answer").click();
      await visible(page, "quiz-results", LONG);
      await expect(page.getByTestId("quiz-results")).toContainText("The ones you missed, again");
    },
  },

  "quiz/results-back-label": {
    run: async (page) => {
      await toResults(
        page,
        {},
        ["B", "A", "B"],
        `/quiz?concept=${NODE_RECURSION}&from=notes&note=${NOTE_CS}&return=${encodeURIComponent(`/notetaker?note=${NOTE_CS}`)}`,
      );
      await expect(page.getByTestId("quiz-back-to-source")).toHaveText("Back to your note");
    },
  },

  // ════════════════════════════ /study — guide ══════════════════════════════

  "study/guide-no-course": {
    run: async (page) => {
      await page.goto("/study");
      await expect(page.getByText("Pick a course to get started")).toBeVisible({ timeout: LONG });
      await expect(guidePicker(page, 1)).toHaveText(/Select a course first/);
    },
  },

  "study/guide-recent-empty": {
    run: async (page) => {
      await json(page, "GET", STUDY_CACHED, { guides: [] });
      await page.goto("/study");
      await expect(page.getByText("No generated guides yet.")).toBeVisible({ timeout: LONG });
    },
  },

  "study/guide-recent-populated": {
    run: async (page) => {
      await openRecentGuide(page);
      await expect(guidePicker(page, 1)).toHaveText(/Midterm Exam/, { timeout: 30_000 });
      await expect(page.getByRole("button", { name: /Regenerate/ })).toBeEnabled({ timeout: 30_000 });
    },
  },

  "study/guide-exams-loading": {
    run: async (page) => {
      await holdOn(page, "GET", STUDY_EXAMS);
      await pickCourseCs(page);
      await expect(guidePicker(page, 1)).toHaveText(/Loading…/);
    },
  },

  "study/guide-exams-error-toast": {
    run: async (page) => {
      await fail(page, "GET", STUDY_EXAMS, "Couldn't load the exams for this course.");
      await pickCourseCs(page);
      await toast(page, "Couldn't load the exams for this course.");
    },
  },

  "study/guide-no-exams": {
    run: async (page) => {
      await json(page, "GET", STUDY_EXAMS, { exams: [] });
      await pickCourseCs(page);
      await expect(page.getByText("No exams for this course yet")).toBeVisible({ timeout: 15_000 });
    },
  },

  "study/guide-choose-exam": {
    run: async (page) => {
      await pickCourseCs(page);
      await expect(page.getByText("Choose an exam", { exact: true })).toBeVisible({ timeout: 30_000 });
    },
  },

  "study/guide-loading": {
    run: async (page) => {
      await holdOn(page, "GET", STUDY_GUIDE);
      await openRecentGuide(page);
      await expect(page.locator(".skeleton").first()).toBeVisible({ timeout: 15_000 });
    },
  },

  "study/guide-populated": {
    run: async (page) => {
      await openRecentGuide(page);
      await expect(page.getByText("Covers variables, control flow, and functions.")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("Topic 1")).toBeVisible();
    },
  },

  "study/guide-regenerating": {
    run: async (page) => {
      await holdOn(page, "POST", STUDY_REGEN);
      await openRecentGuide(page);
      const btn = page.getByRole("button", { name: /Regenerate/ });
      await expect(btn).toBeEnabled({ timeout: 30_000 });
      await btn.click();
      await expect(page.getByRole("button", { name: /Regenerating…/ })).toBeVisible();
    },
  },

  "study/guide-regenerate-error": {
    run: async (page) => {
      await fail(page, "POST", STUDY_REGEN, "Couldn't regenerate that study guide.");
      await openRecentGuide(page);
      const btn = page.getByRole("button", { name: /Regenerate/ });
      await expect(btn).toBeEnabled({ timeout: 30_000 });
      await btn.click();
      await toast(page, "Couldn't regenerate that study guide.");
    },
  },

  "study/guide-missing": {
    run: async (page) => {
      await fail(page, "GET", STUDY_GUIDE, "Exam not found", 404);
      await openRecentGuide(page);
      await expect(page.getByText("That exam isn't around anymore")).toBeVisible({ timeout: 30_000 });
    },
  },

  "study/guide-missing-term": {
    run: async (page) => {
      await fail(page, "GET", STUDY_GUIDE, "CS101 has no offering in Spring 2026.", 404);
      await openRecentGuide(page);
      await expect(page.getByText("That guide isn't available")).toBeVisible({ timeout: 30_000 });
    },
  },

  "study/guide-failed": {
    run: async (page) => {
      await fail(page, "GET", STUDY_GUIDE, "The study guide service is busy. Try again in a minute.");
      await openRecentGuide(page);
      await expect(page.getByText("That guide didn't come through")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    },
  },

  // ════════════════════════════ /flashcards ═════════════════════════════════

  "cards/loading": {
    run: async (page) => {
      await holdOn(page, "GET", FLASHCARDS);
      await page.goto("/study?mode=cards");
      await expect(page.getByRole("button", { name: /Generate cards/ })).toBeVisible({ timeout: LONG });
      await expect(page.locator(".skeleton").first()).toBeVisible();
    },
  },

  "cards/empty-all": {
    run: async (page) => {
      await json(page, "GET", FLASHCARDS, { flashcards: [] });
      await page.goto("/study?mode=cards");
      await expect(page.getByText("Pick a course and generate cards from your library material.")).toBeVisible({ timeout: LONG });
    },
  },

  "cards/empty-course": {
    run: async (page) => {
      await openCards(page);
      await railRow(page, "CS101").first().click();
      await expect(page.getByText("Generate cards for this course to start reviewing.")).toBeVisible();
    },
  },

  "cards/front": {
    run: async (page) => {
      await openCards(page);
      await expect(page.getByText("Click or press Space to reveal")).toBeVisible();
      await expect(page.getByRole("button", { name: /easy/ })).toBeDisabled();
    },
  },

  "cards/back-flipped": {
    run: async (page) => {
      await openCards(page);
      await page.keyboard.press("Space");
      await expect(page.getByRole("button", { name: /easy/ })).toBeEnabled();
      await page.waitForTimeout(700); // 3D flip
    },
  },

  "cards/rated-next": {
    run: async (page) => {
      await json(page, "POST", "/api/flashcards/rate", { ok: true });
      await openCards(page);
      await page.keyboard.press("Space");
      await page.getByRole("button", { name: /easy/ }).click();
      await expect(page.getByText(/Card 2 of \d+/)).toBeVisible();
    },
  },

  "cards/topic-filtered": {
    run: async (page) => {
      await openCards(page);
      await page.getByRole("button", { name: "Linear Algebra", exact: true }).click();
      await expect(page.getByText("Card 1 of 3")).toBeVisible();
    },
  },

  "cards/course-filtered": {
    run: async (page) => {
      await openCards(page);
      await railRow(page, "MATH210").first().click();
      await expect(page.getByText("Card 1 of 3")).toBeVisible();
    },
  },

  "cards/generating": {
    run: async (page) => {
      await holdOn(page, "POST", "/api/flashcards/generate");
      await openCards(page);
      await railRow(page, "MATH210").first().click();
      await page.getByRole("button", { name: /Generate cards/ }).click();
      await expect(page.getByRole("button", { name: /Generating…/ })).toBeVisible();
    },
  },

  "cards/generate-warn": {
    run: async (page) => {
      await openCards(page);
      await page.getByRole("button", { name: /Generate cards/ }).click();
      await toast(page, "Pick a course or topic before generating.");
    },
  },

  "cards/generate-error": {
    run: async (page) => {
      await fail(page, "POST", "/api/flashcards/generate", "Couldn't generate cards right now.");
      await openCards(page);
      await railRow(page, "MATH210").first().click();
      await page.getByRole("button", { name: /Generate cards/ }).click();
      await toast(page, "Couldn't generate cards right now.");
    },
  },

  "cards/deleted": {
    run: async (page) => {
      await json(page, "DELETE", /^\/api\/flashcards\/[^/]+$/, { deleted: true });
      await openCards(page);
      await page.getByRole("button", { name: /Delete card/ }).click();
      await toast(page, "Card deleted");
    },
  },

  // ── Import modal ──

  "import/paste-empty": {
    run: async (page) => {
      const dialog = await openImport(page);
      await expect(dialog).toContainText("No cards parsed yet.");
    },
  },

  "import/paste-parsed": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByPlaceholder("e.g. Cell Biology — Chapter 5").fill("Cell Biology — Organelles");
      await pasteCards(dialog);
      await expect(dialog).toContainText("4 valid · 0 flagged");
    },
  },

  "import/paste-table-flagged-row": {
    run: async (page) => {
      const dialog = await openImport(page);
      // Auto-detect (lib/flashcardParsers.detectDelimiters) scores newline rows
      // at 4/5 = 0.8 here, but PASTE's Mitochondria definition carries a ";",
      // and a ";"-split yields 2 tab-bearing chunks = 1.0, so it would pick
      // Semicolon and parse 2 cards. Drop that ";" so newline/tab wins.
      const rows = PASTE.replace("respiration; makes", "respiration, makes");
      await pasteCards(dialog, `${rows}\nEndoplasmic reticulum`);
      await expect(dialog).toContainText("4 valid · 1 flagged");
    },
  },

  "import/custom-separator": {
    run: async (page) => {
      const dialog = await openImport(page);
      await pasteCards(
        dialog,
        [
          "Mitochondria :: Site of aerobic respiration",
          "Ribosome :: Translates mRNA into protein",
          "Lysosome :: Sac of digestive enzymes",
        ].join("\n"),
      );
      // Listbox triggers in the dialog: course, term separator, card separator.
      await dialog.locator('button[aria-haspopup="listbox"]').nth(1).click();
      await page.getByRole("option", { name: "Custom…" }).click();
      await dialog.getByPlaceholder("Custom separator").fill("::");
      await expect(dialog).toContainText("3 valid · 0 flagged");
    },
  },

  "import/reverse-on": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByPlaceholder("e.g. Cell Biology — Chapter 5").fill("Cell Biology — Organelles");
      await pasteCards(dialog);
      await dialog.getByLabel("Generate reverse cards").check();
      await expect(dialog.getByRole("button", { name: "Import 8 cards" })).toBeVisible();
    },
  },

  "import/cleaning": {
    run: async (page) => {
      await holdOn(page, "POST", "/api/flashcards/import/cleanup");
      const dialog = await openImport(page);
      await pasteCards(dialog);
      await dialog.getByRole("button", { name: /Clean up with AI/ }).click();
      await expect(dialog.getByRole("button", { name: /Cleaning…/ })).toBeVisible();
    },
  },

  "import/cloze": {
    run: async (page) => {
      await json(page, "POST", "/api/flashcards/import/cloze", {
        cards: [
          { front: "The ____ is the site of aerobic respiration.", back: "mitochondrion" },
          { front: "Ribosomes translate ____ into a polypeptide chain.", back: "mRNA" },
          { front: "The Golgi apparatus modifies, sorts and ____ proteins.", back: "packages" },
        ],
      });
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "Cloze deletion (AI)" }).click();
      await dialog
        .locator("textarea")
        .fill(
          "The mitochondrion is the site of aerobic respiration. Ribosomes translate mRNA into a polypeptide chain, and the Golgi apparatus modifies, sorts and packages proteins.",
        );
      await dialog.getByRole("button", { name: "Generate cloze cards" }).click();
      await expect(dialog).toContainText("3 valid · 0 flagged");
    },
  },

  "import/upload-tab": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "Upload", exact: true }).click();
      await expect(dialog).toContainText("Drop or click to upload .csv");
    },
  },

  "import/upload-errors": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "Upload", exact: true }).click();
      await dialog.locator('input[type="file"]').setInputFiles({
        name: "biology-deck.doc",
        mimeType: "application/msword",
        buffer: Buffer.from("not a deck"),
      });
      await toast(page, "Unsupported file type: .doc");
    },
  },

  "import/url-tab": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "URL", exact: true }).click();
      await expect(dialog.getByPlaceholder("https://quizlet.com/12345/some-set")).toBeVisible();
    },
  },

  "import/url-blocked": {
    run: async (page) => {
      await fail(page, "POST", "/api/flashcards/import/parse", "Quizlet blocked the request", 422);
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "URL", exact: true }).click();
      await dialog.getByPlaceholder("https://quizlet.com/12345/some-set").fill("https://quizlet.com/512839/cell-organelles");
      await dialog.getByRole("button", { name: "Fetch cards" }).click();
      await expect(dialog).toContainText("Couldn't fetch this URL");
    },
  },

  "import/url-error": {
    run: async (page) => {
      await fail(page, "POST", "/api/flashcards/import/parse", "Upstream timed out", 502);
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "URL", exact: true }).click();
      await dialog.getByPlaceholder("https://quizlet.com/12345/some-set").fill("https://quizlet.com/512839/cell-organelles");
      await dialog.getByRole("button", { name: "Fetch cards" }).click();
      await toast(page, /Fetch failed/);
    },
  },

  "import/ai-tab-paste": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "AI", exact: true }).click();
      await expect(dialog.getByPlaceholder("Paste lecture notes, a study guide, or a course topic.")).toBeVisible();
    },
  },

  "import/ai-tab-library": {
    run: async (page) => {
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "AI", exact: true }).click();
      await dialog.getByRole("button", { name: "From library" }).click();
      await expect(dialog.getByText(/Pick a document…|No library documents yet/)).toBeVisible();
    },
  },

  "import/ai-tab-generating": {
    run: async (page) => {
      await holdOn(page, "POST", "/api/flashcards/import/generate");
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "AI", exact: true }).click();
      await dialog
        .getByPlaceholder("Paste lecture notes, a study guide, or a course topic.")
        .fill("Cell organelles: mitochondria, ribosomes, the Golgi apparatus and lysosomes, and what each one does.");
      await dialog.getByRole("button", { name: "Generate cards" }).click();
      await expect(dialog.getByRole("button", { name: "Generating…" })).toBeVisible();
    },
  },

  "import/photo-tab": {
    run: async (page) => {
      await holdOn(page, "POST", "/api/flashcards/import/parse");
      const dialog = await openImport(page);
      await dialog.getByRole("button", { name: "Photo", exact: true }).click();
      await dialog.locator('input[type="file"]').setInputFiles({
        name: "whiteboard.png",
        mimeType: "image/png",
        buffer: Buffer.from("89504e470d0a1a0a", "hex"),
      });
      await expect(dialog).toContainText("Reading image…");
    },
  },

  "import/committing": {
    run: async (page) => {
      await holdOn(page, "POST", "/api/flashcards/import/commit");
      const dialog = await openImport(page);
      await dialog.getByPlaceholder("e.g. Cell Biology — Chapter 5").fill("Cell Biology — Organelles");
      await pasteCards(dialog);
      await dialog.getByRole("button", { name: "Import 4 cards" }).click();
      await expect(dialog.getByRole("button", { name: "Importing…" })).toBeVisible();
    },
  },

  "import/commit-error": {
    run: async (page) => {
      await fail(page, "POST", "/api/flashcards/import/commit", "Couldn't save these cards.");
      const dialog = await openImport(page);
      await dialog.getByPlaceholder("e.g. Cell Biology — Chapter 5").fill("Cell Biology — Organelles");
      await pasteCards(dialog);
      await dialog.getByRole("button", { name: "Import 4 cards" }).click();
      await toast(page, /Import failed/);
    },
  },

  // ════════════════════════════ /notetaker ══════════════════════════════════

  "notes/loading": {
    run: async (page) => {
      await holdOn(page, "GET", NOTES_LIST);
      await page.goto("/notetaker");
      await expect(page.getByText("Loading notes…")).toBeVisible({ timeout: LONG });
    },
  },

  "notes/empty": {
    run: async (page) => {
      await json(page, "GET", NOTES_LIST, { notes: [] });
      await page.goto("/notetaker");
      await expect(page.getByRole("button", { name: /Create your first note/ })).toBeEnabled({ timeout: LONG });
    },
  },

  "notes/empty-no-courses": {
    run: async (page) => {
      await json(page, "GET", NOTES_LIST, { notes: [] });
      await json(page, "GET", COURSES, { courses: [] });
      await page.goto("/notetaker");
      await expect(page.getByText("Add a course first to start taking notes.")).toBeVisible({ timeout: LONG });
    },
  },

  "notes/course-picker": {
    run: async (page) => {
      await openNote(page);
      await page.getByRole("button", { name: /New note/ }).click();
      await expect(page.getByText("Which course is this for?")).toBeVisible();
    },
  },

  "notes/three-pane": {
    run: async (page) => {
      await openNote(page);
      await expect(page.getByRole("textbox", { name: "Untitled note" })).toHaveValue("Week 1 — Variables");
      await expect(page.getByText("Linked concepts")).toBeVisible();
    },
  },

  "notes/list-filtered": {
    run: async (page) => {
      await openNote(page);
      await page.getByRole("button", { name: "CS101", exact: true }).first().click();
      await expect(page.getByText(/^\d+ \/ \d+$/)).toBeVisible();
    },
  },

  "notes/list-no-match": {
    run: async (page) => {
      await openNote(page);
      await page.getByPlaceholder("Search notes…").fill("thermodynamics");
      await expect(page.getByText("No notes match the current filters.")).toBeVisible();
    },
  },

  "notes/saving": {
    run: async (page) => {
      await holdOn(page, "PATCH", /^\/api\/notes\/[^/]+$/);
      await openNote(page);
      await noteBody(page).press("End");
      await noteBody(page).pressSequentially(" Strings are immutable.");
      await expect(page.getByText("Saving…")).toBeVisible({ timeout: 10_000 });
    },
  },

  "notes/saved": {
    run: async (page) => {
      await json(page, "PATCH", /^\/api\/notes\/[^/]+$/, { id: NOTE_CS });
      await openNote(page);
      await noteBody(page).press("End");
      await noteBody(page).pressSequentially(" Strings are immutable.");
      await expect(page.getByText("Saved · just now")).toBeVisible({ timeout: 10_000 });
    },
  },

  "notes/no-concepts": {
    run: async (page) => {
      await json(page, "GET", noteConcepts(), { concepts: [] });
      await openNote(page);
      await expect(page.getByText("No concepts linked yet.", { exact: false })).toBeVisible();
      await expect(page.getByRole("button", { name: "Generate quiz" })).toBeDisabled();
    },
  },

  "notes/concepts-linked": {
    run: async (page) => {
      await json(page, "GET", noteConcepts(), { concepts: LINKED });
      await openNote(page);
      await expect(page.getByRole("button", { name: "Unlink Recursion" })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole("button", { name: "Generate quiz" })).toBeEnabled();
    },
  },

  "notes/concept-picker": {
    run: async (page) => {
      await openNote(page);
      await page.getByRole("button", { name: /Link concept/ }).click();
      await expect(page.getByPlaceholder("Search concepts…")).toBeVisible();
      await expect(page.getByText("Loading…")).toHaveCount(0, { timeout: 30_000 });
    },
  },

  "notes/tags-empty": {
    run: async (page) => {
      await patchJson(page, "GET", NOTES_LIST, (body) => ({
        ...body,
        notes: (body.notes ?? []).map((n: { id: string }) => (n.id === NOTE_CS ? { ...n, tags: [] } : n)),
      }));
      await openNote(page);
      await expect(page.getByText("No tags.")).toBeVisible();
    },
  },

  "notes/tag-adding": {
    run: async (page) => {
      await openNote(page);
      await page.getByRole("button", { name: "+ Add" }).click();
      await page.getByPlaceholder("tag").fill("midterm");
      await expect(page.getByPlaceholder("tag")).toHaveValue("midterm");
    },
  },

  "notes/busy-summarize": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/notes/${NOTE_CS}/summarize`);
      await openNote(page);
      await page.getByRole("button", { name: "Summarize note" }).click();
      await expect(page.getByRole("button", { name: "Summarizing…" })).toBeVisible();
    },
  },

  "notes/busy-extract": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/notes/${NOTE_CS}/extract-concepts`);
      await openNote(page);
      await page.getByRole("button", { name: "Extract concepts" }).click();
      await expect(page.getByRole("button", { name: "Extracting…" })).toBeVisible();
    },
  },

  "notes/busy-quiz": {
    run: async (page) => {
      await json(page, "GET", noteConcepts(), { concepts: LINKED });
      await holdOn(page, "POST", `/api/notes/${NOTE_CS}/generate-quiz`);
      await openNote(page);
      const btn = page.getByRole("button", { name: "Generate quiz" });
      await expect(btn).toBeEnabled({ timeout: 15_000 });
      await btn.click();
      await expect(page.getByRole("button", { name: "Building quiz…" })).toBeVisible();
    },
  },

  "notes/busy-tutor": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/notes/${NOTE_CS}/send-to-tutor`);
      await openNote(page);
      await page.getByRole("button", { name: "Send to tutor" }).click();
      await expect(page.getByRole("button", { name: "Opening tutor…" })).toBeVisible();
    },
  },

  "notes/busy-delete": {
    run: async (page) => {
      await holdOn(page, "DELETE", `/api/notes/${NOTE_CS}`);
      await openNote(page);
      await page.getByRole("button", { name: /Delete note/ }).click();
      await expect(page.getByRole("button", { name: /Deleting…/ })).toBeVisible();
    },
  },

  "notes/summary-shown": {
    run: async (page) => {
      await json(page, "POST", `/api/notes/${NOTE_CS}/summarize`, { summary: NOTE_SUMMARY });
      await openNote(page);
      await page.getByRole("button", { name: "Summarize note" }).click();
      await expect(page.getByText("Last summary")).toBeVisible({ timeout: 15_000 });
    },
  },

  "notes/action-error-toast": {
    run: async (page) => {
      await fail(page, "POST", `/api/notes/${NOTE_CS}/summarize`, "Couldn't summarize this note.");
      await openNote(page);
      await page.getByRole("button", { name: "Summarize note" }).click();
      await toast(page, "Couldn't summarize this note.");
    },
  },

  "notes/fullscreen": {
    run: async (page) => {
      await openFullscreenChat(page);
      await expect(page.getByText("Esc to exit")).toBeVisible();
    },
  },

  "notes/chat-empty": {
    run: async (page) => {
      await openFullscreenChat(page);
      await expect(page.getByPlaceholder("Ask a quick question…")).toBeVisible();
    },
  },

  "notes/chat-thinking": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/notes/${NOTE_CS}/chat`);
      await openFullscreenChat(page);
      await sendNoteChat(page);
      await expect(page.getByText("Sapling is thinking…")).toBeVisible();
    },
  },

  "notes/chat-replied": {
    run: async (page) => {
      await json(page, "POST", `/api/notes/${NOTE_CS}/chat`, { reply: NOTE_CHAT_REPLY });
      await openFullscreenChat(page);
      await sendNoteChat(page);
      await expect(page.getByText(NOTE_CHAT_REPLY.slice(0, 40))).toBeVisible({ timeout: 15_000 });
    },
  },

  "notes/chat-error": {
    run: async (page) => {
      await fail(page, "POST", `/api/notes/${NOTE_CS}/chat`, "Chat is unavailable.");
      await openFullscreenChat(page);
      await sendNoteChat(page);
      await expect(page.getByText("Sorry — something went wrong. Try again?")).toBeVisible({ timeout: 15_000 });
    },
  },

  "notes/deep-link-note": {
    run: async (page) => {
      await openNote(page, NOTE_MATH);
      await expect(page.getByRole("textbox", { name: "Untitled note" })).toHaveValue("Vectors Overview");
    },
  },

  // ════════════════════════════ /library ════════════════════════════════════

  "lib/loading": {
    run: async (page) => {
      await holdOn(page, "GET", DOCS);
      await page.goto("/library");
      await visible(page, "library-search", LONG);
      await expect(page.locator(".skeleton").first()).toBeVisible();
    },
  },

  "lib/empty": {
    run: async (page) => {
      await json(page, "GET", DOCS, { documents: [] });
      await page.goto("/library");
      await expect(page.getByText("Your library is quiet")).toBeVisible({ timeout: LONG });
    },
  },

  "lib/upload-disabled": {
    run: async (page) => {
      await json(page, "GET", COURSES, { courses: [] });
      await page.goto("/library");
      await expect(page.getByTestId("library-upload")).toBeDisabled({ timeout: LONG });
    },
  },

  "lib/grid": {
    run: async (page) => {
      await openLibrary(page);
      await expect(page.getByRole("button", { name: "Grid", exact: true })).toHaveAttribute("aria-pressed", "true");
    },
  },

  "lib/list": {
    run: async (page) => {
      await openLibrary(page);
      await page.getByRole("button", { name: "List", exact: true }).click();
      await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
      await visible(page, `library-doc-${DOC_MATH}`);
    },
  },

  "lib/category-filtered": {
    run: async (page) => {
      await openLibrary(page);
      await page.getByRole("button", { name: "lecture notes", exact: true }).click();
      await expect(page.getByRole("button", { name: "lecture notes", exact: true })).toHaveAttribute("aria-pressed", "true");
      await visible(page, `library-doc-${DOC_MATH}`);
    },
  },

  "lib/course-rail": {
    run: async (page) => {
      await openLibrary(page);
      await visible(page, "library-course-filter-all");
      await visible(page, `library-course-filter-${COURSE_CS101}`);
    },
  },

  "lib/course-scan": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/documents/course/${COURSE_CS101}/scan-concepts`);
      await openLibrary(page);
      await page.getByTestId(`library-course-filter-${COURSE_CS101}`).click();
      await page.getByTestId("library-course-scan").click();
      await expect(page.getByTestId("library-course-scan")).toHaveText(/Scanning…/);
    },
  },

  "lib/detail-modal": {
    run: async (page) => {
      await openDetail(page);
      await visible(page, "library-detail-scan");
    },
  },

  "lib/detail-concept-open": {
    run: async (page) => {
      await openDetail(page);
      await page.getByTestId("library-concept-toggle-0").click();
      await expect(page.getByText("Objects with magnitude and direction in a vector space.")).toBeVisible();
    },
  },

  "lib/detail-scanning": {
    run: async (page) => {
      await holdOn(page, "POST", `/api/documents/doc/${DOC_MATH}/scan-concepts`);
      await openDetail(page);
      await page.getByTestId("library-detail-scan").click();
      await expect(page.getByTestId("library-detail-scan")).toHaveText(/Scanning…/);
    },
  },

  "lib/detail-scanned": {
    run: async (page) => {
      await json(page, "POST", `/api/documents/doc/${DOC_MATH}/scan-concepts`, {
        concepts: ["Vectors", "Matrices", "Linear Transformations", "Eigenvalues"],
        added: 2,
        existing: 2,
      });
      await openDetail(page);
      await page.getByTestId("library-detail-scan").click();
      await expect(page.getByText("Added 2 new concepts on top of the existing 2.")).toBeVisible({ timeout: 15_000 });
    },
  },

  "lib/detail-delete-armed": {
    run: async (page) => {
      await openDetail(page);
      await page.getByTestId("library-detail-delete").click();
      await expect(page.getByTestId("library-detail-delete")).toContainText("Click again to confirm");
    },
  },

  "lib/deleted": {
    run: async (page) => {
      await json(page, "DELETE", `/api/documents/doc/${DOC_MATH}`, { deleted: true });
      await openDetail(page);
      await page.getByTestId("library-detail-delete").click();
      await page.getByTestId("library-detail-delete").click();
      await toast(page, "Document deleted");
    },
  },

  "lib/syllabus-toast": {
    run: async (page) => {
      await uploadToDone(page, "syllabus");
      await page.getByTestId("upload-modal-done").click();
      await toast(page, "Syllabus processed — new assignments will appear on the calendar.");
    },
  },

  // ── Upload modal ──

  "upload/empty": {
    run: async (page) => {
      await openUpload(page);
      await expect(page.getByTestId("upload-modal")).toContainText("0 files queued");
      await expect(page.getByTestId("upload-modal-submit")).toBeDisabled();
    },
  },

  "upload/dragging": {
    run: async (page) => {
      await openUpload(page);
      const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
      await page.getByTestId("upload-modal-dropzone").dispatchEvent("dragenter", { dataTransfer });
      await page.getByTestId("upload-modal-dropzone").dispatchEvent("dragover", { dataTransfer });
      await expect(page.getByTestId("upload-modal-dropzone")).toContainText("Drop to add files");
    },
  },

  "upload/rejected-toast": {
    run: async (page) => {
      await openUpload(page);
      await page.getByTestId("upload-modal-file-input").setInputFiles({
        name: "lecture-notes.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("plain text"),
      });
      await toast(page, "lecture-notes.txt: only PDF / DOCX / PPTX are accepted.");
    },
  },

  "upload/course-search-results": {
    run: async (page) => {
      await json(page, "GET", "/api/onboarding/courses", {
        courses: [
          { id: "figma-cat-cs201", course_code: "CS201", course_name: "Data Structures" },
          { id: "figma-cat-cs210", course_code: "CS210", course_name: "Computer Systems" },
          { id: "figma-cat-cs230", course_code: "CS230", course_name: "Discrete Mathematics" },
        ],
      });
      await openUpload(page);
      await page.getByTestId("upload-modal-course-search").fill("CS2");
      await visible(page, "upload-modal-course-result-figma-cat-cs201", 15_000);
    },
  },

  "upload/course-added": {
    run: async (page) => {
      await json(page, "GET", "/api/onboarding/courses", {
        courses: [{ id: "figma-cat-cs201", course_code: "CS201", course_name: "Data Structures" }],
      });
      await json(page, "POST", COURSES, { course_id: "figma-cat-cs201", already_existed: false });
      await openUpload(page);
      await page.getByTestId("upload-modal-course-search").fill("CS201");
      await page.getByTestId("upload-modal-course-result-figma-cat-cs201").click();
      await toast(page, "Added CS201");
    },
  },

  "upload/queued": {
    run: async (page) => {
      await queueFile(page);
      await expect(page.getByTestId("upload-modal-file-row-0")).toContainText("queued");
      await expect(page.getByTestId("upload-modal-submit")).toBeEnabled();
    },
  },

  "upload/processing-sse": {
    run: async (page) => {
      await holdOn(page, "POST", UPLOAD);
      await queueFile(page);
      await page.getByTestId("upload-modal-submit").click();
      await expect(page.getByTestId("upload-modal-file-row-0")).toContainText("processing…");
      await expect(page.getByTestId("upload-modal-file-row-0")).toContainText("Starting upload…");
    },
  },

  "upload/done": {
    run: async (page) => {
      await uploadToDone(page);
      await expect(page.getByTestId("upload-modal-file-row-0")).toContainText("Base Case");
      await visible(page, "upload-modal-file-reanalyze-0");
    },
  },

  "upload/category-changed": {
    run: async (page) => {
      await json(page, "PATCH", "/api/documents/doc/figma-upload-doc", { id: "figma-upload-doc", category: "slides" });
      await uploadToDone(page);
      await page.getByTestId("upload-modal-file-row-0").getByRole("button", { name: "Category", exact: true }).click();
      await page.getByRole("option", { name: "Slides" }).click();
      await toast(page, "Category updated");
    },
  },

  "upload/error": {
    run: async (page) => {
      await sse(page, "POST", UPLOAD, [
        uploadEvent("status", "received", "Received lecture-05-recursion.pdf"),
        uploadEvent("progress", "extracting", "Extracting text…"),
        uploadEvent("error", "failed", "Couldn't read any text from this PDF — it may be a scan.", {
          request_id: "5c1e9a7b-2f04-4d8e-9b13-6a0f2d7c4e11",
        }),
      ]);
      await queueFile(page);
      await page.getByTestId("upload-modal-submit").click();
      await visible(page, "upload-modal-file-retry-0", 30_000);
      await expect(page.getByTestId("upload-modal-file-row-0")).toContainText("Reference:");
    },
  },
};
