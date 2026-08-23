// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { GraphNode } from "@/lib/types";

const quizApi = vi.hoisted(() => ({
  fetchQuizConfig: vi.fn(),
  generateQuiz: vi.fn(),
  answerQuestion: vi.fn(),
  submitQuiz: vi.fn(),
  getAttempt: vi.fn(),
  listAttempts: vi.fn(),
  abandonAttempt: vi.fn(),
  describeConcept: vi.fn(),
}));
vi.mock("./api", () => quizApi);

const coreApi = vi.hoisted(() => ({ getCourses: vi.fn(), getGraph: vi.fn() }));
vi.mock("@/lib/api", async importActual => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, getCourses: coreApi.getCourses, getGraph: coreApi.getGraph };
});

import { fallbackDefinition, useQuizHome } from "./useQuizHome";
import { dismissAttempt, isDismissed, saveSession } from "./session";
import { initialSession } from "./machine";
import { DEFAULT_PREFS } from "./prefs";
import type { EntryRequest } from "./source";
import type { AttemptSummary } from "./types";

function node(over: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    concept_name: over.id,
    mastery_score: 0.3,
    mastery_tier: "struggling",
    times_studied: 1,
    last_studied_at: null,
    subject: "CS",
    course_id: "course-a",
    ...over,
  };
}

const COURSES = [
  {
    enrollment_id: "e1", course_id: "course-a", course_code: "CS 330", course_name: "Algorithms",
    school: "BU", department: "CS", color: "#123456", nickname: null, node_count: 3,
    enrolled_at: "2026-01-01T00:00:00Z", term: "Fall 2026", terms: ["Fall 2026"],
  },
];

function attempt(over: Partial<AttemptSummary> & { quiz_id: string }): AttemptSummary {
  return {
    status: "in_progress",
    concept_node_id: "n1",
    concept_name: "n1",
    course_id: "course-a",
    score: null,
    total: null,
    difficulty: "medium",
    mastery_before: null,
    mastery_after: null,
    mastery_delta: null,
    created_at: "2026-08-22T09:00:00Z",
    completed_at: null,
    ...over,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  coreApi.getCourses.mockResolvedValue({ courses: COURSES });
  coreApi.getGraph.mockResolvedValue({
    nodes: [
      node({ id: "n-new", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0 }),
      node({ id: "n1", mastery_score: 0.29, times_studied: 3 }),
      node({ id: "n2", mastery_score: 0.44, mastery_tier: "learning" }),
      node({ id: "n-done", mastery_score: 0.9, mastery_tier: "mastered" }),
    ],
    edges: [],
    stats: {},
  });
  quizApi.listAttempts.mockResolvedValue({ total: 0, limit: 20, offset: 0, attempts: [] });
  quizApi.getAttempt.mockResolvedValue({ resumable: false });
  quizApi.abandonAttempt.mockResolvedValue({
    quiz_id: "open", status: "abandoned", abandoned_at: "2026-08-23T02:00:00Z",
  });
  quizApi.describeConcept.mockResolvedValue("Recursion is a function calling itself.");
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("bootstrap", () => {
  it("waits for the active semester to hydrate before fetching", async () => {
    renderHook(() => useQuizHome("u1", null));
    await new Promise(r => setTimeout(r, 0));
    expect(coreApi.getGraph).not.toHaveBeenCalled();
  });

  it("fetches unscoped for 'All semesters' and scoped for a term", async () => {
    const { rerender } = renderHook(({ s }: { s: string }) => useQuizHome("u1", s), {
      initialProps: { s: "" },
    });
    await waitFor(() => expect(coreApi.getGraph).toHaveBeenCalledWith("u1", undefined));

    rerender({ s: "Fall 2026" });
    await waitFor(() => expect(coreApi.getGraph).toHaveBeenCalledWith("u1", "Fall 2026"));
  });

  it("ranks candidates, picks a studied primary, and counts the due set", async () => {
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.candidates.map(c => c.node.id)).toEqual(["n-new", "n1", "n2"]);
    // R-7: the primary prefers the weakest concept actually studied.
    expect(result.current.primary?.node.id).toBe("n1");
    expect(result.current.alternatives.map(c => c.node.id)).toEqual(["n-new", "n2"]);
    expect(result.current.due.count).toBe(3);
    expect(result.current.due.courseCount).toBe(1);
    expect(result.current.byCourse[0].course.course_code).toBe("CS 330");
  });

  it("keeps the home screen when only the history read fails", async () => {
    quizApi.listAttempts.mockRejectedValue(new ApiError("boom", 500));
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.attempts).toEqual([]);
  });

  it("reports an error when the graph read fails", async () => {
    coreApi.getGraph.mockRejectedValue(new ApiError("boom", 500, { code: "QUIZ_INTERNAL_ERROR" }));
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.message).toBe(
      "Something went wrong on our side. Try again in a moment.",
    );
  });
});

describe("resume discovery (R-3)", () => {
  it("verifies the stored attempt id against the wire before offering it", async () => {
    const stored = {
      ...initialSession({ source: { kind: "tree" }, concept: "n1" }, null, DEFAULT_PREFS),
      attemptId: "attempt-stored",
      phase: "paused" as const,
    };
    saveSession(stored);
    quizApi.getAttempt.mockResolvedValue({
      quiz_id: "attempt-stored",
      status: "in_progress",
      resumable: true,
      difficulty: "medium",
      concept_node_id: "n1",
      questions: [],
      responses: [{ question_index: 0, selected_index: 1, is_correct: true, answered_at: "x" }],
      score: null,
      total: null,
      created_at: "2026-08-22T09:00:00Z",
    });

    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.resumable).not.toBeNull());
    expect(quizApi.getAttempt).toHaveBeenCalledWith("attempt-stored");
    expect(result.current.resumable?.answered).toBe(1);
    expect(result.current.resumable?.session?.attemptId).toBe("attempt-stored");
  });

  it("finds an in_progress attempt started on another device", async () => {
    quizApi.listAttempts.mockResolvedValue({
      total: 2,
      limit: 20,
      offset: 0,
      attempts: [
        attempt({ quiz_id: "done", status: "completed", score: 3, total: 3 }),
        attempt({ quiz_id: "open" }),
      ],
    });
    quizApi.getAttempt.mockResolvedValue({
      quiz_id: "open", status: "in_progress", resumable: true, difficulty: "medium",
      concept_node_id: "n1", questions: [], responses: [], score: null, total: null,
      created_at: "2026-08-22T09:00:00Z",
    });

    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.resumable?.attempt.quiz_id).toBe("open"));
    // No local record for it, so there is no stored session to restore.
    expect(result.current.resumable?.session).toBeNull();
    expect(quizApi.getAttempt).toHaveBeenCalledTimes(1);
    expect(quizApi.getAttempt).toHaveBeenCalledWith("open");
  });

  it("skips a locally dismissed attempt without spending a request on it", async () => {
    dismissAttempt("open");
    quizApi.listAttempts.mockResolvedValue({
      total: 1, limit: 20, offset: 0, attempts: [attempt({ quiz_id: "open" })],
    });

    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await new Promise(r => setTimeout(r, 0));
    expect(quizApi.getAttempt).not.toHaveBeenCalled();
    expect(result.current.resumable).toBeNull();
  });

  it("moves on when the wire says an attempt is no longer resumable", async () => {
    quizApi.listAttempts.mockResolvedValue({
      total: 2, limit: 20, offset: 0,
      attempts: [attempt({ quiz_id: "stale" }), attempt({ quiz_id: "live" })],
    });
    quizApi.getAttempt.mockImplementation((id: string) =>
      id === "stale"
        ? Promise.reject(new ApiError("gone", 409, { code: "QUIZ_ATTEMPT_ABANDONED" }))
        : Promise.resolve({
          quiz_id: "live", status: "in_progress", resumable: true, difficulty: "medium",
          concept_node_id: "n1", questions: [], responses: [], score: null, total: null,
          created_at: "2026-08-22T09:00:00Z",
        }),
    );

    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.resumable?.attempt.quiz_id).toBe("live"));
  });
});

describe("discard (G4)", () => {
  const OPEN = { total: 1, limit: 20, offset: 0, attempts: [{ ...attempt({ quiz_id: "open" }) }] };
  const RESUMABLE = {
    quiz_id: "open", status: "in_progress", resumable: true, difficulty: "medium",
    concept_node_id: "n1", questions: [], responses: [], score: null, total: null,
    created_at: "2026-08-22T09:00:00Z",
  };

  async function homeWithAResumableAttempt() {
    quizApi.listAttempts.mockResolvedValue(OPEN);
    quizApi.getAttempt.mockResolvedValue(RESUMABLE);
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.resumable?.attempt.quiz_id).toBe("open"));
    return result;
  }

  it("abandons the attempt server-side and drops it from the strip at once", async () => {
    const result = await homeWithAResumableAttempt();

    await act(async () => {
      result.current.discard("open");
    });

    // The durable half: the row is closed for every other device too.
    expect(quizApi.abandonAttempt).toHaveBeenCalledWith("open");
    // …and the optimistic half, which is what makes the strip vanish now.
    expect(isDismissed("open")).toBe(true);
    expect(result.current.resumable).toBeNull();
  });

  it("re-reads the world, so the strip's next answer comes off the wire", async () => {
    const result = await homeWithAResumableAttempt();
    const before = quizApi.listAttempts.mock.calls.length;

    // What the server says once the abandon has landed.
    quizApi.listAttempts.mockResolvedValue({
      ...OPEN, attempts: [{ ...attempt({ quiz_id: "open", status: "abandoned" }) }],
    });

    await act(async () => {
      result.current.discard("open");
    });
    await waitFor(() =>
      expect(quizApi.listAttempts.mock.calls.length).toBeGreaterThan(before),
    );
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.resumable).toBeNull();
  });

  it("keeps the attempt hidden when the abandon call fails", async () => {
    // Resurrecting a quiz the student just discarded is the worse answer; the
    // backend's 24h sweep is the backstop for the row itself.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    quizApi.abandonAttempt.mockRejectedValue(new ApiError("boom", 500));
    const result = await homeWithAResumableAttempt();

    await act(async () => {
      result.current.discard("open");
    });

    expect(isDismissed("open")).toBe(true);
    expect(result.current.resumable).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("does nothing at all for an empty id", async () => {
    const result = await homeWithAResumableAttempt();

    await act(async () => {
      result.current.discard("");
    });

    expect(quizApi.abandonAttempt).not.toHaveBeenCalled();
    expect(result.current.resumable?.attempt.quiz_id).toBe("open");
  });
});

describe("the card's concept (§5 B1.2 entry overrides)", () => {
  function entry(over: Partial<EntryRequest> = {}): EntryRequest {
    return { source: { kind: "link" }, ...over };
  }

  it("is the ranked primary when nothing was deep-linked", async () => {
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.cardConceptId).toBe("n1");
    expect(result.current.primary?.node.id).toBe("n1");
  });

  it("follows a ?concept= deep link, even to a concept the ranking would not pick", async () => {
    const { result } = renderHook(() => useQuizHome("u1", "", entry({ concept: "n2" })));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.cardConceptId).toBe("n2");
    // The ranking is untouched — only the card moved.
    expect(result.current.primary?.node.id).toBe("n1");
  });

  it("follows a ?topic= name", async () => {
    const { result } = renderHook(() => useQuizHome("u1", "", entry({ topic: "n2" })));
    await waitFor(() => expect(result.current.cardConceptId).toBe("n2"));
  });

  it("opens a ?course= entry on that course's weakest due concept", async () => {
    coreApi.getGraph.mockResolvedValue({
      nodes: [
        node({ id: "a-strongish", mastery_score: 0.4, course_id: "course-a" }),
        node({ id: "b-weak", mastery_score: 0.05, course_id: "course-b" }),
        node({ id: "b-mid", mastery_score: 0.3, course_id: "course-b" }),
      ],
      edges: [],
      stats: {},
    });
    const { result } = renderHook(() => useQuizHome("u1", "", entry({ course: "course-b" })));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.cardConceptId).toBe("b-weak");
  });

  it("opens a ?scope=due entry on the weakest due concept overall", async () => {
    const { result } = renderHook(() => useQuizHome("u1", "", entry({ scope: "due" })));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    // n-new scores 0.0 — the raw ranking order, not the studied-first tie-break.
    expect(result.current.cardConceptId).toBe("n-new");
  });

  it("falls back to the ranking when the deep link points outside the scope", async () => {
    const { result } = renderHook(() => useQuizHome("u1", "", entry({ concept: "not-here" })));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.cardConceptId).toBe("n1");
  });

  it("is null before the graph has loaded", () => {
    const { result } = renderHook(() => useQuizHome("u1", null, entry({ concept: "n2" })));
    expect(result.current.cardConceptId).toBeNull();
  });
});

describe("the card definition (R-8)", () => {
  it("asks for exactly one description — the CARD's concept, not the primary's", async () => {
    const deepLink: EntryRequest = { source: { kind: "tree" }, concept: "n2" };
    const { result } = renderHook(() => useQuizHome("u1", "", deepLink));
    await waitFor(() => expect(result.current.cardDescription).not.toBeNull());
    expect(quizApi.describeConcept).toHaveBeenCalledTimes(1);
    expect(quizApi.describeConcept).toHaveBeenCalledWith("u1", "n2", "CS 330");
  });

  it("describes the primary when there is no deep link", async () => {
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.cardDescription).not.toBeNull());
    expect(quizApi.describeConcept).toHaveBeenCalledTimes(1);
    expect(quizApi.describeConcept).toHaveBeenCalledWith("u1", "n1", "CS 330");
  });

  it("keeps primaryDescription as an alias of the same value", async () => {
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.cardDescription).not.toBeNull());
    expect(result.current.primaryDescription).toBe(result.current.cardDescription);
  });

  it("leaves the description null when the call fails, so the card falls back", async () => {
    quizApi.describeConcept.mockRejectedValue(new ApiError("agent down", 502));
    const { result } = renderHook(() => useQuizHome("u1", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await new Promise(r => setTimeout(r, 0));
    expect(result.current.cardDescription).toBeNull();
  });

  // The two queue-shaped cards are headed "Practice {CODE}" / "Review everything
  // due" over a queue summary (§5 B1.2). There is no definition slot on either,
  // so a description for the queue's first concept is an LLM call for text
  // nothing renders.
  it("does not describe a ?course= card — it has no definition slot", async () => {
    const { result } = renderHook(() =>
      useQuizHome("u1", "", { source: { kind: "tree" }, course: "course-a" }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await new Promise(r => setTimeout(r, 0));

    // The concept id is still resolved — Start generates on it, and the accent
    // comes from it. Only the paragraph is skipped.
    expect(result.current.cardConceptId).toBe("n-new");
    expect(result.current.cardDescription).toBeNull();
    expect(quizApi.describeConcept).not.toHaveBeenCalled();
  });

  it("does not describe a ?scope=due card either", async () => {
    const { result } = renderHook(() =>
      useQuizHome("u1", "", { source: { kind: "dashboard" }, scope: "due" }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await new Promise(r => setTimeout(r, 0));

    expect(result.current.cardConceptId).toBe("n-new");
    expect(result.current.cardDescription).toBeNull();
    expect(quizApi.describeConcept).not.toHaveBeenCalled();
  });

  it("still describes when an unusable ?course= falls back to the primary card", async () => {
    const { result } = renderHook(() =>
      useQuizHome("u1", "", { source: { kind: "tree" }, course: "no-such-course" }));
    await waitFor(() => expect(result.current.cardDescription).not.toBeNull());
    expect(result.current.cardConceptId).toBe("n1");
    expect(quizApi.describeConcept).toHaveBeenCalledTimes(1);
    expect(quizApi.describeConcept).toHaveBeenCalledWith("u1", "n1", "CS 330");
  });
});

describe("fallbackDefinition", () => {
  it("builds the sentence the card shows while the description loads", () => {
    const candidate = {
      node: node({ id: "n1", mastery_tier: "struggling" }),
      course: COURSES[0],
      color: "#123456",
      rationale: "",
    };
    expect(fallbackDefinition(candidate, 4)).toBe("CS 330 · struggling · 4 connected concepts");
    expect(fallbackDefinition(candidate, 1)).toBe("CS 330 · struggling · 1 connected concept");
    expect(fallbackDefinition(null, 3)).toBe("");
  });
});
