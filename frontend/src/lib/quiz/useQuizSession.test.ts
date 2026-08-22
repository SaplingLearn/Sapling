// @vitest-environment jsdom
/**
 * `useQuizSession` is where the machine meets the network. These drive the
 * whole loop through mocked clients: start → answer → answer → submit, the
 * leave-and-resume round trip, the answered-then-unmounted resume, and the two
 * failures whose copy the student actually sees.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { AnswerResult, AttemptDetail, GenerateResult, SubmitResult } from "./types";

const push = vi.fn();
const replace = vi.fn();
// The route the hook believes it is on. `exit` compares the destination against
// it to decide push vs replace, so tests that care set it.
let pathname = "/quiz";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => pathname,
}));

const quizApi = vi.hoisted(() => ({
  fetchQuizConfig: vi.fn(),
  generateQuiz: vi.fn(),
  answerQuestion: vi.fn(),
  submitQuiz: vi.fn(),
  getAttempt: vi.fn(),
  listAttempts: vi.fn(),
  describeConcept: vi.fn(),
}));
vi.mock("./api", () => quizApi);

const gamification = vi.hoisted(() => ({ fetchGamificationMe: vi.fn() }));
vi.mock("@/lib/api", async importActual => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, fetchGamificationMe: gamification.fetchGamificationMe };
});

import { useQuizSession } from "./useQuizSession";
import { resetQuizConfigCache } from "./useQuizConfig";
import { STORAGE_KEY, loadSession } from "./session";
import type { EntryRequest } from "./source";

const CONFIG = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};

const ENTRY: EntryRequest = {
  concept: "c1",
  source: { kind: "tree", returnTo: "/tree?node=c1", conceptId: "c1" },
};

function question(id: number) {
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

function generated(n: number): GenerateResult {
  return {
    quiz_id: "attempt-1",
    questions: Array.from({ length: n }, (_, i) => question(i + 1)),
    requested_difficulty: "medium",
    resolved_difficulty: "medium",
    requested_count: n,
    delivered_count: n,
  };
}

function answerResult(index: number): AnswerResult {
  return {
    question_index: index,
    question_id: index + 1,
    is_correct: true,
    correct_index: 1,
    explanation: `because ${index}`,
    next_question: null,
    recorded: true,
  };
}

const SUBMIT_RESULT: SubmitResult = {
  score: 2,
  total: 2,
  mastery_before: 0.25,
  mastery_after: 0.31,
  results: [],
};

function me(total_xp: number, streak: number) {
  return {
    level: 3, next_level: 4, stage: "sprout", total_xp, xp_into_level: 10, xp_for_level: 100,
    level_pct: 10, streak, longest_streak: streak, daily_goal_xp: 50, today_xp: 10,
    earned_count: 1, total_count: 10,
  };
}

const START = {
  intent: "practice" as const,
  scope: { kind: "concept" as const, conceptId: "c1" },
  conceptId: "c1",
  courseId: "course-1",
};

beforeEach(() => {
  resetQuizConfigCache();
  window.localStorage.clear();
  pathname = "/quiz";
  push.mockClear();
  replace.mockClear();
  quizApi.fetchQuizConfig.mockResolvedValue(CONFIG);
  quizApi.generateQuiz.mockResolvedValue(generated(2));
  quizApi.answerQuestion.mockImplementation(
    (_id: string, p: { questionIndex: number }) => Promise.resolve(answerResult(p.questionIndex)),
  );
  quizApi.submitQuiz.mockResolvedValue(SUBMIT_RESULT);
  quizApi.getAttempt.mockResolvedValue({} as AttemptDetail);
  gamification.fetchGamificationMe
    .mockResolvedValueOnce(me(100, 3))
    .mockResolvedValue(me(130, 4));
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function mount(entry: EntryRequest = ENTRY) {
  return renderHook(() => useQuizSession("u1", entry));
}

describe("start → answer → answer → submit", () => {
  it("walks the whole loop and lands on results with the XP delta", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());

    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));
    expect(quizApi.generateQuiz).toHaveBeenCalledWith({
      userId: "u1",
      conceptNodeId: "c1",
      numQuestions: 5,
      difficulty: "medium",
    });

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));
    expect(quizApi.answerQuestion).toHaveBeenCalledWith("attempt-1", {
      questionIndex: 0,
      selectedIndex: 1,
      questionId: 1,
    });

    act(() => result.current.actions.select(2));
    await act(async () => {
      result.current.actions.submitAnswer();
    });

    await waitFor(() => expect(result.current.session.phase).toBe("results"));
    expect(quizApi.submitQuiz).toHaveBeenCalledWith("attempt-1", [
      { question_id: 1, selected_label: "B" },
      { question_id: 2, selected_label: "C" },
    ]);
    expect(result.current.session.result).toEqual(SUBMIT_RESULT);
    expect(result.current.session.xp).toEqual({ before: 100, after: 130, streak: 4 });
    // The stored record is cleared once the attempt is scored.
    expect(loadSession()).toBeNull();
  });

  it("omits the XP line when a gamification read failed (R-9 — never invented)", async () => {
    gamification.fetchGamificationMe.mockReset();
    gamification.fetchGamificationMe.mockRejectedValue(new Error("down"));

    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    quizApi.generateQuiz.mockResolvedValue(generated(1));

    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));
    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });

    await waitFor(() => expect(result.current.session.phase).toBe("results"));
    expect(result.current.session.xp).toBeNull();
  });

  it("retries a dropped answer exactly once, and never a rejected one", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    quizApi.answerQuestion
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(answerResult(0));

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(2);

    quizApi.answerQuestion.mockReset();
    quizApi.answerQuestion.mockRejectedValue(
      new ApiError("bad", 400, { code: "QUIZ_QUESTION_INVALID" }),
    );
    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("error"));
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(1);
    expect(result.current.session.error?.message).toBe(
      "That answer didn't line up with the question. Reload and try again.",
    );
  });
});

/**
 * The two defects the Chapter-1 lane found, ridden in as `test.fixme` in
 * `e2e/quiz-journeys.spec.ts`. Both are unit-reproducible; these are the guards
 * that keep them fixed once those journeys are un-fixme'd.
 */
describe("#537 browser-lane regressions", () => {
  const DASHBOARD: EntryRequest = {
    source: { kind: "dashboard", returnTo: "/dashboard" },
  };

  it("quiz home no longer deletes the paused attempt it is about to offer", async () => {
    // Leave a quiz mid-flight, from the DASHBOARD — a tree origin is
    // indistinguishable from the `returnToSource` fallback, which is what
    // masked this in the green leave-and-return journey.
    const first = mount(DASHBOARD);
    await waitFor(() => expect(first.result.current.config).not.toBeNull());
    act(() =>
      first.result.current.actions.setConfig({
        count: 5, difficulty: "medium", feedback: "as-you-go",
      }),
    );
    act(() => first.result.current.actions.start(START));
    await waitFor(() => expect(first.result.current.session.phase).toBe("active"));
    act(() => first.result.current.actions.select(1));
    await act(async () => {
      first.result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(first.result.current.session.phase).toBe("answered"));
    act(() => first.result.current.actions.requestLeave());
    act(() => first.result.current.actions.confirmLeave());
    expect(first.result.current.session.phase).toBe("paused");

    const parked = loadSession();
    expect(parked?.items[0].verdict).not.toBeNull();
    expect(parked?.source.kind).toBe("dashboard");
    first.unmount();

    // Now mount quiz home the way a student reaches it: no deep link. Its
    // config effect fires `SET_CONFIG` as soon as `/api/quiz/config` resolves,
    // and every accepted event is persisted. That used to wipe the record.
    const second = mount({ source: { kind: "nav" } });
    await waitFor(() => expect(second.result.current.config).not.toBeNull());
    await waitFor(() =>
      expect(second.result.current.session.config.count).toBe(5));
    expect(loadSession()).toEqual(parked);

    // …so Resume gets the verdicts and the origin back.
    quizApi.getAttempt.mockResolvedValue({
      quiz_id: "attempt-1", status: "in_progress", resumable: true, difficulty: "medium",
      concept_node_id: "c1", questions: [question(1), question(2)],
      responses: [
        { question_index: 0, selected_index: 1, is_correct: true, answered_at: "2026-08-22T10:00:00Z" },
      ],
      score: null, total: null, created_at: "2026-08-22T09:00:00Z",
    } satisfies AttemptDetail);

    await act(async () => {
      second.result.current.actions.resume("attempt-1");
    });
    await waitFor(() => expect(second.result.current.session.phase).toBe("active"));
    expect(second.result.current.session.items[0].verdict).toEqual({
      isCorrect: true, correctIndex: 1, explanation: "because 0",
    });
    expect(second.result.current.session.source.kind).toBe("dashboard");
    expect(second.result.current.session.cursor).toBe(1);
  });

  it("Done drops the deep link instead of leaving home pinned to it", async () => {
    pathname = "/quiz";
    quizApi.generateQuiz.mockResolvedValue(generated(1));
    const { result } = mount({
      concept: "c1",
      source: { kind: "link", conceptId: "c1" },
    });
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));
    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("results"));

    act(() => result.current.actions.exit("/quiz"));

    // `push` does not take for a query-only change on the same route — the lane
    // measured Done leaving the URL at `/quiz?concept=…`.
    expect(replace).toHaveBeenCalledWith("/quiz");
    expect(push).not.toHaveBeenCalled();

    // And the session stops pointing at the concept that was just finished, so
    // nothing that prefers the session over the proposal stays pinned to it.
    expect(result.current.session.phase).toBe("home");
    expect(result.current.session.conceptId).toBe("");
    expect(result.current.session.scope).toEqual({ kind: "concept", conceptId: "" });
    expect(result.current.session.result).toBeNull();
  });

  it("still pushes for an exit that really changes route", async () => {
    pathname = "/quiz";
    quizApi.generateQuiz.mockResolvedValue(generated(1));
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));
    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("results"));

    // No target: "Back to your tree" resolves through `returnToSource`, which
    // needs the conceptId EXIT clears — so it has to be read before the reset.
    act(() => result.current.actions.exit());
    expect(push).toHaveBeenCalledWith("/tree?node=c1");
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("a double-pressed Submit only answers once", () => {
  it("fires exactly one /answer for the item while the first is in flight", async () => {
    // The phase stays `active` for the whole round trip, so neither
    // canSubmitAnswer nor a `phase !== "active"` disabled check rules the second
    // press out — only the hook's in-flight guard does.
    let release: (value: AnswerResult) => void = () => {};
    quizApi.answerQuestion.mockImplementationOnce(
      () => new Promise<AnswerResult>(resolve => {
        release = resolve;
      }),
    );

    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(1));
    act(() => {
      result.current.actions.submitAnswer();
      result.current.actions.submitAnswer();
      result.current.actions.submitAnswer();
    });
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(1);

    await act(async () => {
      release(answerResult(0));
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(1);

    // The guard is per item, not a one-shot latch: the next question submits.
    act(() => result.current.actions.select(2));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(2);
  });

  it("releases the guard after a failure, so retrying is possible", async () => {
    quizApi.answerQuestion.mockRejectedValueOnce(
      new ApiError("bad", 400, { code: "QUIZ_QUESTION_INVALID" }),
    );

    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("error"));

    await act(async () => {
      result.current.actions.retry();
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));
    expect(quizApi.answerQuestion).toHaveBeenCalledTimes(2);
  });
});

describe('the "sapling:graph-changed" announcement', () => {
  it("fires exactly once per submit, carrying the mastery move", async () => {
    const seen: CustomEvent[] = [];
    const listener = (e: Event) => seen.push(e as CustomEvent);
    window.addEventListener("sapling:graph-changed", listener);

    try {
      quizApi.generateQuiz.mockResolvedValue(generated(1));
      const { result } = mount();
      await waitFor(() => expect(result.current.config).not.toBeNull());
      act(() => result.current.actions.start(START));
      await waitFor(() => expect(result.current.session.phase).toBe("active"));

      act(() => result.current.actions.select(1));
      await act(async () => {
        result.current.actions.submitAnswer();
      });
      await waitFor(() => expect(result.current.session.phase).toBe("results"));

      expect(seen).toHaveLength(1);
      expect(seen[0].detail).toEqual({
        conceptId: "c1",
        masteryBefore: 0.25,
        masteryAfter: 0.31,
      });
    } finally {
      window.removeEventListener("sapling:graph-changed", listener);
    }
  });

  it("stays silent when the submit failed", async () => {
    const seen: Event[] = [];
    const listener = (e: Event) => seen.push(e);
    window.addEventListener("sapling:graph-changed", listener);

    try {
      quizApi.generateQuiz.mockResolvedValue(generated(1));
      quizApi.submitQuiz.mockRejectedValue(
        new ApiError("done", 409, { code: "QUIZ_ATTEMPT_ALREADY_COMPLETED" }),
      );
      const { result } = mount();
      await waitFor(() => expect(result.current.config).not.toBeNull());
      act(() => result.current.actions.start(START));
      await waitFor(() => expect(result.current.session.phase).toBe("active"));

      act(() => result.current.actions.select(1));
      await act(async () => {
        result.current.actions.submitAnswer();
      });
      await waitFor(() => expect(result.current.session.phase).toBe("error"));

      expect(seen).toHaveLength(0);
    } finally {
      window.removeEventListener("sapling:graph-changed", listener);
    }
  });
});

describe("leave and resume", () => {
  it("parks the session, navigates back to the source, and picks it up again", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));

    act(() => result.current.actions.requestLeave());
    expect(result.current.session.phase).toBe("confirm-leave");
    act(() => result.current.actions.confirmLeave());

    expect(result.current.session.phase).toBe("paused");
    expect(push).toHaveBeenCalledWith("/tree?node=c1");
    expect(loadSession()?.attemptId).toBe("attempt-1");
    unmount();

    // A fresh mount, arriving via the resume strip.
    quizApi.getAttempt.mockResolvedValue({
      quiz_id: "attempt-1",
      status: "in_progress",
      resumable: true,
      difficulty: "medium",
      concept_node_id: "c1",
      questions: [question(1), question(2)],
      responses: [
        { question_index: 0, selected_index: 1, is_correct: true, answered_at: "2026-08-22T10:00:00Z" },
      ],
      score: null,
      total: null,
      created_at: "2026-08-22T09:00:00Z",
    } satisfies AttemptDetail);

    const second = mount({ attempt: "attempt-1", source: { kind: "quiz" } });
    await waitFor(() => expect(second.result.current.session.phase).toBe("active"));
    expect(second.result.current.session.cursor).toBe(1);
    expect(second.result.current.session.attemptId).toBe("attempt-1");
    // The origin survives the round trip — it only exists in the stored record.
    expect(second.result.current.session.source).toEqual(ENTRY.source);
  });

  it("resumes an answered-then-unmounted quiz that never reached the leave dialog", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(3));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.cursor).toBe(1));

    // No leave dialog, no CONFIRM_LEAVE — the tab simply goes away.
    unmount();
    const stored = loadSession();
    expect(stored?.attemptId).toBe("attempt-1");
    expect(stored?.items[0].selectedIndex).toBe(3);

    quizApi.getAttempt.mockResolvedValue({
      quiz_id: "attempt-1",
      status: "in_progress",
      resumable: true,
      difficulty: "medium",
      concept_node_id: "c1",
      questions: [question(1), question(2)],
      responses: [
        { question_index: 0, selected_index: 3, is_correct: true, answered_at: "2026-08-22T10:00:00Z" },
      ],
      score: null,
      total: null,
      created_at: "2026-08-22T09:00:00Z",
    } satisfies AttemptDetail);

    const second = mount({ attempt: "attempt-1", source: { kind: "nav" } });
    await waitFor(() => expect(second.result.current.session.phase).toBe("active"));
    expect(second.result.current.session.cursor).toBe(1);
    expect(second.result.current.session.items[0].selectedIndex).toBe(3);
    expect(second.result.current.session.source.kind).toBe("tree");
  });

  it("explains an expired attempt instead of silently doing nothing", async () => {
    quizApi.getAttempt.mockRejectedValue(
      new ApiError("gone", 409, { code: "QUIZ_ATTEMPT_ABANDONED" }),
    );
    const { result } = mount({ attempt: "attempt-9", source: { kind: "quiz" } });
    await waitFor(() => expect(result.current.session.phase).toBe("error"));
    expect(result.current.session.error?.message).toBe(
      "That quiz expired after a day. Start a fresh one.",
    );
    act(() => result.current.actions.dismissError());
    expect(result.current.session.phase).toBe("home");
  });
});

describe("failures the student reads", () => {
  it("maps a generate timeout to its own copy, not a generic 502", async () => {
    quizApi.generateQuiz.mockRejectedValue(
      new ApiError("timeout", 502, { code: "QUIZ_GENERATION_TIMEOUT" }),
    );
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());

    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("error"));
    expect(result.current.session.error).toEqual({
      code: "QUIZ_GENERATION_TIMEOUT",
      message: "Writing this quiz took too long. Try again — it usually works the second time.",
      retryable: true,
    });

    act(() => result.current.actions.dismissError());
    expect(result.current.session.phase).toBe("home");
  });

  it("interpolates Retry-After into the rate-limit copy", async () => {
    quizApi.generateQuiz.mockRejectedValue(
      new ApiError("slow", 429, { code: "QUIZ_RATE_LIMITED", retryAfterSec: 12 }),
    );
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("error"));
    expect(result.current.session.error?.message).toBe(
      "You're quizzing fast — give it 12 seconds and try again.",
    );
  });

  it("shows the 409 copy when the attempt was already scored, and retries the submit", async () => {
    quizApi.generateQuiz.mockResolvedValue(generated(1));
    quizApi.submitQuiz.mockRejectedValueOnce(
      new ApiError("done", 409, { code: "QUIZ_ATTEMPT_ALREADY_COMPLETED" }),
    );

    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });

    await waitFor(() => expect(result.current.session.phase).toBe("error"));
    expect(result.current.session.error?.message).toBe(
      "This quiz was already scored. Your results are on your tree.",
    );

    // Retry goes back through the submit path, not back to home.
    quizApi.submitQuiz.mockResolvedValue(SUBMIT_RESULT);
    await act(async () => {
      result.current.actions.retry();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("results"));
  });
});

describe("exits and persistence", () => {
  it("refuses to exit a live quiz", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.exit());
    expect(push).not.toHaveBeenCalled();
    expect(result.current.session.phase).toBe("active");
  });

  it("clears the stored session on exit", async () => {
    quizApi.generateQuiz.mockResolvedValue(generated(1));
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));
    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("results"));

    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(result.current.session));
    act(() => result.current.actions.exit("/quiz"));
    // Same route, so it replaces rather than pushes — see the Done block below.
    expect(replace).toHaveBeenCalledWith("/quiz");
    expect(loadSession()).toBeNull();
  });

  it("persists an Adjust-dialog choice to prefs", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() =>
      result.current.actions.setConfig({ count: 10, difficulty: "hard", feedback: "as-you-go" }),
    );
    expect(result.current.session.config).toEqual({
      count: 10,
      difficulty: "hard",
      feedback: "as-you-go",
    });
    const { loadPrefs } = await import("./prefs");
    expect(loadPrefs()).toEqual({ count: 10, difficulty: "hard", feedback: "as-you-go" });
  });

  it("holds on the verdict in as-you-go mode instead of advancing", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() =>
      result.current.actions.setConfig({ count: 5, difficulty: "medium", feedback: "as-you-go" }),
    );
    act(() => result.current.actions.start(START));
    await waitFor(() => expect(result.current.session.phase).toBe("active"));

    act(() => result.current.actions.select(1));
    await act(async () => {
      result.current.actions.submitAnswer();
    });
    await waitFor(() => expect(result.current.session.phase).toBe("answered"));
    expect(result.current.session.cursor).toBe(0);
    expect(result.current.session.items[0].verdict?.explanation).toBe("because 0");
    expect(quizApi.submitQuiz).not.toHaveBeenCalled();

    act(() => result.current.actions.next());
    expect(result.current.session.phase).toBe("active");
    expect(result.current.session.cursor).toBe(1);
  });
});
