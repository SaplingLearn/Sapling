import { describe, expect, it } from "vitest";
import { recommendationsFromNext } from "./learnerNext";
import type { StudyNext } from "./studyApi";

const concept = (
  node_id: string,
  concept_name: string,
  reason: "due" | "misconception" | "ready",
  course_id = "c1",
) => ({
  node_id,
  concept_name,
  course_id,
  reason,
  p_known: 0.5,
  band: "develop" as const,
  due_at: reason === "due" ? "2026-11-07T12:00:00Z" : null,
  open_misconceptions: reason === "misconception" ? 1 : 0,
});

describe("recommendationsFromNext (W8.7)", () => {
  it("flattens due → misconceptions → ready and caps at three", () => {
    const next: StudyNext = {
      due: [concept("d1", "Arrays", "due"), concept("d2", "Trees", "due")],
      misconceptions: [concept("m1", "Heaps", "misconception")],
      ready: [concept("r1", "Graphs", "ready"), concept("r2", "Sorts", "ready")],
    };
    const rows = recommendationsFromNext(next);
    expect(rows.map((r) => r.concept_name)).toEqual(["Arrays", "Trees", "Heaps"]);
    expect(rows[0]).toMatchObject({
      node_id: "d1",
      course_id: "c1",
      reason: expect.stringMatching(/due for review/i),
    });
    expect(rows[2].reason).toMatch(/mixed this one up/i);
  });

  it("falls through to ready when due and misconceptions are empty", () => {
    const next: StudyNext = {
      due: [],
      misconceptions: [],
      ready: [concept("r1", "Graphs", "ready")],
    };
    expect(recommendationsFromNext(next)).toEqual([
      {
        concept_name: "Graphs",
        node_id: "r1",
        course_id: "c1",
        reason: expect.stringMatching(/ready to learn/i),
      },
    ]);
  });

  it("returns [] for empty buckets", () => {
    expect(recommendationsFromNext({ due: [], misconceptions: [], ready: [] })).toEqual([]);
  });
});
