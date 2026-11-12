import { describe, it, expect } from "vitest";
import {
  conceptsForCourse,
  categoriesFromChecklist,
  roadmapGroups,
  OTHER_GROUP,
  classifyAssessment,
  readiness,
  conceptIdsForExam,
  readinessBand,
  studyQueue,
  quickReviews,
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

  it("names roadmap columns from the checklist's categories when it covers the course", () => {
    // "Core" parents a + b; "Extras" parents c. Both are real categories.
    const cats = categoriesFromChecklist([
      { id: "core", name: "Core", parent_id: null, node_id: null },
      { id: "extras", name: "Extras", parent_id: null, node_id: null },
      { id: "t-a", name: "A", parent_id: "core", node_id: "a" },
      { id: "t-b", name: "B", parent_id: "core", node_id: "b" },
      { id: "t-c", name: "C", parent_id: "extras", node_id: "c" },
    ]);
    const cs = conceptsForCourse(nodes, edges, "c1", NOW, cats);
    expect(cs.map(c => [c.id, c.group])).toEqual([["a", "Core"], ["b", "Core"], ["c", "Extras"]]);
    expect(roadmapGroups(cs)).toEqual(["Core", "Extras"]);
  });

  it("orders columns by prerequisite depth, not by name", () => {
    // "Later" holds c (depth 2); "Early" holds a (depth 0). Alphabetically
    // "Early" already wins, so flip the names to prove depth is what decides.
    const cats = categoriesFromChecklist([
      { id: "zz", name: "Zebra Unit", parent_id: null, node_id: null },
      { id: "aa", name: "Alpha Unit", parent_id: null, node_id: null },
      { id: "t-a", name: "A", parent_id: "zz", node_id: "a" },
      { id: "t-b", name: "B", parent_id: "zz", node_id: "b" },
      { id: "t-c", name: "C", parent_id: "aa", node_id: "c" },
    ]);
    // Zebra = depths {0, 1} -> mean 0.5; Alpha = depth {2} -> mean 2.
    expect(roadmapGroups(conceptsForCourse(nodes, edges, "c1", NOW, cats)))
      .toEqual(["Zebra Unit", "Alpha Unit"]);
  });

  it("falls back to prerequisite layers when the checklist covers too little", () => {
    const cats = categoriesFromChecklist([
      { id: "core", name: "Core", parent_id: null, node_id: null },
      { id: "t-a", name: "A", parent_id: "core", node_id: "a" },
    ]);
    expect(cats.get("a")).toBe("Core");
    // One concept of three placed: the outline does not speak for this course.
    expect(conceptsForCourse(nodes, edges, "c1", NOW, cats).map(c => c.group))
      .toEqual(["Foundations", "Core Methods", "Building On"]);
  });

  it("places a covered concept outside every category in Other, last", () => {
    const cats = categoriesFromChecklist([
      { id: "core", name: "Core", parent_id: null, node_id: null },
      { id: "t-a", name: "A", parent_id: "core", node_id: "a" },
      { id: "t-b", name: "B", parent_id: "core", node_id: "b" },
      // A root that parents nothing is not a category.
      { id: "t-c", name: "C", parent_id: null, node_id: "c" },
    ]);
    expect(cats.has("c")).toBe(false);
    const cs = conceptsForCourse(nodes, edges, "c1", NOW, cats);
    expect(cs.map(c => c.group)).toEqual(["Core", "Core", OTHER_GROUP]);
    expect(roadmapGroups(cs)).toEqual(["Core", OTHER_GROUP]);
  });

  it("ignores a flat outline, which would give every concept its own column", () => {
    const cats = categoriesFromChecklist([
      { id: "t-a", name: "A", parent_id: null, node_id: "a" },
      { id: "t-b", name: "B", parent_id: null, node_id: "b" },
      { id: "t-c", name: "C", parent_id: null, node_id: "c" },
    ]);
    expect(cats.size).toBe(0);
    expect(conceptsForCourse(nodes, edges, "c1", NOW, cats).map(c => c.group))
      .toEqual(["Foundations", "Core Methods", "Building On"]);
  });

  it("takes the root ancestor, not the immediate parent", () => {
    const cats = categoriesFromChecklist([
      { id: "unit", name: "Unit One", parent_id: null, node_id: null },
      { id: "sub", name: "Sub", parent_id: "unit", node_id: null },
      { id: "t-a", name: "A", parent_id: "sub", node_id: "a" },
    ]);
    expect(cats.get("a")).toBe("Unit One");
  });

  it("survives a broken checklist hierarchy", () => {
    // A parent that is not in the outline, and a cycle.
    const cats = categoriesFromChecklist([
      { id: "t-a", name: "A", parent_id: "missing", node_id: "a" },
      { id: "t-b", name: "B", parent_id: "t-c", node_id: "b" },
      { id: "t-c", name: "C", parent_id: "t-b", node_id: "c" },
    ]);
    expect(cats.has("a")).toBe(false);
    expect(cats.size).toBeGreaterThanOrEqual(0);
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

  it("takes the server's week_delta over the event sum, which only sees the last five events", () => {
    // Six +0.05 moves this week; the payload carries the last five of them.
    const lastFive = Array.from({ length: 5 }, () => ({ delta: 0.05, created_at: new Date(2026, 10, 6).toISOString() }));
    const withTotal = conceptsForCourse([node("a", "learning", 0.6, { mastery_events: lastFive, week_delta: 0.3 })], [], "c1", NOW);
    expect(withTotal[0].weekDelta).toBeCloseTo(0.3);
    // A node that did not move says 0, and that is taken as said.
    const still = conceptsForCourse([node("a", "learning", 0.6, { mastery_events: lastFive, week_delta: 0 })], [], "c1", NOW);
    expect(still[0].weekDelta).toBe(0);
    // An older payload without the field keeps the event sum.
    const older = conceptsForCourse([node("a", "learning", 0.6, { mastery_events: lastFive })], [], "c1", NOW);
    expect(older[0].weekDelta).toBeCloseTo(0.25);
    const odd = conceptsForCourse([node("a", "learning", 0.6, { mastery_events: lastFive, week_delta: null })], [], "c1", NOW);
    expect(odd[0].weekDelta).toBeCloseTo(0.25);
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

describe("conceptIdsForExam", () => {
  const on = (...ids: string[]) => ids.map(id => ({ id }));

  it("is empty with no outline, or no exam", () => {
    expect(conceptIdsForExam([], "e1").size).toBe(0);
    expect(conceptIdsForExam([{ node_id: "a", assessments: on("e1") }], null).size).toBe(0);
    expect(conceptIdsForExam([{ node_id: "a", assessments: on("e1") }], undefined).size).toBe(0);
  });

  it("is empty when the outline links nothing to that exam", () => {
    const outline = [
      { node_id: "a", assessments: on("e2") },
      { node_id: "b", assessments: [] },
      // A partial payload (no `assessments` at all) is read as "on nothing".
      { node_id: "c" },
      { node_id: "d", assessments: null },
    ];
    expect(conceptIdsForExam(outline, "e1").size).toBe(0);
  });

  it("skips topics the graph never matched", () => {
    const outline = [
      { node_id: null, assessments: on("e1") },
      { node_id: "b", assessments: on("e1") },
    ];
    expect([...conceptIdsForExam(outline, "e1")]).toEqual(["b"]);
    expect(conceptIdsForExam([{ node_id: null, assessments: on("e1") }], "e1").size).toBe(0);
  });

  it("returns the nodes of the topics on that exam, once each", () => {
    const outline = [
      { node_id: "a", assessments: on("e1", "e2") },
      { node_id: "b", assessments: on("e2") },
      { node_id: "c", assessments: on("e1") },
      { node_id: "a", assessments: on("e1") }, // two topics on one node
    ];
    expect([...conceptIdsForExam(outline, "e1")].sort()).toEqual(["a", "c"]);
    expect([...conceptIdsForExam(outline, "e2")].sort()).toEqual(["a", "b"]);
  });
});

describe("readinessBand", () => {
  const cs = conceptsForCourse(
    [node("a", "mastered", 0.9), node("b", "struggling", 0.3), node("c", "learning", 0.6)],
    [], "c1", NOW,
  );
  const exam = { id: "e1", title: "Midterm" };
  const on = (...ids: string[]) => ids.map(id => ({ id }));

  it("is the exam's own concepts, named for the exam, when the outline links some", () => {
    const band = readinessBand(cs, [{ node_id: "b", assessments: on("e1") }, { node_id: "c", assessments: on("e1") }], exam, "CS101");
    expect(band.label).toBe("Ready for Midterm");
    expect(band.concepts.map(c => c.id).sort()).toEqual(["b", "c"]);
    expect(readiness(band.concepts).pct).toBe(45); // not the course's 60
  });

  it("is the whole course, named for the course, when the exam has no concepts", () => {
    for (const outline of [
      [],
      [{ node_id: "b", assessments: on("other") }],
      [{ node_id: null, assessments: on("e1") }],
      // Linked, but to a node that is not one of this course's concepts.
      [{ node_id: "elsewhere", assessments: on("e1") }],
    ]) {
      const band = readinessBand(cs, outline, exam, "CS101");
      expect(band.label).toBe("CS101 Readiness");
      expect(band.concepts).toBe(cs);
    }
  });

  it("with no exam selected it is the course's mastery", () => {
    const band = readinessBand(cs, [{ node_id: "b", assessments: on("e1") }], null, "CS101");
    expect(band).toEqual({ concepts: cs, label: "CS101 Mastery" });
  });
});
