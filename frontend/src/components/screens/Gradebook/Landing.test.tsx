// @vitest-environment jsdom
/**
 * Regression tests for the gradebook landing's semester chips (#140).
 *
 * The landing used to read `(c as any).semester` off the /courses payload,
 * which has always been `term`. `distinct` was therefore always empty and
 * every signed-in user fell through to the SAMPLE_SEMESTERS demo chips.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { GradebookCourseSummary } from "@/lib/types";

const mockUser = { userId: "u1" as string | null, userReady: true };

vi.mock("@/context/UserContext", () => ({
  useUser: () => mockUser,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(),
  getGradebookSummary: vi.fn(),
  getSemesters: vi.fn(),
}));

// Presentational children — stubbed so the test only exercises the landing's
// own term resolution.
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

import { GradebookLanding } from "./Landing";
import { getCourses, getGradebookSummary, getSemesters } from "@/lib/api";
import type { Semester } from "@/lib/api";

const mockedGetCourses = vi.mocked(getCourses);
const mockedGetSummary = vi.mocked(getGradebookSummary);
const mockedGetSemesters = vi.mocked(getSemesters);

const SEMESTERS: Semester[] = [
  { id: "spring-2025", term: "Spring", year: 2025, label: "Spring 2025", start_date: "2025-01-05", end_date: "2025-05-17", sort_key: 20251 },
  { id: "fall-2024", term: "Fall", year: 2024, label: "Fall 2024", start_date: "2024-08-25", end_date: "2025-01-04", sort_key: 20243 },
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

// The chips are the only aria-pressed controls on the page, so this reads
// the rendered semester list — and its order — without depending on styling.
const chipLabels = () =>
  screen
    .getAllByRole("button")
    .filter((b) => b.getAttribute("aria-pressed") !== null)
    .map((b) => b.textContent);

beforeEach(() => {
  mockUser.userId = "u1";
  mockedGetSummary.mockResolvedValue({ courses: [] });
  mockedGetSemesters.mockResolvedValue({ semesters: SEMESTERS });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/gradebook");
});

describe("GradebookLanding semester chips", () => {
  it("builds the chips from each course's term", async () => {
    mockedGetCourses.mockResolvedValue({
      courses: [course("bio", "Fall 2024"), course("psy", "Spring 2025"), course("mat", "Fall 2024")],
    });

    render(<GradebookLanding />);

    await screen.findByRole("button", { name: "Fall 2024" });
    expect(chipLabels()).toEqual(["Spring 2025", "Fall 2024"]);
  });

  it("preselects the term today falls in, not just the newest one", async () => {
    // Inside Fall 2024's range, which is NOT the highest sort_key.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2024, 9, 1));
    try {
      mockedGetCourses.mockResolvedValue({
        courses: [course("bio", "Fall 2024"), course("psy", "Spring 2025")],
      });

      render(<GradebookLanding />);

      const chip = await screen.findByRole("button", { name: "Fall 2024" });
      expect(chipLabels()).toEqual(["Spring 2025", "Fall 2024"]);
      expect(chip.getAttribute("aria-pressed")).toBe("true");
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens the term named by ?semester= so archived courses deep-link", async () => {
    window.history.replaceState({}, "", "/gradebook?semester=Fall+2024");
    mockedGetCourses.mockResolvedValue({
      courses: [course("bio", "Fall 2024"), course("psy", "Spring 2025")],
    });

    render(<GradebookLanding />);

    const chip = await screen.findByRole("button", { name: "Fall 2024" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(mockedGetSummary).toHaveBeenCalledWith("u1", "Fall 2024"));
  });

  it("ignores a ?semester= the user is not enrolled in", async () => {
    window.history.replaceState({}, "", "/gradebook?semester=Fall+1999");
    mockedGetCourses.mockResolvedValue({ courses: [course("psy", "Spring 2025")] });

    render(<GradebookLanding />);

    const chip = await screen.findByRole("button", { name: "Spring 2025" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
  });

  it("still orders the chips when /api/semesters fails", async () => {
    mockedGetSemesters.mockRejectedValue(new Error("500"));
    mockedGetCourses.mockResolvedValue({
      courses: [course("bio", "Fall 2024"), course("psy", "Spring 2025")],
    });

    render(<GradebookLanding />);

    await screen.findByRole("button", { name: "Fall 2024" });
    expect(chipLabels()).toEqual(["Spring 2025", "Fall 2024"]);
  });

  it("never falls back to the demo chips for a signed-in user", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [course("bio", "Fall 2024")] });

    render(<GradebookLanding />);

    await screen.findByRole("button", { name: "Fall 2024" });
    // SAMPLE_SEMESTERS — the logged-out preview. Leaking these into a real
    // account is the bug this file exists for.
    expect(chipLabels()).toEqual(["Fall 2024"]);
  });

  it("fetches the gradebook summary for the resolved term", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [course("bio", "Fall 2024")] });

    render(<GradebookLanding />);

    await waitFor(() => expect(mockedGetSummary).toHaveBeenCalledWith("u1", "Fall 2024"));
  });

  it("shows the empty state, not demo chips, when the user has no terms", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [] });

    render(<GradebookLanding />);

    expect(await screen.findByText(/A blank semester, ready to plant\./)).toBeInTheDocument();
    expect(screen.queryByText("Spring 2026")).toBeNull();
    expect(mockedGetSummary).not.toHaveBeenCalled();
  });

  it("shows the empty state when the courses request fails", async () => {
    mockedGetCourses.mockRejectedValue(new Error("500"));

    render(<GradebookLanding />);

    expect(await screen.findByText(/A blank semester, ready to plant\./)).toBeInTheDocument();
    expect(screen.queryByText("Spring 2026")).toBeNull();
  });

  it("still previews the sample semesters when logged out", async () => {
    mockUser.userId = null;

    render(<GradebookLanding />);

    await screen.findByRole("button", { name: "Spring 2026" });
    expect(chipLabels()).toEqual(["Spring 2026", "Fall 2025"]);
    expect(mockedGetCourses).not.toHaveBeenCalled();
  });
});
