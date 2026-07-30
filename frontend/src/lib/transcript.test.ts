/**
 * buildTranscript (#139) — pure grouping + per-semester GPA for the
 * transcript modal. The GPA math must mirror
 * backend/services/gradebook_service.py::weighted_gpa exactly:
 * grade_points == null rows are listed but excluded from the math,
 * null/zero/negative credits count as 1, and an empty group yields null.
 */
import { describe, it, expect } from "vitest";

import { buildTranscript, weightedGpa } from "./transcript";
import type { GpaCourseRow } from "./types";

function row(overrides: Partial<GpaCourseRow>): GpaCourseRow {
  return {
    course_id: "c1",
    course_code: "CS101",
    semester: "Fall 2025",
    credits: 3,
    percent: 90,
    letter: "A-",
    grade_points: 3.7,
    ...overrides,
  };
}

describe("weightedGpa", () => {
  it("credit-weights grade points (mirrors backend weighted_gpa)", () => {
    // (4.0 * 4 + 3.0 * 2) / 6 = 22 / 6
    const gpa = weightedGpa([
      row({ grade_points: 4.0, credits: 4 }),
      row({ grade_points: 3.0, credits: 2 }),
    ]);
    expect(gpa).toBeCloseTo(22 / 6, 10);
  });

  it("defaults null credits to 1", () => {
    // (4.0 * 1 + 2.0 * 3) / 4 = 10 / 4
    const gpa = weightedGpa([
      row({ grade_points: 4.0, credits: null }),
      row({ grade_points: 2.0, credits: 3 }),
    ]);
    expect(gpa).toBeCloseTo(2.5, 10);
  });

  it("defaults zero credits to 1 (backend treats falsy credits as 1)", () => {
    const gpa = weightedGpa([
      row({ grade_points: 4.0, credits: 0 }),
      row({ grade_points: 2.0, credits: 1 }),
    ]);
    expect(gpa).toBeCloseTo(3.0, 10);
  });

  it("excludes grade_points null rows from the math", () => {
    const gpa = weightedGpa([
      row({ grade_points: 4.0, credits: 3 }),
      row({ grade_points: null, percent: null, letter: null, credits: 100 }),
    ]);
    expect(gpa).toBe(4.0);
  });

  it("returns null when nothing contributes", () => {
    expect(weightedGpa([])).toBeNull();
    expect(weightedGpa([row({ grade_points: null })])).toBeNull();
  });
});

describe("buildTranscript", () => {
  it("groups rows by semester label, most recent first", () => {
    const transcript = buildTranscript([
      row({ course_id: "a", semester: "Fall 2025" }),
      row({ course_id: "b", semester: "Spring 2026" }),
      row({ course_id: "c", semester: "Fall 2025" }),
    ]);
    expect(transcript.map((s) => s.label)).toEqual(["Spring 2026", "Fall 2025"]);
    expect(transcript[1].courses.map((c) => c.course_id)).toEqual(["a", "c"]);
  });

  it("sorts labels it cannot rank to the end", () => {
    const transcript = buildTranscript([
      row({ course_id: "a", semester: "Mystery Term" }),
      row({ course_id: "b", semester: "Spring 2026" }),
    ]);
    expect(transcript.map((s) => s.label)).toEqual(["Spring 2026", "Mystery Term"]);
  });

  it("computes a per-semester credit-weighted GPA", () => {
    const transcript = buildTranscript([
      row({ course_id: "a", semester: "Fall 2025", grade_points: 4.0, credits: 4 }),
      row({ course_id: "b", semester: "Fall 2025", grade_points: 3.0, credits: 2 }),
      row({ course_id: "c", semester: "Spring 2026", grade_points: 2.0, credits: 3 }),
    ]);
    const fall = transcript.find((s) => s.label === "Fall 2025")!;
    const spring = transcript.find((s) => s.label === "Spring 2026")!;
    expect(fall.gpa).toBeCloseTo(22 / 6, 10);
    expect(spring.gpa).toBeCloseTo(2.0, 10);
  });

  it("still lists in-progress rows but leaves them out of the semester GPA", () => {
    const transcript = buildTranscript([
      row({ course_id: "a", semester: "Spring 2026", grade_points: 4.0, credits: 2 }),
      row({
        course_id: "b",
        semester: "Spring 2026",
        grade_points: null,
        percent: null,
        letter: null,
        credits: 5,
      }),
    ]);
    expect(transcript[0].courses).toHaveLength(2);
    expect(transcript[0].gpa).toBe(4.0);
  });

  it("yields a null GPA for a semester with no graded rows", () => {
    const transcript = buildTranscript([
      row({ course_id: "a", grade_points: null, percent: null, letter: null }),
    ]);
    expect(transcript[0].gpa).toBeNull();
    expect(transcript[0].courses).toHaveLength(1);
  });

  it("returns an empty transcript for no rows", () => {
    expect(buildTranscript([])).toEqual([]);
  });
});
