/**
 * The quiz home from the learner model's plan (learning-loop spec §13 A143,
 * `quiz_concept_plan`): the plan's order, its reasons and its due queue, over
 * the scoped graph only.
 */
import { describe, expect, it } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import { courseQueueFromPlan, dueFromPlan, planReasonCopy, rankFromPlan, skillPercent } from "./proposals";
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
    expect(ranked[2].plan).toEqual({ reason: "misconception", pKnown: 0.4 });
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

describe("dueFromPlan", () => {
  it("is the plan's due reviews in its order, counted across courses", () => {
    expect(dueFromPlan(PLAN, NODES)).toEqual({ conceptIds: ["due1", "due2"], count: 2, courseCount: 2 });
  });
});

describe("the plan's words", () => {
  it("says why, in a student's words", () => {
    expect(planReasonCopy("due")).toMatch(/^Due for review/);
    expect(planReasonCopy("misconception")).toMatch(/mixed this one up before/);
    expect(planReasonCopy("ready")).toMatch(/^Ready to learn/);
    expect(skillPercent(0.354)).toBe("35%");
  });
});
