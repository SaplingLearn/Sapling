import { describe, expect, it } from "vitest";
import {
  courseTermLabels,
  currentTerm,
  termRankFromLabel,
} from "./semesters";
import type { EnrolledCourse, Semester } from "./api";

/**
 * The four terms seeded by migration 0019, verbatim. Keeping the real rows
 * here means these tests would catch a drift between the client's
 * current-term rule and `services/academics.py::current_term`.
 */
const SEMESTERS: Semester[] = [
  { id: "fall-2026", term: "Fall", year: 2026, label: "Fall 2026", start_date: "2026-08-24", end_date: "2027-01-03", sort_key: 20263 },
  { id: "summer-2026", term: "Summer", year: 2026, label: "Summer 2026", start_date: "2026-05-18", end_date: "2026-08-23", sort_key: 20262 },
  { id: "spring-2026", term: "Spring", year: 2026, label: "Spring 2026", start_date: "2026-01-05", end_date: "2026-05-17", sort_key: 20261 },
  { id: "fall-2025", term: "Fall", year: 2025, label: "Fall 2025", start_date: "2025-08-25", end_date: "2026-01-04", sort_key: 20253 },
];

function course(course_id: string, term: string): EnrolledCourse {
  return {
    enrollment_id: `e-${course_id}`,
    course_id,
    course_code: course_id.toUpperCase(),
    course_name: course_id,
    school: "BU",
    department: "CS",
    color: null,
    nickname: null,
    node_count: 0,
    enrolled_at: "2026-01-01",
    term,
  };
}

describe("termRankFromLabel", () => {
  it("mirrors the sort_key formula (year * 10 + term ordinal)", () => {
    expect(termRankFromLabel("Fall 2025")).toBe(20253);
    expect(termRankFromLabel("Spring 2026")).toBe(20261);
    expect(termRankFromLabel("Summer 2026")).toBe(20262);
    expect(termRankFromLabel("Winter 2026")).toBe(20264);
  });

  it("is case- and order-insensitive", () => {
    expect(termRankFromLabel("fall 2025")).toBe(20253);
    expect(termRankFromLabel("2025 FALL")).toBe(20253);
  });

  it("ranks a bare year below every named term in it", () => {
    expect(termRankFromLabel("2025")).toBe(20250);
    expect(termRankFromLabel("2025")! < termRankFromLabel("Spring 2025")!).toBe(true);
  });

  it("returns null for a label with no year", () => {
    expect(termRankFromLabel("Fall")).toBeNull();
    expect(termRankFromLabel("")).toBeNull();
  });
});

describe("currentTerm", () => {
  it("picks the term whose date range contains today", () => {
    expect(currentTerm(SEMESTERS, "2026-03-01")?.label).toBe("Spring 2026");
    expect(currentTerm(SEMESTERS, "2025-09-10")?.label).toBe("Fall 2025");
    expect(currentTerm(SEMESTERS, "2026-07-01")?.label).toBe("Summer 2026");
  });

  it("includes both range endpoints", () => {
    expect(currentTerm(SEMESTERS, "2026-01-05")?.label).toBe("Spring 2026");
    expect(currentTerm(SEMESTERS, "2026-05-17")?.label).toBe("Spring 2026");
    // One day earlier is still the term that straddles the new year.
    expect(currentTerm(SEMESTERS, "2026-01-04")?.label).toBe("Fall 2025");
  });

  it("falls back to the highest sort_key when today sits in a gap", () => {
    // Well past the last seeded term.
    expect(currentTerm(SEMESTERS, "2030-04-01")?.label).toBe("Fall 2026");
    // Before the first seeded term — same rule, same answer.
    expect(currentTerm(SEMESTERS, "2001-04-01")?.label).toBe("Fall 2026");
  });

  it("breaks a range overlap on the higher sort_key, like the backend's order+limit", () => {
    const overlapping: Semester[] = [
      { id: "a", term: "Spring", year: 2026, label: "Spring 2026", start_date: "2026-01-01", end_date: "2026-12-31", sort_key: 20261 },
      { id: "b", term: "Fall", year: 2026, label: "Fall 2026", start_date: "2026-01-01", end_date: "2026-12-31", sort_key: 20263 },
    ];
    expect(currentTerm(overlapping, "2026-06-01")?.label).toBe("Fall 2026");
  });

  it("accepts a Date and reads it in local time", () => {
    // 23:30 local on the last day of Spring 2026. Converting via toISOString()
    // would roll this into the next day in any timezone east of UTC.
    const d = new Date(2026, 4, 17, 23, 30, 0);
    expect(currentTerm(SEMESTERS, d)?.label).toBe("Spring 2026");
  });

  it("returns null when there are no semesters", () => {
    expect(currentTerm([], "2026-03-01")).toBeNull();
    expect(currentTerm(null, "2026-03-01")).toBeNull();
    expect(currentTerm(undefined, "2026-03-01")).toBeNull();
  });

  it("ignores rows with missing date bounds instead of throwing", () => {
    const partial = [
      { id: "x", term: "Fall", year: 2025, label: "Fall 2025", start_date: "", end_date: "", sort_key: 20253 },
    ] as Semester[];
    expect(currentTerm(partial, "2025-09-10")?.label).toBe("Fall 2025");
  });
});

describe("courseTermLabels", () => {
  it("dedupes and orders most recent first", () => {
    const labels = courseTermLabels(
      [
        course("a", "Fall 2025"),
        course("b", "Spring 2026"),
        course("c", "Fall 2025"),
        course("d", "Fall 2026"),
      ],
      SEMESTERS,
    );
    expect(labels).toEqual(["Fall 2026", "Spring 2026", "Fall 2025"]);
  });

  it("skips courses with no term — a chip for them would filter to nothing", () => {
    expect(courseTermLabels([course("a", ""), course("b", "  ")], SEMESTERS)).toEqual([]);
  });

  it("still orders sensibly with no semesters payload", () => {
    const labels = courseTermLabels([course("a", "Fall 2025"), course("b", "Spring 2026")]);
    expect(labels).toEqual(["Spring 2026", "Fall 2025"]);
  });
});
