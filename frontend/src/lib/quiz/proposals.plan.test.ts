/**
 * The quiz home from the learner model's plan (learning-loop spec §13 A143,
 * `quiz_concept_plan`): the plan's order, its reasons and its due queue, over
 * the scoped graph only.
 */
import { describe, expect, it } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import {
  courseQueueFromPlan,
  dueFromPlan,
  metaLine,
  planReasonCopy,
  planStateLine,
  plannedCourseQueue,
  rankFromPlan,
  shownMastery,
  skillPercent,
} from "./proposals";
import type { QuizPlan } from "./types";

function node(id: string, course: string | null, over: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    concept_name: id.toUpperCase(),
    course_id: course,
    mastery_score: 0.5,
    mastery_tier: "learning",
    times_studied: 1,
    last_studied_at: null,
    subject: "CS",
    is_subject_root: false,
    ...over,
  } as GraphNode;
}

const COURSES = [
  { course_id: "cs1", course_code: "CS 111", course_name: "Intro", color: "#123456" },
  { course_id: "ma1", course_code: "MA 121", course_name: "Calc", color: "#654321" },
] as unknown as EnrolledCourse[];

const PLAN: QuizPlan = {
  concepts: [
    { node_id: "due1", concept_name: "DUE1", course_id: "cs1", reason: "due", p_known: 0.96, band: "profic", due_at: "2026-11-07T00:00:00Z", open_misconceptions: 0 },
    { node_id: "other_term", concept_name: "X", course_id: "zz", reason: "due", p_known: 0.9, band: "profic", due_at: "2026-11-06T00:00:00Z", open_misconceptions: 0 },
    { node_id: "due2", concept_name: "DUE2", course_id: "ma1", reason: "due", p_known: 0.81, band: "profic", due_at: "2026-11-08T00:00:00Z", open_misconceptions: 0 },
    { node_id: "mix", concept_name: "MIX", course_id: "cs1", reason: "misconception", p_known: 0.4, band: "develop", due_at: null, open_misconceptions: 2 },
    { node_id: "ready", concept_name: "READY", course_id: "cs1", reason: "ready", p_known: 0.354, band: "develop", due_at: null, open_misconceptions: 0 },
  ],
};

const NODES = [node("ready", "cs1"), node("mix", "cs1"), node("due2", "ma1"), node("due1", "cs1"), node("root", null, { is_subject_root: true })];

describe("rankFromPlan", () => {
  it("keeps the plan's order over the scoped graph and carries its reason", () => {
    const ranked = rankFromPlan(PLAN, NODES, COURSES, []);
    expect(ranked.map(c => c.node.id)).toEqual(["due1", "due2", "mix", "ready"]);
    expect(ranked.map(c => c.rationale)).toEqual([
      "skill 96% · due for review",
      "skill 81% · due for review",
      "skill 40% · mixed up before",
      "skill 35% · ready to learn",
    ]);
    expect(ranked[2].plan).toEqual({ reason: "misconception", pKnown: 0.4, band: "develop" });
    expect(ranked[0].course?.course_code).toBe("CS 111");
  });
});

describe("courseQueueFromPlan", () => {
  it("is the course's proposed concepts in the plan's order, never one the plan leaves out", () => {
    const ranked = rankFromPlan(PLAN, NODES, COURSES, []);
    expect(courseQueueFromPlan(ranked, "cs1")).toEqual(["due1", "mix", "ready"]);
    expect(courseQueueFromPlan(ranked, "ma1")).toEqual(["due2"]);
    expect(courseQueueFromPlan(ranked, "none")).toEqual([]);
  });
});

describe("plannedCourseQueue", () => {
  const ranked = rankFromPlan(PLAN, NODES, COURSES, []);

  it("prefers the course's own plan, in its order", () => {
    const own = rankFromPlan({ concepts: [PLAN.concepts[4], PLAN.concepts[0]] }, NODES, COURSES, []);
    expect(plannedCourseQueue(ranked, own, NODES, "cs1")).toEqual(["ready", "due1"]);
  });

  it("uses the all-courses plan's concepts of the course when its own plan is missing", () => {
    expect(plannedCourseQueue(ranked, null, NODES, "cs1")).toEqual(["due1", "mix", "ready"]);
    expect(plannedCourseQueue(ranked, undefined, NODES, "ma1")).toEqual(["due2"]);
  });

  it("falls back to the tier ranking when the plan proposes none of the course's concepts", () => {
    const nodes = [...NODES, node("ph_weak", "ph1", { mastery_score: 0.1, mastery_tier: "struggling" }), node("ph_ok", "ph1", { mastery_score: 0.4 })];
    expect(plannedCourseQueue(ranked, null, nodes, "ph1")).toEqual(["ph_weak", "ph_ok"]);
    // the course's own plan came back empty: still the tier ranking, never an empty queue
    expect(plannedCourseQueue(ranked, [], nodes, "ph1")).toEqual(["ph_weak", "ph_ok"]);
  });

  it("is empty only when the course has nothing to practise at all", () => {
    const nodes = [node("ph_done", "ph1", { mastery_score: 0.95, mastery_tier: "mastered" })];
    expect(plannedCourseQueue(ranked, null, nodes, "ph1")).toEqual([]);
  });
});

describe("dueFromPlan", () => {
  it("is the plan's due reviews in its order, counted across courses", () => {
    expect(dueFromPlan(PLAN, NODES)).toEqual({ conceptIds: ["due1", "due2"], count: 2, courseCount: 2 });
  });
});

describe("one measure per concept (metaLine)", () => {
  const NOW = new Date("2026-11-08T12:00:00Z");
  const fresh = node("fresh", "cs1", { mastery_score: 0.15, mastery_tier: "struggling", times_studied: 0 });
  const plan = { reason: "ready" as const, pKnown: 0.35, band: "develop" as const };

  it("reads the plan's skill meter and band for a concept the plan proposes", () => {
    expect(metaLine(fresh, NOW, plan)).toBe("35% · developing · not studied yet");
    expect(planStateLine(fresh, plan, NOW)).toBe("developing · not studied yet");
    expect(shownMastery(fresh, plan)).toBe(0.35);
  });

  it("keeps the graph's score and tier without one", () => {
    expect(metaLine(fresh, NOW)).toBe("15% · struggling · not studied yet");
    expect(shownMastery(fresh)).toBe(0.15);
  });

  it("says each band as the quiz results do", () => {
    expect(metaLine(fresh, NOW, { ...plan, band: "novice" })).toBe("35% · just starting · not studied yet");
    expect(metaLine(fresh, NOW, { ...plan, band: "profic", pKnown: 0.91 })).toBe("91% · proficient · not studied yet");
  });
});

describe("the plan's words", () => {
  it("says why, in a student's words", () => {
    expect(planReasonCopy("due")).toMatch(/^Due for review/);
    expect(planReasonCopy("misconception")).toMatch(/mixed this one up before/);
    expect(planReasonCopy("ready")).toMatch(/^Ready to learn/);
    expect(skillPercent(0.354)).toBe("35%");
  });

  it("promises no check of the misconception the round may not target (#866 K43)", () => {
    // The quiz targets a held misconception only with the server-only
    // quiz_planned_questions on, in a multiple-choice or mixed round, and only
    // when the writer tags a distractor that passes the checks: the card cannot
    // know, so it says why the concept is proposed and promises nothing more.
    expect(planReasonCopy("misconception")).toBe("You've mixed this one up before — worth practising again.");
    expect(planReasonCopy("misconception")).not.toMatch(/checks?|this round/i);
  });
});
