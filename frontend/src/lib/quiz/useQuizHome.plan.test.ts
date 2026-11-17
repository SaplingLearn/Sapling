// @vitest-environment jsdom
/**
 * The quiz home with `quiz_concept_plan` on (learning-loop spec §13 A143): the
 * proposals, the card's suggestion and the due queue come from
 * `GET /api/quiz/plan`; off, or when the plan fails, the tier ranking stands.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphNode } from "@/lib/types";

const flags = vi.hoisted(() => ({ plan: "on", loop: "on" }));
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (key: string) =>
    key === "quiz_concept_plan" ? flags.plan : key === "learning_loop" ? flags.loop : "off",
}));

const quizApi = vi.hoisted(() => ({
  getAttempt: vi.fn(),
  listAttempts: vi.fn(),
  abandonAttempt: vi.fn(),
  describeConcept: vi.fn(),
  getQuizPlan: vi.fn(),
}));
vi.mock("./api", () => quizApi);

const coreApi = vi.hoisted(() => ({ getCourses: vi.fn(), getGraph: vi.fn() }));
vi.mock("@/lib/api", async importActual => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, getCourses: coreApi.getCourses, getGraph: coreApi.getGraph };
});

import { useQuizHome } from "./useQuizHome";

function node(id: string, over: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    concept_name: id,
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

beforeEach(() => {
  window.localStorage.clear();
  flags.plan = "on";
  flags.loop = "on";
  coreApi.getCourses.mockResolvedValue({ courses: COURSES });
  coreApi.getGraph.mockResolvedValue({
    nodes: [node("weakest", { mastery_score: 0.05 }), node("due-a"), node("due-b"), node("ready")],
    edges: [],
    stats: {},
  });
  quizApi.listAttempts.mockResolvedValue({ total: 0, limit: 20, offset: 0, attempts: [] });
  quizApi.getAttempt.mockResolvedValue({ resumable: false });
  quizApi.describeConcept.mockResolvedValue("A definition.");
  quizApi.getQuizPlan.mockResolvedValue({
    concepts: [
      { node_id: "due-b", concept_name: "due-b", course_id: "course-a", reason: "due", p_known: 0.9, band: "profic", due_at: null, open_misconceptions: 0 },
      { node_id: "due-a", concept_name: "due-a", course_id: "course-a", reason: "due", p_known: 0.92, band: "profic", due_at: null, open_misconceptions: 0 },
      { node_id: "ready", concept_name: "ready", course_id: "course-a", reason: "ready", p_known: 0.4, band: "develop", due_at: null, open_misconceptions: 0 },
    ],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useQuizHome with the learner model's plan", () => {
  it("proposes the plan's concepts in its order and queues its due reviews", async () => {
    const { result } = renderHook(() => useQuizHome("user_andres", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(quizApi.getQuizPlan).toHaveBeenCalledWith("user_andres");
    expect(result.current.planned).toBe(true);
    expect(result.current.candidates.map(c => c.node.id)).toEqual(["due-b", "due-a", "ready"]);
    expect(result.current.primary?.node.id).toBe("due-b");
    expect(result.current.dueQueue).toEqual(["due-b", "due-a"]);
    expect(result.current.due.count).toBe(2);
    expect(result.current.cardConceptId).toBe("due-b");
  });

  it("keeps the tier ranking when the plan fails", async () => {
    quizApi.getQuizPlan.mockRejectedValue(new Error("503"));
    const { result } = renderHook(() => useQuizHome("user_andres", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.planned).toBe(false);
    expect(result.current.primary?.node.id).toBe("weakest");
  });

  it("never asks for the plan while the flag is off", async () => {
    flags.plan = "off";
    const { result } = renderHook(() => useQuizHome("user_andres", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(quizApi.getQuizPlan).not.toHaveBeenCalled();
    expect(result.current.planned).toBe(false);
  });

  it("never asks for the plan while the student's learning_loop flag is off", async () => {
    flags.loop = "off";
    const { result } = renderHook(() => useQuizHome("user_andres", ""));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(quizApi.getQuizPlan).not.toHaveBeenCalled();
    expect(result.current.planned).toBe(false);
  });
});
