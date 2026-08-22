import { describe, expect, it } from "vitest";
import {
  canExit,
  canSubmitAnswer,
  defaultConfigFor,
  errorReturnPhase,
  firstUnansweredIndex,
  initialSession,
  reduce,
  type QuizEvent,
  type StartRequest,
} from "./machine";
import type { EntryRequest } from "./source";
import type {
  AnswerResult,
  AttemptDetail,
  GenerateResult,
  QuizConfig,
  QuizPrefs,
  QuizSession,
  QuizSource,
  SubmitResult,
  WireQuestion,
} from "./types";

const CONFIG: QuizConfig = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};

const PREFS: QuizPrefs = { count: null, difficulty: null, feedback: "at-end" };

const TREE_SOURCE: QuizSource = {
  kind: "tree",
  returnTo: "/tree?node=c1",
  conceptId: "c1",
};

function entry(overrides: Partial<EntryRequest> = {}): EntryRequest {
  return { source: TREE_SOURCE, ...overrides };
}

function question(id: number): WireQuestion {
  return {
    id,
    question: `Q${id}?`,
    options: [
      { label: "A", text: "a" },
      { label: "B", text: "b" },
      { label: "C", text: "c" },
      { label: "D", text: "d" },
    ],
    difficulty: "medium",
  };
}

function generated(count: number, requested = count): GenerateResult {
  return {
    quiz_id: "attempt-1",
    questions: Array.from({ length: count }, (_, i) => question(i + 1)),
    requested_difficulty: "medium",
    resolved_difficulty: "medium",
    requested_count: requested,
    delivered_count: count,
  };
}

function answered(index: number, isCorrect = true, recorded = true): AnswerResult {
  return {
    question_index: index,
    question_id: index + 1,
    is_correct: isCorrect,
    correct_index: 1,
    explanation: `because ${index}`,
    next_question: null,
    recorded,
  };
}

const SUBMITTED: SubmitResult = {
  score: 2,
  total: 3,
  mastery_before: 0.25,
  mastery_after: 0.31,
  results: [],
};

function startOf(conceptId = "c1"): StartRequest {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId },
    conceptId,
    courseId: "course-1",
  };
}

/** home → generating → active, with `n` questions delivered. */
function activeSession(
  n = 3,
  feedback: "as-you-go" | "at-end" = "at-end",
  entryOverrides: Partial<EntryRequest> = {},
): QuizSession {
  const base = initialSession(entry(entryOverrides), CONFIG, { ...PREFS, feedback });
  const generating = reduce(base, {
    type: "START",
    start: startOf(),
    config: base.config,
  });
  return reduce(generating, { type: "GENERATED", result: generated(n) });
}

/**
 * Answers every question. In at-end mode the last recorded answer lands on
 * `submitting`; in as-you-go mode it stops on `answered` (the student still has
 * to press "See results"), which is what the FINISH cases below need.
 */
function answerAll(session: QuizSession): QuizSession {
  let s = session;
  const last = session.items.length - 1;
  for (let i = 0; i <= last; i += 1) {
    s = reduce(s, { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(i) });
    if (s.phase === "answered" && i < last) s = reduce(s, { type: "NEXT" });
  }
  return s;
}

describe("defaultConfigFor", () => {
  it("prefers 5 questions and medium difficulty when the config offers them", () => {
    expect(defaultConfigFor(CONFIG, PREFS)).toEqual({
      count: 5,
      difficulty: "medium",
      feedback: "at-end",
    });
  });

  it("falls back to the middle option and the first difficulty otherwise", () => {
    const odd: QuizConfig = {
      num_questions: { min: 2, max: 8, options: [2, 4, 8] },
      difficulties: ["gentle", "brutal"],
      question_types: ["multiple_choice"],
    };
    expect(defaultConfigFor(odd, PREFS)).toEqual({
      count: 4,
      difficulty: "gentle",
      feedback: "at-end",
    });
  });

  it("lets stored prefs win over the config-derived defaults", () => {
    expect(defaultConfigFor(CONFIG, { count: 10, difficulty: "hard", feedback: "as-you-go" }))
      .toEqual({ count: 10, difficulty: "hard", feedback: "as-you-go" });
  });

  it("degrades to a single scalar default before /config resolves", () => {
    const out = defaultConfigFor(null, PREFS);
    expect(out.count).toBeGreaterThan(0);
    expect(out.difficulty).toBeTruthy();
  });
});

describe("initialSession", () => {
  it("opens on home with the entry's source and concept", () => {
    const s = initialSession(entry({ concept: "c1" }), CONFIG, PREFS);
    expect(s.phase).toBe("home");
    expect(s.source).toEqual(TREE_SOURCE);
    expect(s.conceptId).toBe("c1");
    expect(s.scope).toEqual({ kind: "concept", conceptId: "c1" });
    expect(s.items).toEqual([]);
    expect(s.attemptId).toBeNull();
    expect(s.error).toBeNull();
  });

  it("opens a due entry on an empty due queue (the home hook fills it)", () => {
    const s = initialSession(entry({ scope: "due" }), CONFIG, PREFS);
    expect(s.scope).toEqual({ kind: "due", queue: [] });
  });

  it("opens a course entry on an empty course queue", () => {
    const s = initialSession(entry({ course: "course-9" }), CONFIG, PREFS);
    expect(s.scope).toEqual({ kind: "course", courseId: "course-9", queue: [] });
    expect(s.courseId).toBe("course-9");
  });
});

describe("home ⇄ configuring", () => {
  it("CONFIGURE opens and closes the config surface", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    const configuring = reduce(home, { type: "CONFIGURE", open: true });
    expect(configuring.phase).toBe("configuring");
    expect(reduce(configuring, { type: "CONFIGURE", open: false }).phase).toBe("home");
  });

  it("ignores CONFIGURE outside home/configuring", () => {
    const active = activeSession();
    expect(reduce(active, { type: "CONFIGURE", open: true })).toBe(active);
  });
});

describe("START → GENERATED", () => {
  it("clears the previous attempt when generating", () => {
    const results = reduce(answerAll(activeSession(1)), {
      type: "SUBMITTED",
      result: SUBMITTED,
      xp: null,
    });
    expect(results.phase).toBe("results");

    const generating = reduce(results, { type: "START", start: startOf("c2"), config: results.config });
    expect(generating.phase).toBe("generating");
    expect(generating.attemptId).toBeNull();
    expect(generating.items).toEqual([]);
    expect(generating.result).toBeNull();
    expect(generating.cursor).toBe(0);
  });

  it("lands on active at cursor 0 with one item per question", () => {
    const s = activeSession(3);
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(0);
    expect(s.attemptId).toBe("attempt-1");
    expect(s.items.map(i => i.index)).toEqual([0, 1, 2]);
    expect(s.items.every(i => i.selectedIndex === null && i.verdict === null)).toBe(true);
  });

  it("flags a short delivery", () => {
    const base = initialSession(entry(), CONFIG, PREFS);
    const generating = reduce(base, { type: "START", start: startOf(), config: base.config });
    expect(reduce(generating, { type: "GENERATED", result: generated(3) }).deliveredShort).toBe(false);
    expect(reduce(generating, { type: "GENERATED", result: generated(2, 5) }).deliveredShort).toBe(true);
  });

  it("treats a zero-question delivery as a generation failure", () => {
    const base = initialSession(entry(), CONFIG, PREFS);
    const generating = reduce(base, { type: "START", start: startOf(), config: base.config });
    const s = reduce(generating, { type: "GENERATED", result: generated(0, 5) });
    expect(s.phase).toBe("error");
    expect(s.error?.code).toBe("QUIZ_GENERATION_FAILED");
  });

  it("GENERATE_FAILED lands on error whose dismissal returns home", () => {
    const base = initialSession(entry(), CONFIG, PREFS);
    const generating = reduce(base, { type: "START", start: startOf(), config: base.config });
    const failed = reduce(generating, {
      type: "GENERATE_FAILED",
      error: { code: "QUIZ_GENERATION_TIMEOUT", message: "slow", retryable: true },
    });
    expect(failed.phase).toBe("error");
    expect(errorReturnPhase(failed)).toBe("home");
    expect(reduce(failed, { type: "DISMISS_ERROR" }).phase).toBe("home");
    expect(reduce(failed, { type: "DISMISS_ERROR" }).error).toBeNull();
  });

  it("ignores GENERATED outside generating", () => {
    const active = activeSession();
    expect(reduce(active, { type: "GENERATED", result: generated(3) })).toBe(active);
  });
});

describe("answering — as-you-go", () => {
  it("SELECT records the choice without advancing", () => {
    const s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 2 });
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(0);
    expect(s.items[0].selectedIndex).toBe(2);
  });

  it("ANSWER_RECORDED reveals the verdict and holds on answered", () => {
    let s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0, false) });
    expect(s.phase).toBe("answered");
    expect(s.cursor).toBe(0);
    expect(s.items[0].verdict).toEqual({
      isCorrect: false,
      correctIndex: 1,
      explanation: "because 0",
    });
  });

  it("NEXT advances from answered, and reaches submitting on the last item", () => {
    let s = activeSession(2, "as-you-go");
    s = reduce(s, { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    s = reduce(s, { type: "NEXT" });
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(1);

    s = reduce(s, { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(1) });
    expect(s.phase).toBe("answered");
    expect(reduce(s, { type: "NEXT" }).phase).toBe("submitting");
  });
});

describe("answering — at-end", () => {
  it("ANSWER_RECORDED advances straight past the verdict", () => {
    let s = reduce(activeSession(3, "at-end"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(1);
    // The verdict is still stored — only its display is deferred.
    expect(s.items[0].verdict).not.toBeNull();
  });

  it("goes to submitting when the last answer is recorded", () => {
    let s = reduce(activeSession(1, "at-end"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(s.phase).toBe("submitting");
  });
});

describe("submitting and results", () => {
  it("SUBMITTED carries the result and the XP delta into results", () => {
    const s = reduce(answerAll(activeSession(2)), {
      type: "SUBMITTED",
      result: SUBMITTED,
      xp: { before: 100, after: 130, streak: 4 },
    });
    expect(s.phase).toBe("results");
    expect(s.result).toEqual(SUBMITTED);
    expect(s.xp).toEqual({ before: 100, after: 130, streak: 4 });
  });

  it("SUBMIT_FAILED lands on an error that returns to submitting", () => {
    const s = reduce(answerAll(activeSession(2)), {
      type: "SUBMIT_FAILED",
      error: { code: "QUIZ_ATTEMPT_ALREADY_COMPLETED", message: "scored", retryable: false },
    });
    expect(s.phase).toBe("error");
    expect(s.error?.code).toBe("QUIZ_ATTEMPT_ALREADY_COMPLETED");
    expect(errorReturnPhase(s)).toBe("submitting");
    expect(reduce(s, { type: "DISMISS_ERROR" }).phase).toBe("submitting");
  });

  it("ANSWER_FAILED returns to active, not to home", () => {
    const s = reduce(reduce(activeSession(3), { type: "SELECT", index: 1 }), {
      type: "ANSWER_FAILED",
      error: { code: "NETWORK", message: "offline", retryable: true },
    });
    expect(s.phase).toBe("error");
    expect(errorReturnPhase(s)).toBe("active");
    expect(reduce(s, { type: "DISMISS_ERROR" }).phase).toBe("active");
  });
});

describe("leaving and resuming", () => {
  it("REQUEST_LEAVE / CANCEL_LEAVE round-trips back to active", () => {
    const active = activeSession(3);
    const confirming = reduce(active, { type: "REQUEST_LEAVE" });
    expect(confirming.phase).toBe("confirm-leave");
    expect(reduce(confirming, { type: "CANCEL_LEAVE" }).phase).toBe("active");
  });

  it("CANCEL_LEAVE returns to answered when the current verdict is showing", () => {
    let s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    const confirming = reduce(s, { type: "REQUEST_LEAVE" });
    expect(confirming.phase).toBe("confirm-leave");
    expect(reduce(confirming, { type: "CANCEL_LEAVE" }).phase).toBe("answered");
  });

  it("CONFIRM_LEAVE parks the session on paused", () => {
    const paused = reduce(reduce(activeSession(3), { type: "REQUEST_LEAVE" }), {
      type: "CONFIRM_LEAVE",
    });
    expect(paused.phase).toBe("paused");
    expect(paused.attemptId).toBe("attempt-1");
  });
});

describe("RESUME", () => {
  function detail(selected: number[]): AttemptDetail {
    return {
      quiz_id: "attempt-1",
      status: "in_progress",
      resumable: true,
      difficulty: "medium",
      concept_node_id: "c1",
      questions: [question(1), question(2), question(3)],
      responses: selected.map((selected_index, question_index) => ({
        question_index,
        selected_index,
        is_correct: true,
        answered_at: "2026-08-22T10:00:00Z",
      })),
      score: null,
      total: null,
      created_at: "2026-08-22T09:00:00Z",
    };
  }

  it("lands on the first unanswered item", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    const s = reduce(home, { type: "RESUME", detail: detail([1, 2]), stored: null });
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(2);
    expect(s.attemptId).toBe("attempt-1");
    expect(s.items[0].selectedIndex).toBe(1);
    expect(s.items[2].selectedIndex).toBeNull();
  });

  it("restores verdicts and scope from the stored session", () => {
    let mid = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    mid = reduce(mid, { type: "ANSWER_RECORDED", result: answered(0) });
    const stored = reduce(reduce(mid, { type: "REQUEST_LEAVE" }), { type: "CONFIRM_LEAVE" });

    const home = initialSession(entry(), CONFIG, PREFS);
    const s = reduce(home, { type: "RESUME", detail: detail([1]), stored });
    expect(s.items[0].verdict).toEqual({
      isCorrect: true,
      correctIndex: 1,
      explanation: "because 0",
    });
    expect(s.config.feedback).toBe("as-you-go");
    expect(s.cursor).toBe(1);
  });

  it("shows the last verdict again when every question is already answered", () => {
    let mid = activeSession(3, "as-you-go");
    for (let i = 0; i < 3; i += 1) {
      mid = reduce(mid, { type: "SELECT", index: 1 });
      mid = reduce(mid, { type: "ANSWER_RECORDED", result: answered(i) });
      if (i < 2) mid = reduce(mid, { type: "NEXT" });
    }
    const home = initialSession(entry(), CONFIG, PREFS);
    const s = reduce(home, { type: "RESUME", detail: detail([1, 1, 1]), stored: mid });
    expect(s.cursor).toBe(2);
    expect(s.phase).toBe("answered");
  });

  it("ignores a stored session that belongs to another attempt", () => {
    const other = { ...activeSession(3), attemptId: "attempt-other" };
    const home = initialSession(entry(), CONFIG, PREFS);
    const s = reduce(home, { type: "RESUME", detail: detail([1]), stored: other });
    expect(s.items[0].verdict).toBeNull();
    expect(s.source).toEqual(TREE_SOURCE);
  });
});

describe("results exits", () => {
  function resultsSession(scope: QuizSession["scope"]): QuizSession {
    const base = { ...answerAll(activeSession(3)), scope };
    return reduce(base, { type: "SUBMITTED", result: SUBMITTED, xp: null });
  }

  it("PRACTISE_MISSED generates a review attempt on the same concept", () => {
    const s = reduce(resultsSession({ kind: "concept", conceptId: "c1" }), {
      type: "PRACTISE_MISSED",
      missedCount: 2,
      numQuestions: 2,
    });
    expect(s.phase).toBe("generating");
    expect(s.intent).toBe("review");
    expect(s.scope).toEqual({ kind: "missed", conceptId: "c1", missedCount: 2 });
    expect(s.config.count).toBe(2);
    expect(s.config.difficulty).toBe("medium");
  });

  it("NEXT_IN_QUEUE advances to the next concept in the queue", () => {
    const s = reduce(resultsSession({ kind: "due", queue: ["c1", "c2", "c3"] }), {
      type: "NEXT_IN_QUEUE",
    });
    expect(s.phase).toBe("generating");
    expect(s.queueIndex).toBe(1);
    expect(s.conceptId).toBe("c2");
  });

  it("EXIT from results resets to a clean home session", () => {
    const s = reduce(resultsSession({ kind: "concept", conceptId: "c1" }), { type: "EXIT" });
    expect(s.phase).toBe("home");
    expect(s.result).toBeNull();
    expect(s.items).toEqual([]);
    expect(s.attemptId).toBeNull();
  });
});

describe("FLAG", () => {
  it("toggles the current item and stays in the same phase", () => {
    const active = activeSession(3);
    const flagged = reduce(active, { type: "FLAG" });
    expect(flagged.phase).toBe("active");
    expect(flagged.items[0].flagged).toBe(true);
    expect(reduce(flagged, { type: "FLAG" }).items[0].flagged).toBe(false);
  });

  it("is a no-op when there is no current item", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    expect(reduce(home, { type: "FLAG" })).toBe(home);
  });
});

describe("FINISH", () => {
  it("submits once every question is answered", () => {
    const s = answerAll(activeSession(2, "as-you-go"));
    // answerAll leaves the last item on `answered` in as-you-go mode.
    expect(reduce(s, { type: "FINISH" }).phase).toBe("submitting");
  });

  it("is ignored while questions remain unanswered", () => {
    const s = activeSession(3);
    expect(reduce(s, { type: "FINISH" })).toBe(s);
  });
});

describe("FAILED and SET_CONFIG (the two events beyond §4's list)", () => {
  const ABANDONED = {
    code: "QUIZ_ATTEMPT_ABANDONED" as const,
    message: "expired",
    retryable: false,
  };

  it("FAILED surfaces a resume failure on quiz home", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    const failed = reduce(home, { type: "FAILED", error: ABANDONED });
    expect(failed.phase).toBe("error");
    expect(failed.error).toEqual(ABANDONED);
    expect(reduce(failed, { type: "DISMISS_ERROR" }).phase).toBe("home");
  });

  it("FAILED never clobbers a live attempt", () => {
    const active = activeSession(3);
    expect(reduce(active, { type: "FAILED", error: ABANDONED })).toBe(active);
    const confirming = reduce(active, { type: "REQUEST_LEAVE" });
    expect(reduce(confirming, { type: "FAILED", error: ABANDONED })).toBe(confirming);
  });

  it("FAILED does not overwrite an error already on screen", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    const first = reduce(home, { type: "FAILED", error: ABANDONED });
    const second = reduce(first, {
      type: "FAILED",
      error: { code: "NETWORK", message: "offline", retryable: true },
    });
    expect(second).toBe(first);
  });

  it("SET_CONFIG holds an Adjust-dialog choice made without starting", () => {
    const home = initialSession(entry(), CONFIG, PREFS);
    const tuned = reduce(home, {
      type: "SET_CONFIG",
      config: { count: 10, difficulty: "hard", feedback: "as-you-go" },
    });
    expect(tuned.config).toEqual({ count: 10, difficulty: "hard", feedback: "as-you-go" });
    expect(tuned.phase).toBe("home");
  });

  it("SET_CONFIG is ignored mid-quiz — the attempt is already generated", () => {
    const active = activeSession(3);
    expect(
      reduce(active, {
        type: "SET_CONFIG",
        config: { count: 10, difficulty: "hard", feedback: "as-you-go" },
      }),
    ).toBe(active);
  });
});

// ── The six invariants (§4) ────────────────────────────────────────────────

describe("invariant 1 — nothing walks out of a live quiz by accident", () => {
  const LEAVERS: QuizEvent[] = [
    { type: "EXIT" },
    { type: "CONFIGURE", open: true },
    { type: "GENERATED", result: generated(3) },
    { type: "PRACTISE_MISSED", missedCount: 1, numQuestions: 1 },
    { type: "NEXT_IN_QUEUE" },
    { type: "RESUME", detail: { ...({} as AttemptDetail) }, stored: null },
    { type: "SUBMITTED", result: SUBMITTED, xp: null },
    { type: "DISMISS_ERROR" },
    { type: "CANCEL_LEAVE" },
    { type: "FAILED", error: { code: "NETWORK", message: "offline", retryable: true } },
    { type: "SET_CONFIG", config: { count: 10, difficulty: "hard", feedback: "as-you-go" } },
  ];

  it("no event takes active to home or to an exit", () => {
    const active = activeSession(3);
    for (const event of LEAVERS) {
      const next = reduce(active, event);
      expect(next.phase, `${event.type} from active`).toBe("active");
    }
  });

  it("no event takes answered to home or to an exit", () => {
    let s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(s.phase).toBe("answered");
    for (const event of LEAVERS) {
      if (event.type === "CANCEL_LEAVE") continue;
      expect(reduce(s, event).phase, `${event.type} from answered`).toBe("answered");
    }
  });

  it("the only ways out are CONFIRM_LEAVE and the submit path", () => {
    const active = activeSession(1);
    expect(
      reduce(reduce(active, { type: "REQUEST_LEAVE" }), { type: "CONFIRM_LEAVE" }).phase,
    ).toBe("paused");

    let s = reduce(active, { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(s.phase).toBe("submitting");
  });

  it("canExit is false for every live phase", () => {
    const active = activeSession(3);
    expect(canExit(active)).toBe(false);
    expect(canExit(reduce(active, { type: "REQUEST_LEAVE" }))).toBe(false);
    expect(canExit({ ...active, phase: "submitting" })).toBe(false);
    expect(canExit({ ...active, phase: "home" })).toBe(true);
    expect(canExit({ ...active, phase: "results" })).toBe(true);
    expect(canExit({ ...active, phase: "paused" })).toBe(true);
  });
});

describe("invariant 2 — source survives the whole session", () => {
  const NOTE_SOURCE: QuizSource = {
    kind: "notes",
    returnTo: "/notetaker?note=n7",
    conceptId: "c1",
    noteId: "n7",
  };

  it("is identical on entry, on paused, on results and on exit", () => {
    const start = initialSession({ source: NOTE_SOURCE, concept: "c1" }, CONFIG, PREFS);
    expect(start.source).toEqual(NOTE_SOURCE);

    const active = reduce(
      reduce(start, { type: "START", start: startOf(), config: start.config }),
      { type: "GENERATED", result: generated(2) },
    );
    expect(active.source).toEqual(NOTE_SOURCE);

    const paused = reduce(reduce(active, { type: "REQUEST_LEAVE" }), { type: "CONFIRM_LEAVE" });
    expect(paused.source).toEqual(NOTE_SOURCE);

    const results = reduce(answerAll(active), { type: "SUBMITTED", result: SUBMITTED, xp: null });
    expect(results.source).toEqual(NOTE_SOURCE);

    expect(reduce(results, { type: "EXIT" }).source).toEqual(NOTE_SOURCE);
  });

  it("survives a queue hop and a practise-missed restart", () => {
    const start = initialSession({ source: NOTE_SOURCE, scope: "due" }, CONFIG, PREFS);
    const active = reduce(
      reduce(start, {
        type: "START",
        start: { intent: "practice", scope: { kind: "due", queue: ["c1", "c2"] }, conceptId: "c1", courseId: null },
        config: start.config,
      }),
      { type: "GENERATED", result: generated(1) },
    );
    const results = reduce(answerAll(active), { type: "SUBMITTED", result: SUBMITTED, xp: null });
    expect(reduce(results, { type: "NEXT_IN_QUEUE" }).source).toEqual(NOTE_SOURCE);
    expect(
      reduce(results, { type: "PRACTISE_MISSED", missedCount: 1, numQuestions: 1 }).source,
    ).toEqual(NOTE_SOURCE);
  });
});

describe("invariant 3 — answered then unmounted resumes where it left off", () => {
  it("restores the cursor to the first unanswered item and keeps the source", () => {
    // Answer question 1, then the tab goes away mid-quiz.
    let s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    const stored = s;
    expect(stored.source).toEqual(TREE_SOURCE);

    // A fresh mount: a brand-new home session, then RESUME off the wire.
    const fresh = initialSession(entry(), CONFIG, PREFS);
    const resumed = reduce(fresh, {
      type: "RESUME",
      stored,
      detail: {
        quiz_id: "attempt-1",
        status: "in_progress",
        resumable: true,
        difficulty: "medium",
        concept_node_id: "c1",
        questions: [question(1), question(2), question(3)],
        responses: [
          { question_index: 0, selected_index: 1, is_correct: true, answered_at: "2026-08-22T10:00:00Z" },
        ],
        score: null,
        total: null,
        created_at: "2026-08-22T09:00:00Z",
      },
    });

    expect(resumed.phase).toBe("active");
    expect(resumed.cursor).toBe(1);
    expect(resumed.source).toEqual(TREE_SOURCE);
    expect(firstUnansweredIndex(resumed.items)).toBe(1);
  });
});

describe("invariant 4 — SELECT is ignored once the verdict is showing", () => {
  it("keeps the recorded choice", () => {
    let s = reduce(activeSession(3, "as-you-go"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0) });
    expect(s.phase).toBe("answered");

    const after = reduce(s, { type: "SELECT", index: 3 });
    expect(after).toBe(s);
    expect(after.items[0].selectedIndex).toBe(1);
  });

  it("SUBMIT_ANSWER without a selection is ignored", () => {
    const s = activeSession(3);
    expect(canSubmitAnswer(s)).toBe(false);
    expect(reduce(s, { type: "SUBMIT_ANSWER" })).toBe(s);

    const selected = reduce(s, { type: "SELECT", index: 0 });
    expect(canSubmitAnswer(selected)).toBe(true);
  });
});

describe("invariant 5 — NEXT_IN_QUEUE past the end is ignored", () => {
  it("stops at the last queue entry", () => {
    const base = { ...answerAll(activeSession(1)), scope: { kind: "due" as const, queue: ["c1", "c2"] } };
    const results = reduce(base, { type: "SUBMITTED", result: SUBMITTED, xp: null });

    const second = reduce(results, { type: "NEXT_IN_QUEUE" });
    expect(second.queueIndex).toBe(1);

    const atEnd = { ...results, queueIndex: 1 };
    expect(reduce(atEnd, { type: "NEXT_IN_QUEUE" })).toBe(atEnd);
  });

  it("is ignored for a scope with no queue at all", () => {
    const results = reduce(answerAll(activeSession(1)), {
      type: "SUBMITTED",
      result: SUBMITTED,
      xp: null,
    });
    expect(reduce(results, { type: "NEXT_IN_QUEUE" })).toBe(results);
  });
});

describe("invariant 6 — an unrecorded replay still advances", () => {
  it("treats recorded:false exactly like recorded:true", () => {
    let s = reduce(activeSession(3, "at-end"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0, true, false) });
    expect(s.phase).toBe("active");
    expect(s.cursor).toBe(1);
    expect(s.items[0].verdict).not.toBeNull();
  });

  it("still reaches submitting on the last item", () => {
    let s = reduce(activeSession(1, "at-end"), { type: "SELECT", index: 1 });
    s = reduce(s, { type: "ANSWER_RECORDED", result: answered(0, false, false) });
    expect(s.phase).toBe("submitting");
  });
});
