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

const mockUser = { userId: "u1" as string | null, userReady: true };

vi.mock("@/context/UserContext", () => ({
  useUser: () => mockUser,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(),
  getGradebookSummary: vi.fn(),
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
  CourseCard: ({ course }: any) => <a href="#">{course.course_name}</a>,
  COURSE_CARD_GRID_GAP: 24,
  COURSE_CARD_HEIGHT: 244,
}));

import { GradebookLanding } from "./Landing";
import { getCourses, getGradebookSummary } from "@/lib/api";

const mockedGetCourses = vi.mocked(getCourses);
const mockedGetSummary = vi.mocked(getGradebookSummary);

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

beforeEach(() => {
  mockUser.userId = "u1";
  mockedGetSummary.mockResolvedValue({ courses: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GradebookLanding semester chips", () => {
  it("builds the chips from each course's term", async () => {
    mockedGetCourses.mockResolvedValue({
      courses: [course("bio", "Fall 2024"), course("psy", "Spring 2025"), course("mat", "Fall 2024")],
    });

    render(<GradebookLanding />);

    expect(await screen.findByText("Fall 2024")).toBeInTheDocument();
    expect(screen.getByText("Spring 2025")).toBeInTheDocument();
  });

  it("never falls back to the demo chips for a signed-in user", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [course("bio", "Fall 2024")] });

    render(<GradebookLanding />);

    await screen.findByText("Fall 2024");
    // SAMPLE_SEMESTERS — the logged-out preview. Leaking these into a real
    // account is the bug this file exists for.
    expect(screen.queryByText("Spring 2026")).toBeNull();
    expect(screen.queryByText("Fall 2025")).toBeNull();
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

    expect(await screen.findByText("Spring 2026")).toBeInTheDocument();
    expect(screen.getByText("Fall 2025")).toBeInTheDocument();
    expect(mockedGetCourses).not.toHaveBeenCalled();
  });
});
