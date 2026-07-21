import { describe, expect, it } from "vitest";
import {
  UNKNOWN_TERM_LABEL,
  currentTerm,
  groupCoursesByTerm,
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

const ids = (courses: EnrolledCourse[]) => courses.map((c) => c.course_id);

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

describe("groupCoursesByTerm", () => {
  it("groups by term label, most recent term first", () => {
    const groups = groupCoursesByTerm(
      [course("a", "Fall 2025"), course("b", "Spring 2026"), course("c", "Fall 2025")],
      SEMESTERS,
    );
    expect(groups.map((g) => g.label)).toEqual(["Spring 2026", "Fall 2025"]);
    expect(ids(groups[1].courses)).toEqual(["a", "c"]);
  });

  it("preserves input order inside a group", () => {
    const groups = groupCoursesByTerm(
      [course("z", "Fall 2025"), course("a", "Fall 2025"), course("m", "Fall 2025")],
      SEMESTERS,
    );
    expect(ids(groups[0].courses)).toEqual(["z", "a", "m"]);
  });

  it("buckets courses with an empty or whitespace term instead of dropping them", () => {
    const groups = groupCoursesByTerm(
      [course("a", "Spring 2026"), course("b", ""), course("c", "   ")],
      SEMESTERS,
    );
    const other = groups.find((g) => g.label === UNKNOWN_TERM_LABEL);
    expect(ids(other!.courses)).toEqual(["b", "c"]);
    // Unrankable bucket sorts last.
    expect(groups[groups.length - 1].label).toBe(UNKNOWN_TERM_LABEL);
  });

  it("keeps a course whose term field is missing entirely", () => {
    const missing = { ...course("a", "") } as Partial<EnrolledCourse>;
    delete missing.term;
    const groups = groupCoursesByTerm([missing as EnrolledCourse], SEMESTERS);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe(UNKNOWN_TERM_LABEL);
  });

  it("orders by label rank when no semesters are supplied", () => {
    const groups = groupCoursesByTerm([
      course("a", "Fall 2025"),
      course("b", "Fall 2026"),
      course("c", "Spring 2026"),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Fall 2026", "Spring 2026", "Fall 2025"]);
  });

  it("prefers the server sort_key over the label rank when they disagree", () => {
    // A school whose 'Winter 2026' term genuinely precedes Spring 2026.
    // Label parsing alone would rank Winter after Spring.
    const custom: Semester[] = [
      { id: "w", term: "Winter", year: 2026, label: "Winter 2026", start_date: "2026-01-02", end_date: "2026-01-20", sort_key: 20260 },
      { id: "s", term: "Spring", year: 2026, label: "Spring 2026", start_date: "2026-01-21", end_date: "2026-05-17", sort_key: 20261 },
    ];
    const groups = groupCoursesByTerm(
      [course("a", "Winter 2026"), course("b", "Spring 2026")],
      custom,
    );
    expect(groups.map((g) => g.label)).toEqual(["Spring 2026", "Winter 2026"]);
  });

  it("returns an empty list for no courses", () => {
    expect(groupCoursesByTerm([], SEMESTERS)).toEqual([]);
    expect(groupCoursesByTerm(null, SEMESTERS)).toEqual([]);
  });
});
