/**
 * Characterization of `reduce` / `resumeFrom` beyond machine.test.ts: every
 * event from every phase (identity or where it lands), plus the field-level
 * branches the scenario tests there don't reach. Pinned on the switch-based
 * reducer before it was split into per-event handlers.
 */
import { describe, expect, it } from "vitest";
import { initialSession, reduce, type QuizEvent, type StartRequest } from "./machine";
import { QUIZ_ERROR_COPY } from "./errors";
import type {
  AnswerResult,
  AttemptDetail,
  GenerateResult,
  Phase,
  QuizConfig,
  QuizItem,
  QuizPrefs,
  QuizSession,
  QuizSource,
  SubmitResult,
  WireQuestion,
} from "./types";

const CONFIG: QuizConfig = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice", "short_answer"],
};
const PREFS: QuizPrefs = { count: null, difficulty: null, feedback: "at-end" };
const SOURCE: QuizSource = { kind: "tree", returnTo: "/tree?node=c1", conceptId: "c1" };
const NETWORK = { code: "NETWORK" as const, message: "offline", retryable: true };
const SUBMITTED: SubmitResult = {
  score: 1, total: 3, mastery_before: 0.1, mastery_after: 0.2, results: [],
};
const XP = { before: 1, after: 2, streak: 3 };

function mc(id: number): WireQuestion {
  return {
    id,
    question: `Q${id}?`,
    options: [{ label: "A", text: "a" }, { label: "B", text: "b" }],
    difficulty: "medium",
  };
}

function written(id: number): WireQuestion {
  return { id, type: "short_answer", question: `W${id}?`, options: [], difficulty: "easy" };
}

function generated(questions: WireQuestion[]): GenerateResult {
  return {
    quiz_id: "attempt-1",
    questions,
    requested_difficulty: "medium",
    resolved_difficulty: "medium",
    requested_count: questions.length,
    delivered_count: questions.length,
  };
}

function answered(index: number, extra: Partial<AnswerResult> = {}): AnswerResult {
  return {
    question_index: index,
    question_id: index + 1,
    is_correct: true,
    correct_index: 1,
    explanation: `because ${index}`,
    next_question: null,
    recorded: true,
    ...extra,
  };
}

function start(overrides: Partial<StartRequest> = {}): StartRequest {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: "c1" },
    conceptId: "c1",
    courseId: "course-1",
    ...overrides,
  };
}

function home(): QuizSession {
  return initialSession({ source: SOURCE, concept: "c1" }, CONFIG, PREFS);
}

function active(questions: WireQuestion[] = [mc(1), mc(2), mc(3)], feedback: "at-end" | "as-you-go" = "at-end") {
  const base = { ...home(), config: { ...home().config, feedback } };
  const generating = reduce(base, { type: "START", start: start(), config: base.config });
  return reduce(generating, { type: "GENERATED", result: generated(questions) });
}

function detail(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    quiz_id: "attempt-1",
    status: "in_progress",
    resumable: true,
    difficulty: "hard",
    concept_node_id: "c1",
    questions: [mc(1), mc(2), mc(3)],
    responses: [],
    score: null,
    total: null,
    created_at: "2026-08-22T09:00:00Z",
    ...overrides,
  };
}

function response(question_index: number, selected_index: number | null, extra = {}) {
  return { question_index, selected_index, is_correct: true, answered_at: "2026-08-22T10:00:00Z", ...extra };
}

const PHASES: Phase[] = [
  "home", "configuring", "generating", "active", "answered",
  "confirm-leave", "submitting", "results", "paused", "error",
];

const EVENTS: QuizEvent[] = [
  { type: "CONFIGURE", open: true },
  { type: "START", start: start({ conceptId: "c9" }), config: { count: 3, difficulty: "easy", feedback: "at-end" } },
  { type: "GENERATED", result: generated([mc(7), mc(8)]) },
  { type: "GENERATE_FAILED", error: NETWORK },
  { type: "SELECT", index: 0 },
  { type: "WRITE", text: "draft" },
  { type: "SUBMIT_ANSWER" },
  { type: "ANSWER_RECORDED", result: answered(1) },
  { type: "ANSWER_FAILED", error: NETWORK },
  { type: "NEXT" },
  { type: "GO_TO", index: 2 },
  { type: "REQUEST_LEAVE" },
  { type: "CANCEL_LEAVE" },
  { type: "CONFIRM_LEAVE" },
  { type: "RESUME", detail: detail({ responses: [response(0, 1)] }), stored: null },
  { type: "FINISH" },
  { type: "SUBMITTED", result: SUBMITTED, xp: XP },
  { type: "SUBMIT_FAILED", error: NETWORK },
  { type: "PRACTISE_MISSED", missedCount: 2, numQuestions: 2 },
  { type: "NEXT_IN_QUEUE" },
  { type: "EXIT" },
  { type: "CANCEL" },
  { type: "FLAG" },
  { type: "DISMISS_ERROR" },
  { type: "FAILED", error: NETWORK },
  { type: "SET_CONFIG", config: { count: 10, difficulty: "hard", feedback: "as-you-go" } },
];

/** A mid-quiz session (cursor 1, a written item, a verdict on item 0, a
 *  queue) re-labelled with each phase in turn. */
function matrixBase(): QuizSession {
  let s = active([mc(1), written(2), mc(3)], "at-end");
  s = reduce(s, { type: "SELECT", index: 1 });
  s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
  return { ...s, scope: { kind: "due", queue: ["c1", "c2"] } };
}

function digest(before: QuizSession, after: QuizSession): string {
  if (after === before) return "=";
  const item = after.items[after.cursor];
  return [
    after.phase,
    `c${after.cursor}`,
    `n${after.items.length}`,
    after.attemptId ?? "-",
    after.error?.code ?? "-",
    item ? `sel${item.selectedIndex ?? "-"}/txt${item.answerText ?? "-"}/flag${item.flagged ? 1 : 0}` : "noitem",
  ].join(" ");
}

describe("every event from every phase", () => {
  it("is either refused (=) or lands as recorded", () => {
    const table: Record<string, Record<string, string>> = {};
    for (const phase of PHASES) {
      const before = { ...matrixBase(), phase };
      table[phase] = Object.fromEntries(EVENTS.map(e => [e.type, digest(before, reduce(before, e))]));
    }
    expect(table).toMatchInlineSnapshot(`
      {
        "active": {
          "ANSWER_FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "ANSWER_RECORDED": "active c2 n3 attempt-1 - sel-/txt-/flag0",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "=",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "active c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "active c2 n3 attempt-1 - sel-/txt-/flag0",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "confirm-leave c1 n3 attempt-1 - sel-/txt-/flag0",
          "RESUME": "=",
          "SELECT": "active c1 n3 attempt-1 - sel0/txt-/flag0",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "active c1 n3 attempt-1 - sel-/txtdraft/flag0",
        },
        "answered": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "=",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "answered c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "active c2 n3 attempt-1 - sel-/txt-/flag0",
          "NEXT": "active c2 n3 attempt-1 - sel-/txt-/flag0",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "confirm-leave c1 n3 attempt-1 - sel-/txt-/flag0",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "configuring": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "configuring c1 n3 attempt-1 - sel-/txt-/flag0",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "FINISH": "=",
          "FLAG": "configuring c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "configuring c1 n3 attempt-1 - sel-/txt-/flag0",
          "START": "generating c0 n0 - - noitem",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "confirm-leave": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "active c1 n3 attempt-1 - sel-/txt-/flag0",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "paused c1 n3 attempt-1 - sel-/txt-/flag0",
          "DISMISS_ERROR": "=",
          "EXIT": "=",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "confirm-leave c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "error": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "active c1 n3 attempt-1 - sel-/txt-/flag0",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "error c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "generating": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "home c1 n3 attempt-1 - sel-/txt-/flag0",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "generating c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "active c0 n2 attempt-1 - sel-/txt-/flag0",
          "GENERATE_FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "home": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "configuring c1 n3 attempt-1 - sel-/txt-/flag0",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "FINISH": "=",
          "FLAG": "home c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "active c1 n3 attempt-1 - sel-/txt-/flag0",
          "SELECT": "=",
          "SET_CONFIG": "home c1 n3 attempt-1 - sel-/txt-/flag0",
          "START": "generating c0 n0 - - noitem",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "paused": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "FINISH": "=",
          "FLAG": "paused c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "active c1 n3 attempt-1 - sel-/txt-/flag0",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "results": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "=",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "home c0 n0 - - noitem",
          "FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "FINISH": "=",
          "FLAG": "results c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "generating c0 n0 - - noitem",
          "PRACTISE_MISSED": "generating c0 n0 - - noitem",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "results c1 n3 attempt-1 - sel-/txt-/flag0",
          "START": "generating c0 n0 - - noitem",
          "SUBMITTED": "=",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "=",
          "WRITE": "=",
        },
        "submitting": {
          "ANSWER_FAILED": "=",
          "ANSWER_RECORDED": "=",
          "CANCEL": "active c1 n3 attempt-1 - sel-/txt-/flag0",
          "CANCEL_LEAVE": "=",
          "CONFIGURE": "=",
          "CONFIRM_LEAVE": "=",
          "DISMISS_ERROR": "=",
          "EXIT": "=",
          "FAILED": "=",
          "FINISH": "=",
          "FLAG": "submitting c1 n3 attempt-1 - sel-/txt-/flag1",
          "GENERATED": "=",
          "GENERATE_FAILED": "=",
          "GO_TO": "=",
          "NEXT": "=",
          "NEXT_IN_QUEUE": "=",
          "PRACTISE_MISSED": "=",
          "REQUEST_LEAVE": "=",
          "RESUME": "=",
          "SELECT": "=",
          "SET_CONFIG": "=",
          "START": "=",
          "SUBMITTED": "results c1 n3 attempt-1 - sel-/txt-/flag0",
          "SUBMIT_ANSWER": "=",
          "SUBMIT_FAILED": "error c1 n3 attempt-1 NETWORK sel-/txt-/flag0",
          "WRITE": "=",
        },
      }
    `);
  });

  it("returns the same object for an event type it does not know", () => {
    const s = matrixBase();
    expect(reduce(s, { type: "NOPE" } as unknown as QuizEvent)).toBe(s);
    expect(reduce(s, { type: "toString" } as unknown as QuizEvent)).toBe(s);
  });
});

describe("field-level transitions", () => {
  it("START from configuring carries the request and a retry's source attempt", () => {
    const configuring = reduce(home(), { type: "CONFIGURE", open: true });
    const cfg = { count: 3, difficulty: "easy", feedback: "as-you-go" as const };
    const s = reduce(configuring, {
      type: "START",
      start: start({ intent: "review", conceptId: "c4", courseId: null, sourceAttemptId: "old-1" }),
      config: cfg,
    });
    expect(s).toEqual({
      ...configuring,
      intent: "review",
      scope: { kind: "concept", conceptId: "c1" },
      conceptId: "c4",
      courseId: null,
      config: cfg,
      queueIndex: 0,
      sourceAttemptId: "old-1",
      phase: "generating",
    });
  });

  it("START with no sourceAttemptId stores null, never undefined", () => {
    const s = reduce({ ...home(), sourceAttemptId: "stale" }, {
      type: "START", start: start(), config: home().config,
    });
    expect(s.sourceAttemptId).toBeNull();
  });

  it("GENERATED on zero questions shows the generation-failed copy", () => {
    const generating = reduce(home(), { type: "START", start: start(), config: home().config });
    const s = reduce(generating, { type: "GENERATED", result: generated([]) });
    expect(s).toEqual({
      ...generating,
      phase: "error",
      error: {
        code: "QUIZ_GENERATION_FAILED",
        message: QUIZ_ERROR_COPY.QUIZ_GENERATION_FAILED,
        retryable: true,
      },
    });
  });

  it("WRITE keeps the first 2000 characters, and only on an open written item", () => {
    const s = active([written(1), mc(2)]);
    const long = reduce(s, { type: "WRITE", text: "x".repeat(2100) });
    expect(long.items[0].answerText).toHaveLength(2000);
    const onMc = reduce(s, { type: "GO_TO", index: 1 });
    expect(reduce(onMc, { type: "WRITE", text: "no" })).toBe(onMc);
    const locked = { ...s, items: [{ ...s.items[0], verdict: { isCorrect: true, correctIndex: -1, explanation: "" } }, s.items[1]] };
    expect(reduce(locked, { type: "WRITE", text: "no" })).toBe(locked);
    const noItem = { ...s, cursor: 5 };
    expect(reduce(noItem, { type: "WRITE", text: "no" })).toBe(noItem);
  });

  it("SELECT is refused when the cursor points at no item", () => {
    const s = { ...active(), cursor: 9 };
    expect(reduce(s, { type: "SELECT", index: 0 })).toBe(s);
  });

  it("ANSWER_RECORDED stores answer text and correct answer when the wire sends them", () => {
    const s = reduce(active([written(1), mc(2)], "as-you-go"), { type: "WRITE", text: "mine" });
    const out = reduce(s, {
      type: "ANSWER_RECORDED",
      result: answered(0, { answer_text: "server", correct_answer: "theirs", is_correct: false, correct_index: -1 }),
    });
    expect(out.items[0]).toEqual({
      ...s.items[0],
      answerText: "server",
      verdict: { isCorrect: false, correctIndex: -1, correctAnswer: "theirs", explanation: "because 0" },
    });
    expect(out.phase).toBe("answered");
    expect(out.cursor).toBe(0);
  });

  it("ANSWER_RECORDED without answer_text leaves the draft text alone", () => {
    const s = reduce(active([written(1), mc(2)], "as-you-go"), { type: "WRITE", text: "mine" });
    const out = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(out.items[0].answerText).toBe("mine");
    expect(Object.keys(out.items[0].verdict ?? {})).toContain("correctAnswer");
  });

  it("ANSWER_RECORDED for an index past the items is refused", () => {
    const s = active();
    expect(reduce(s, { type: "ANSWER_RECORDED", result: answered(9) })).toBe(s);
  });

  it("ANSWER_RECORDED ahead of the cursor scores that item and moves on from it", () => {
    const s = active([mc(1), mc(2), mc(3)], "at-end");
    const out = reduce(s, { type: "ANSWER_RECORDED", result: answered(1) });
    expect(out.items[1].verdict?.isCorrect).toBe(true);
    expect(out.cursor).toBe(2);
    expect(out.phase).toBe("active");
  });

  it("GO_TO keeps a written draft, and the same index is refused", () => {
    const s = reduce(active([written(1), mc(2)]), { type: "WRITE", text: "draft" });
    const moved = reduce(s, { type: "GO_TO", index: 1 });
    expect(moved.items[0].answerText).toBe("draft");
    expect(moved.items[0]).toBe(s.items[0]);
    expect(reduce(s, { type: "GO_TO", index: 0 })).toBe(s);
  });

  it("GO_TO from answered keeps an unverdicted pick on the item it leaves", () => {
    const base = reduce(active(), { type: "SELECT", index: 1 });
    const s = { ...base, phase: "answered" as const };
    const moved = reduce(s, { type: "GO_TO", index: 2 });
    expect(moved.items).toBe(s.items);
    expect(moved.cursor).toBe(2);
    expect(moved.phase).toBe("active");
  });

  it("GO_TO lands on answered for an item with a pick but no verdict", () => {
    const s = active();
    const picked = { ...s, items: s.items.map((i, n) => (n === 2 ? { ...i, selectedIndex: 0 } : i)) };
    expect(reduce(picked, { type: "GO_TO", index: 2 }).phase).toBe("answered");
  });

  it("FINISH is refused with no items, and accepted once every item has a pick", () => {
    const empty = { ...active(), items: [] };
    expect(reduce(empty, { type: "FINISH" })).toBe(empty);
    const s = active();
    const picked = { ...s, items: s.items.map(i => ({ ...i, selectedIndex: 0 })) };
    expect(reduce(picked, { type: "FINISH" })).toEqual({ ...picked, phase: "submitting" });
  });

  it("SUBMITTED clears an error and stores result and XP", () => {
    const s = { ...active(), phase: "submitting" as const, error: NETWORK };
    expect(reduce(s, { type: "SUBMITTED", result: SUBMITTED, xp: XP })).toEqual({
      ...s, phase: "results", result: SUBMITTED, xp: XP, error: null,
    });
  });

  it("PRACTISE_MISSED keeps the rest of the config and the courseId", () => {
    const s = { ...active(), phase: "results" as const, conceptId: "c5", courseId: "course-2" };
    const out = reduce(s, { type: "PRACTISE_MISSED", missedCount: 3, numQuestions: 4 });
    expect(out).toEqual({
      ...s,
      intent: "review",
      scope: { kind: "missed", conceptId: "c5", missedCount: 3 },
      config: { ...s.config, count: 4 },
      sourceAttemptId: "attempt-1",
      phase: "generating",
      attemptId: null,
      items: [],
      cursor: 0,
      error: null,
      result: null,
      xp: null,
      deliveredShort: false,
      reserved: null,
    });
  });

  it("NEXT_IN_QUEUE keeps the course for a course queue and drops it for a due queue", () => {
    const base = { ...active(), phase: "results" as const, courseId: "course-1" };
    const course = reduce(
      { ...base, scope: { kind: "course", courseId: "course-1", queue: ["c1", "c2"] } },
      { type: "NEXT_IN_QUEUE" },
    );
    expect(course.courseId).toBe("course-1");
    expect(course.conceptId).toBe("c2");
    expect(course.sourceAttemptId).toBeNull();
    const due = reduce({ ...base, scope: { kind: "due", queue: ["c1", "c2"] } }, { type: "NEXT_IN_QUEUE" });
    expect(due.courseId).toBeNull();
    expect(due.queueIndex).toBe(1);
  });

  it("EXIT keeps source and config and clears everything else", () => {
    const s = { ...active(), phase: "results" as const, result: SUBMITTED, xp: XP, queueIndex: 2, deliveredShort: true };
    expect(reduce(s, { type: "EXIT" })).toEqual({
      ...s,
      phase: "home",
      scope: { kind: "concept", conceptId: "" },
      conceptId: "",
      courseId: null,
      attemptId: null,
      items: [],
      cursor: 0,
      queueIndex: 0,
      error: null,
      result: null,
      xp: null,
      deliveredShort: false,
      sourceAttemptId: null,
      reserved: null,
    });
  });

  it("CANCEL from generating drops practice framing and errors; from submitting lands active on an open item", () => {
    const generating = {
      ...reduce(home(), { type: "START", start: start({ sourceAttemptId: "x" }), config: home().config }),
      error: NETWORK,
      reserved: { reservedCount: 1, regeneratedCount: 0 },
    };
    expect(reduce(generating, { type: "CANCEL" })).toEqual({
      ...generating, phase: "home", error: null, sourceAttemptId: null, reserved: null,
    });
    const submitting = { ...active(), phase: "submitting" as const, error: NETWORK };
    expect(reduce(submitting, { type: "CANCEL" })).toEqual({ ...submitting, phase: "active", error: null });
  });

  it("FLAG works in any phase with a current item", () => {
    const s = { ...active(), phase: "results" as const };
    expect(reduce(s, { type: "FLAG" }).items[0].flagged).toBe(true);
  });

  it("DISMISS_ERROR after an answer failure returns to active and clears the error", () => {
    const failed = reduce(active(), { type: "ANSWER_FAILED", error: NETWORK });
    expect(reduce(failed, { type: "DISMISS_ERROR" })).toEqual({ ...failed, phase: "active", error: null });
  });

  it("FAILED is accepted from results and paused", () => {
    for (const phase of ["results", "paused", "configuring"] as const) {
      const s = { ...active(), phase };
      expect(reduce(s, { type: "FAILED", error: NETWORK })).toEqual({ ...s, phase: "error", error: NETWORK });
    }
  });

  it("SET_CONFIG is accepted from configuring and results", () => {
    const cfg = { count: 3, difficulty: "easy", feedback: "at-end" as const };
    for (const phase of ["configuring", "results"] as const) {
      const s = { ...active(), phase };
      expect(reduce(s, { type: "SET_CONFIG", config: cfg })).toEqual({ ...s, config: cfg });
    }
  });
});

describe("RESUME (resumeFrom)", () => {
  function resume(d: AttemptDetail, stored: QuizSession | null, from: QuizSession = home()) {
    return reduce(from, { type: "RESUME", detail: d, stored });
  }

  it("with nothing stored: concept scope off the wire, the wire's difficulty, session framing", () => {
    const from = { ...home(), courseId: "course-7", intent: "review" as const, queueIndex: 3, deliveredShort: true };
    const s = resume(detail({ concept_node_id: "c2", responses: [response(0, 1)] }), null, from);
    expect(s).toEqual({
      ...from,
      intent: "review",
      scope: { kind: "concept", conceptId: "c2" },
      source: SOURCE,
      config: { ...from.config, difficulty: "hard" },
      conceptId: "c2",
      courseId: "course-7",
      queueIndex: 0,
      attemptId: "attempt-1",
      items: [
        { index: 0, question: mc(1), selectedIndex: 1, answerText: undefined, verdict: null, flagged: false },
        { index: 1, question: mc(2), selectedIndex: null, answerText: undefined, verdict: null, flagged: false },
        { index: 2, question: mc(3), selectedIndex: null, answerText: undefined, verdict: null, flagged: false },
      ],
      cursor: 1,
      phase: "active",
      error: null,
      result: null,
      xp: null,
      deliveredShort: false,
      sourceAttemptId: null,
      reserved: null,
    });
  });

  it("falls back to the session's difficulty and concept when the wire has none", () => {
    const from = { ...home(), conceptId: "c-home" };
    const s = resume(detail({ difficulty: "", concept_node_id: "" }), null, from);
    expect(s.config).toEqual(from.config);
    expect(s.conceptId).toBe("c-home");
    expect(s.scope).toEqual({ kind: "concept", conceptId: "" });
  });

  it("is accepted from paused, and clears error/result/xp", () => {
    const paused = { ...active(), phase: "paused" as const, error: NETWORK, result: SUBMITTED, xp: XP };
    const s = resume(detail(), null, paused);
    expect(s.phase).toBe("active");
    expect(s.error).toBeNull();
    expect(s.result).toBeNull();
    expect(s.xp).toBeNull();
  });

  it("with a matching stored session: carries its framing, flags, drafts and practice data", () => {
    const base = active([mc(1), written(2), mc(3)], "as-you-go");
    const stored: QuizSession = {
      ...base,
      intent: "review",
      scope: { kind: "due", queue: ["c1", "c2"] },
      source: { kind: "nav" },
      config: { count: 3, difficulty: "easy", feedback: "as-you-go" },
      conceptId: "c-stored",
      courseId: "course-s",
      queueIndex: 1,
      deliveredShort: true,
      sourceAttemptId: "prev",
      reserved: { reservedCount: 2, regeneratedCount: 1 },
      items: [
        { ...base.items[0], selectedIndex: 1, verdict: { isCorrect: false, correctIndex: 0, explanation: "e" }, flagged: true },
        { ...base.items[1], answerText: "draft" },
        { ...base.items[2], selectedIndex: 0, verdict: { isCorrect: true, correctIndex: 0, explanation: "f" } },
      ],
    };
    const s = resume(
      detail({ concept_node_id: "", questions: [mc(1), written(2), mc(3)], responses: [response(0, 1)] }),
      stored,
    );
    expect(s.intent).toBe("review");
    expect(s.scope).toEqual({ kind: "due", queue: ["c1", "c2"] });
    expect(s.source).toEqual({ kind: "nav" });
    expect(s.config).toEqual(stored.config);
    expect(s.conceptId).toBe("c-stored");
    expect(s.courseId).toBe("course-s");
    expect(s.queueIndex).toBe(1);
    expect(s.deliveredShort).toBe(true);
    expect(s.sourceAttemptId).toBe("prev");
    expect(s.reserved).toEqual({ reservedCount: 2, regeneratedCount: 1 });
    expect(s.items).toEqual([
      { index: 0, question: mc(1), selectedIndex: 1, answerText: undefined, verdict: stored.items[0].verdict, flagged: true },
      { index: 1, question: written(2), selectedIndex: null, answerText: "draft", verdict: null, flagged: false },
      // A stored verdict with no server response is dropped; the stored pick stays.
      { index: 2, question: mc(3), selectedIndex: 0, answerText: undefined, verdict: null, flagged: false },
    ]);
    // Item 2 holds a pick, so it counts as answered: the cursor stops on item 1.
    expect(s.cursor).toBe(1);
    expect(s.phase).toBe("active");
  });

  it("prefers the wire's concept over the stored one", () => {
    const stored = { ...active(), conceptId: "c-stored" };
    expect(resume(detail({ concept_node_id: "c-wire" }), stored).conceptId).toBe("c-wire");
  });

  it("builds a written verdict from the wire only when nothing stored has one", () => {
    const d = detail({
      questions: [written(1), mc(2)],
      responses: [response(0, null, { answer_text: "w", is_correct: false }), response(1, 0, { is_correct: false })],
    });
    const s = resume(d, null);
    expect(s.items[0]).toEqual({
      index: 0, question: written(1), selectedIndex: null, answerText: "w",
      verdict: { isCorrect: false, correctIndex: -1, explanation: "" }, flagged: false,
    });
    expect(s.items[1].verdict).toBeNull();
    // Every item answered (a pick on the MC one), but the last has no verdict.
    expect(s.cursor).toBe(1);
    expect(s.phase).toBe("active");
  });

  it("a null wire answer_text falls back to the stored draft", () => {
    const base = active([written(1)]);
    const stored = { ...base, items: [{ ...base.items[0], answerText: "kept" }] };
    const s = resume(detail({ questions: [written(1)], responses: [response(0, null, { answer_text: null })] }), stored);
    expect(s.items[0].answerText).toBe("kept");
    expect(s.items[0].verdict).toEqual({ isCorrect: true, correctIndex: -1, explanation: "" });
    expect(s.phase).toBe("answered");
    expect(s.cursor).toBe(0);
  });

  it("a response with no selected_index field reads as no response at all", () => {
    const base = active([written(1)]);
    const d = detail({
      questions: [written(1)],
      responses: [{ question_index: 0, is_correct: true, answered_at: "x" } as AttemptDetail["responses"][number]],
    });
    const s = resume(d, base);
    expect(s.items[0].verdict).toBeNull();
    expect(s.phase).toBe("active");
  });

  it("an attempt with no questions or responses parks on an empty active quiz", () => {
    const d = { ...detail(), questions: undefined, responses: undefined } as unknown as AttemptDetail;
    const s = resume(d, null);
    expect(s.items).toEqual([]);
    expect(s.cursor).toBe(0);
    expect(s.phase).toBe("active");
  });

  it("matches stored items by question id, not position", () => {
    const base = active([mc(1), mc(2)]);
    const stored: QuizSession = {
      ...base,
      items: [
        { ...base.items[1], flagged: true },
        { ...base.items[0] },
      ],
    };
    const s = resume(detail({ questions: [mc(1), mc(2)] }), stored);
    const flags: QuizItem["flagged"][] = s.items.map(i => i.flagged);
    expect(flags).toEqual([false, true]);
  });
});
