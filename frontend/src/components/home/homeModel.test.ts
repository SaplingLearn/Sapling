import { describe, it, expect } from "vitest";
import type { GraphNode, GraphEdge } from "@/lib/data";
import {
  buildPrereqs, chainOf, courseFocus, dueReviewConcepts, examRow, goalRow, isExam, needsRefresh,
  notificationPills, sessionDayLabel, splitQuote, weekDaysOf,
} from "./homeModel";

const n = (id: string, tier: GraphNode["mastery_tier"], score = 0, extra: Partial<GraphNode> = {}): GraphNode => ({
  id, name: id.toUpperCase(), subject: "S", color: "#C06020", mastery_tier: tier, mastery_score: score, course_id: "c1", ...extra,
});
const pre = (a: string, b: string, t: GraphEdge["relationship_type"] = "prerequisite"): GraphEdge => ({ source: a, target: b, strength: 1, relationship_type: t });

const NOW = new Date(2026, 2, 1, 9).getTime(); // Sun 1 Mar 2026

describe("prerequisite structure", () => {
  const nodes = [n("a", "mastered", 0.9), n("b", "learning", 0.5), n("c", "unexplored"), n("d", "unexplored")];
  const edges = [pre("a", "b"), pre("b", "c", "builds_on"), pre("c", "d", "related")];
  const prereqs = buildPrereqs(nodes, edges);

  it("reads prerequisite and builds_on edges as order, related as none", () => {
    expect(prereqs.get("b")).toEqual(["a"]);
    expect(prereqs.get("c")).toEqual(["b"]);
    expect(prereqs.get("d")).toBeUndefined();
    expect([...chainOf("c", prereqs)].sort()).toEqual(["a", "b", "c"]);
  });

  it("picks the deepest open concept as the goal and the open frontier as here", () => {
    const f = courseFocus(nodes, prereqs);
    expect(f.goalId).toBe("c");
    expect(f.hereId).toBe("b");
    expect(f.steps).toEqual(["b", "c"]);
    const byId = new Map(nodes.map((x) => [x.id, x]));
    expect(goalRow(f, byId, prereqs)).toMatchObject({ title: "Goal: C", count: "1 of 3 solid", note: "B is the next step." });
  });

  it("flags a mastered concept untouched for weeks as needing a refresh", () => {
    expect(needsRefresh(n("x", "mastered", 1, { last_studied_at: "2026-01-01T00:00:00Z" }), NOW)).toBe(true);
    expect(needsRefresh(n("x", "mastered", 1, { last_studied_at: "2026-02-27T00:00:00Z" }), NOW)).toBe(false);
  });
});

describe("assignments", () => {
  it("builds exam and deadline pills only for what's close", () => {
    const pills = notificationPills([
      { id: "1", user_id: "u", title: "Midterm", due_date: "2026-03-07", assignment_type: "exam" },
      { id: "2", user_id: "u", title: "PS 6", due_date: "2026-03-02", assignment_type: "homework" },
      { id: "3", user_id: "u", title: "Essay", due_date: "2026-04-30", assignment_type: "homework" },
    ], NOW);
    expect(pills.map((p) => p.text)).toEqual(["Midterm in 6 days", "PS 6 due tomorrow"]);
    expect(isExam({ title: "Final exam", assignment_type: undefined })).toBe(true);
  });

  it("summarises exam readiness", () => {
    const row = examRow(
      { id: "e", user_id: "u", title: "Midterm", due_date: "2026-03-06", assignment_type: "exam" },
      [n("a", "mastered"), n("b", "mastered"), n("c", "learning", 0.6), n("d", "unexplored")],
      "MATH210",
    );
    expect(row).toMatchObject({ title: "MATH210 Midterm · Fri", count: "2 of 4 ready", note: "2 concepts to go. Start with D." });
  });
});

describe("misc", () => {
  it("counts concepts with due flashcards", () => {
    expect(dueReviewConcepts([
      { topic: "A", times_reviewed: 0 },
      { topic: "a", times_reviewed: 0 },
      { topic: "B", times_reviewed: 1, last_rating: 3, last_reviewed_at: "2026-02-28T00:00:00Z" },
      { topic: "C", times_reviewed: 1, last_rating: 1, last_reviewed_at: "2026-02-27T00:00:00Z" },
    ], NOW)).toBe(2);
  });

  it("splits a quote from its attribution", () => {
    expect(splitQuote("“Hi.” Me")).toEqual({ text: "“Hi.”", by: "Me" });
    expect(splitQuote("plain")).toEqual({ text: "plain", by: "" });
  });

  it("labels days and weeks in local time", () => {
    expect(sessionDayLabel(new Date(2026, 1, 26, 15).toISOString(), NOW)).toBe("Thursday");
    expect(sessionDayLabel(new Date(2026, 1, 28, 15).toISOString(), NOW)).toBe("Yesterday");
    expect(weekDaysOf(new Date(NOW))[0].getDate()).toBe(23);
  });
});
