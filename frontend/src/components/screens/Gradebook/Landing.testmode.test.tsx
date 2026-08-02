// @vitest-environment jsdom
/**
 * NEXT_PUBLIC_TEST_MODE determinism for the gradebook landing (#426).
 *
 * The term-chip preselection calls `currentTerm(terms, today)`. Under the
 * frozen test-mode clock, `today` must come from `now()` — never the real
 * wall clock — or Gradebook can pick a different "current" semester than
 * Dashboard shows for the same data (the #426 cross-page inconsistency).
 *
 * Each test pins the REAL clock (vi.setSystemTime) inside one semester and
 * the frozen test-mode clock inside another, then asserts the chip follows
 * the frozen one. Before the fix the component fell back to `new Date()`,
 * so the real-clock semester won and these tests fail.
 *
 * Module-loading strategy mirrors KnowledgeGraph2D.testmode.test.tsx: the
 * flag is captured when `@/lib/testMode` first evaluates, so stub the env
 * at file scope and import the component lazily in beforeAll.
 */

import React from "react";
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import type { EnrolledCourse, Semester } from "@/lib/api";
import type { GradebookCourseSummary } from "@/lib/types";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

// TranscriptModal (rendered by the landing, #139) pulls useToast; a stable
// stub keeps it from throwing outside a provider (same as Landing.test.tsx).
const toastApi = {
  error: vi.fn(), success: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn(), dismiss: vi.fn(),
};
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => toastApi,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(),
  getGradebookSummary: vi.fn(),
  getSemesters: vi.fn(),
  getGpa: vi.fn(),
}));

// Presentational children — stubbed so the test only exercises the landing's
// own term resolution (same set as Landing.test.tsx).
vi.mock("@/components/Gradebook/AmbientOrbs", () => ({
  AmbientOrbs: () => null,
}));
vi.mock("@/components/Gradebook/SyllabusUploadFlow", () => ({
  SyllabusUploadFlow: () => null,
}));
vi.mock("@/components/Gradebook/CourseCard", () => ({
  CourseCard: ({ course }: { course: GradebookCourseSummary }) => (
    <a href="#">{course.course_name}</a>
  ),
  COURSE_CARD_GRID_GAP: 24,
  COURSE_CARD_HEIGHT: 244,
}));

let GradebookLanding: (typeof import("./Landing"))["GradebookLanding"];

beforeAll(async () => {
  ({ GradebookLanding } = await import("./Landing"));
});

import { getCourses, getGradebookSummary, getSemesters } from "@/lib/api";

const mockedGetCourses = vi.mocked(getCourses);
const mockedGetSummary = vi.mocked(getGradebookSummary);
const mockedGetSemesters = vi.mocked(getSemesters);

const SEMESTERS: Semester[] = [
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

const pressedChip = () =>
  screen
    .getAllByRole("button")
    .filter((b) => b.getAttribute("aria-pressed") === "true")
    .map((b) => b.textContent);

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockedGetSummary.mockResolvedValue({ courses: [], gpa: null, semester: "" });
  mockedGetSemesters.mockResolvedValue({ semesters: SEMESTERS });
  mockedGetCourses.mockResolvedValue({
    courses: [course("bio", "Fall 2025"), course("psy", "Spring 2026")],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  globalThis.__SAPLING_TEST_NOW__ = undefined;
});

describe("GradebookLanding under NEXT_PUBLIC_TEST_MODE (#426)", () => {
  it("preselects the term the FROZEN clock falls in, not the real-clock term", async () => {
    // Real wall clock: inside Spring 2026 (the wrong answer).
    vi.setSystemTime(new Date(2026, 2, 11));
    // Injected frozen clock (the Playwright seam): mid Fall 2025.
    globalThis.__SAPLING_TEST_NOW__ = Date.UTC(2025, 9, 15, 12, 0, 0);

    render(<GradebookLanding />);

    const chip = await screen.findByRole("button", { name: "Fall 2025" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(pressedChip()).toEqual(["Fall 2025"]);
  });

  it("defaults to TEST_NOW_MS (2026-03-11) when no clock is injected", async () => {
    // Real wall clock: inside Fall 2025. The frozen default instant
    // (2026-03-11) sits inside Spring 2026, which must win.
    vi.setSystemTime(new Date(2025, 9, 1));

    render(<GradebookLanding />);

    const chip = await screen.findByRole("button", { name: "Spring 2026" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(pressedChip()).toEqual(["Spring 2026"]);
  });
});
