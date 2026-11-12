/**
 * Shared by the Study Guides home suites: fixtures, the mocks' defaults and
 * the page render. Test-only: nothing in the app imports it.
 *
 * Each suite declares its own `vi.mock(...)` blocks (they are hoisted per
 * file); this module then sees the same mocked modules the page does.
 */
import { vi } from "vitest";
import { render } from "@testing-library/react";

import { getCourses, type EnrolledCourse } from "@/lib/api";
import { createGuide, getGuideOptions, listGuides, planGuide } from "@/lib/studyGuide/api";
import type { GuideCard, GuideOptions, GuidePlan, MaterialOption } from "@/lib/studyGuide/types";

import { GuidesHome } from "./GuidesHome";

export const mocks = {
  courses: vi.mocked(getCourses),
  list: vi.mocked(listGuides),
  options: vi.mocked(getGuideOptions),
  plan: vi.mocked(planGuide),
  create: vi.mocked(createGuide),
};

// ── fixtures ──────────────────────────────────────────────────────────────

export const NOW = new Date("2026-11-12T12:00:00Z");

const course = (id: string, code: string, name: string): EnrolledCourse => ({
  enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name,
  school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
  enrolled_at: "2026-09-01", term: "Fall 2026",
});
export const CS = course("c1", "CS101", "Intro to CS");
export const MATH = course("c2", "MA225", "Calculus");

export const guide = (over: Partial<GuideCard> = {}): GuideCard => ({
  id: "g1",
  title: "Loops and recursion",
  course_id: "c1",
  course_name: "Intro to CS",
  semester: "Fall 2026",
  scope_kind: "exam",
  scope_label: "Midterm 2",
  goal: "exam_prep",
  depth: "standard",
  status: "ready",
  generated_at: "2026-11-10T12:00:00Z",
  created_at: "2026-11-10T11:58:00Z",
  saved_at: null,
  new_materials: 0,
  bars: [
    { title: "Loops", tier: "learning", weight: 30 },
    { title: "Recursion", tier: "struggling", weight: 50 },
    { title: "Variables", tier: "mastered", weight: 20 },
  ],
  counts: { sections: 3, blocks: 7, practice: 2, minutes: 14 },
  ...over,
});

export const material = (id: string, file_name = `${id}.pdf`, category = "lecture_notes"): MaterialOption => ({
  id, file_name, category, created_at: "2026-11-01T00:00:00Z",
});

/** CS101: the whole course suggests everything, the midterm two lectures. */
export const OPTIONS: GuideOptions = {
  scopes: [
    { kind: "course", id: null, title: "Whole course", due_date: null, suggested_material_ids: ["d1", "d2", "d3"] },
    { kind: "exam", id: "e1", title: "Midterm 2", due_date: "2026-11-21", suggested_material_ids: ["d2", "d3"] },
    { kind: "assignment", id: "a1", title: "Lab 5", due_date: null, suggested_material_ids: ["d1"] },
  ],
  materials: [material("d1", "Lecture 1.pdf"), material("d2", "Lecture 2.pdf"), material("d3", "Recursion slides.pptx", "slides")],
};

export const PLAN: GuidePlan = {
  sections: [
    { title: "Recursion", tier: "struggling", weight: 60 },
    { title: "Loops", tier: "learning", weight: 40 },
  ],
  minutes: 12,
};

export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

// ── harness ───────────────────────────────────────────────────────────────

/** The URL the page reads on mount, and the live one `new` is consumed from. */
export function arriveAt(qs: string) {
  window.history.replaceState(null, "", qs ? `/study/guide?${qs}` : "/study/guide");
}

/** Every mock back to the fixtures. Call in `beforeEach`. */
export function resetMocks() {
  vi.resetAllMocks();
  arriveAt("");
  vi.spyOn(console, "error").mockImplementation(() => {});
  mocks.courses.mockResolvedValue({ courses: [CS, MATH] });
  mocks.list.mockResolvedValue({ guides: [guide()] });
  mocks.options.mockResolvedValue(OPTIONS);
  mocks.plan.mockResolvedValue(PLAN);
  mocks.create.mockResolvedValue({ id: "g-new" });
}

export const renderHome = () => render(<GuidesHome now={NOW} />);
