import { describe, it, expect } from "vitest";
import {
  conceptsForCourse,
  classifyAssessment,
  readiness,
  studyQueue,
  quickReviews,
  pace,
  daysTo,
  fmtDow,
} from "./studyModel";

const NOW = new Date(2026, 10, 8, 12);
const node = (id: string, tier: string, score: number, extra: Record<string, unknown> = {}) => ({
  id, course_id: "c1", concept_name: id.toUpperCase(), mastery_tier: tier, mastery_score: score, ...extra,
});

describe("conceptsForCourse", () => {
  const nodes = [
    node("a", "mastered", 0.9),
    node("b", "learning", 0.5),
    node("c", "unexplored", 0),
    { id: "subject_root__c1", course_id: "c1", is_subject_root: true, mastery_tier: "subject_root" },
    { ...node("x", "mastered", 1), course_id: "other" },
  ];
  const edges = [
    { source: "a", target: "b", relationship_type: "prerequisite" },
    { source: "b", target: "c", relationship_type: "builds_on" },
    { source: "a", target: "c", relationship_type: "related" },
  ];

  it("keeps the course's concepts, maps tiers, and layers by prerequisite depth", () => {
    const cs = conceptsForCourse(nodes, edges, "c1", NOW);
    expect(cs.map(c => [c.id, c.st, c.m, c.group])).toEqual([
      ["a", "mastered", 90, "Foundations"],
      ["b", "progress", 50, "Core Methods"],
      ["c", "new", 0, "Building On"],
    ]);
    // "related" edges are not prerequisites.
    expect(cs[2].pre).toEqual(["b"]);
  });

  it("warns when an unmastered concept rests on an unmastered prerequisite", () => {
    const cs = conceptsForCourse(nodes, edges, "c1", NOW);
    expect(cs[1].gap).toBe("");
    expect(cs[2].gap).toBe("Based on B, which isn't mastered yet. You can still start, but expect to revisit it.");
  });

  it("survives a prerequisite cycle", () => {
    const cyc = [
      { source: "a", target: "b", relationship_type: "prerequisite" },
      { source: "b", target: "a", relationship_type: "prerequisite" },
    ];
    expect(conceptsForCourse(nodes, cyc, "c1", NOW)).toHaveLength(3);
  });

  it("sums this week's mastery events into weekDelta", () => {
    const n = [node("a", "learning", 0.6, { mastery_events: [
      { delta: 0.1, created_at: new Date(2026, 10, 6).toISOString() },
      { delta: 0.3, created_at: new Date(2026, 9, 1).toISOString() },
    ] })];
    expect(conceptsForCourse(n, [], "c1", NOW)[0].weekDelta).toBeCloseTo(0.1);
  });
});

describe("assessments", () => {
  it("classifies exams, quizzes and homework", () => {
    expect(classifyAssessment("exam", "Midterm")).toBe("Exam");
    expect(classifyAssessment("quiz", "Quiz 5")).toBe("Quiz");
    expect(classifyAssessment("other", "Final Exam")).toBe("Exam");
    expect(classifyAssessment("other", "Problem Set 6")).toBe("Homework");
    expect(classifyAssessment(null, "Weekly quiz")).toBe("Quiz");
  });
  it("counts days and formats dates", () => {
    expect(daysTo("2026-11-13", NOW)).toBe(5);
    expect(fmtDow("2026-11-13")).toBe("Fri, Nov 13");
    // Exam tabs pass today: a date in another year carries its year.
    expect(fmtDow("2026-11-13", new Date(2026, 10, 8))).toBe("Fri, Nov 13");
    expect(fmtDow("2025-10-15", new Date(2026, 10, 8))).toBe("Wed, Oct 15, 2025");
  });
});

describe("readiness and queue", () => {
  const cs = conceptsForCourse(
    [node("a", "mastered", 0.9), node("b", "struggling", 0.3), node("c", "learning", 0.6)],
    [], "c1", NOW,
  );
  it("readiness is mean mastery", () => {
    expect(readiness(cs).pct).toBe(60);
  });
  it("struggling comes before learning", () => {
    expect(studyQueue(cs).map(c => c.id)).toEqual(["b", "c"]);
  });
  it("quick reviews pick stale or weak studied concepts", () => {
    const stale = conceptsForCourse(
      [node("a", "mastered", 0.95, { last_studied_at: new Date(2026, 9, 20).toISOString() }),
       node("b", "mastered", 0.95, { last_studied_at: new Date(2026, 10, 7).toISOString() })],
      [], "c1", NOW,
    );
    const qr = quickReviews(stale, NOW);
    expect(qr.map(x => x.t.id)).toEqual(["a"]);
    expect(qr[0].ago).toBe(19);
  });
});

describe("pace", () => {
  it("is silent at the target or with no exam ahead", () => {
    expect(pace({ examTitle: "M", days: 5, readiness: 92, weekGain: 0, weekMinutes: 0 })).toBeNull();
    expect(pace({ examTitle: "M", days: -1, readiness: 50, weekGain: 0, weekMinutes: 0 })).toBeNull();
  });
  it("says on pace when the weekly rate reaches the target", () => {
    const p = pace({ examTitle: "Midterm", days: 10, readiness: 70, weekGain: 14, weekMinutes: 120 })!;
    expect(p.ok).toBe(true);
    expect(p.title).toBe("On pace for Midterm");
  });
  it("converts the gap into minutes per day from the observed rate", () => {
    // 7 points over 140 minutes = 0.05 pts/min; 1 pt/day for 5 days -> 65%;
    // 25 points short = 500 minutes over 5 days = 100/day = 1.7 hours.
    const p = pace({ examTitle: "Midterm", days: 5, readiness: 60, weekGain: 7, weekMinutes: 140 })!;
    expect(p.ok).toBe(false);
    expect(p.title).toBe("You need to spend more time");
    expect(p.body).toContain("about 65% readiness");
    expect(p.body).toContain("1.7 more hours per day");
  });
  it("names the next concept when nothing moved this week", () => {
    const p = pace({ examTitle: "Midterm", days: 5, readiness: 40, weekGain: 0, weekMinutes: 0, nextConcept: "Determinants" })!;
    expect(p.body).toContain("Start with Determinants.");
  });
});
