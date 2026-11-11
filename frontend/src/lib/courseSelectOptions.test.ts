import { describe, it, expect } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import { courseSelectOptions } from "./courseSelectOptions";

const course = (id: string, code: string, name: string): EnrolledCourse => ({
  enrollment_id: `e-${id}`, course_id: id, course_code: code, course_name: name,
  school: "X", department: "CS", color: null, nickname: null, node_count: 0,
  enrolled_at: "2026-01-01", term: "Spring 2026",
});

const COURSES = [
  course("c1", "CS101", "Intro"),
  course("c2", "", "Bio"),
  course("c3", "MA 123", ""),
  course("c4", "", ""),
  course("c0", "AA 100", "First by code, last in input"),
];

describe("courseSelectOptions", () => {
  it("labels by code with the name as description, falling back to the name", () => {
    expect(courseSelectOptions([course("c1", "CS101", "Intro"), course("c2", "", "Bio")])).toEqual([
      { value: "c1", label: "CS101", description: "Intro" },
      { value: "c2", label: "Bio", description: undefined },
    ]);
  });

  // Both callers built their options with this exact inline mapping before it
  // was shared: FlashcardImportModal (via importModalModel.courseOptions) and
  // Study's GuidePickers (inline in its CustomSelect).
  it("gives both callers the list their own mapping built, order kept", () => {
    const before = COURSES.map(c => ({
      value: c.course_id,
      label: c.course_code || c.course_name,
      description: c.course_code ? c.course_name : undefined,
    }));
    expect(courseSelectOptions(COURSES)).toStrictEqual(before);
    expect(courseSelectOptions(COURSES).map(o => o.value)).toEqual(["c1", "c2", "c3", "c4", "c0"]);
    expect(courseSelectOptions([])).toEqual([]);
  });
});
