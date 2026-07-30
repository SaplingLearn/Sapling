// @vitest-environment jsdom
/**
 * GradebookCourseScreen ?semester= plumbing (#139).
 *
 * The landing's course cards carry the selected term
 * (`/gradebook/<id>?semester=<label>`) so a course the user took in TWO terms
 * resolves to the right enrollment — without it the backend's
 * `_resolve_enrollment(user, course, None)` picks the CURRENT term and the
 * archived enrollment 404s ("Course not in your gradebook"). This pins the
 * screen half of the fix: the query param must reach getGradebookCourse.
 * Screen rendering concerns live elsewhere; every heavy child is stubbed.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => ({
    show: vi.fn(),
    dismiss: vi.fn(),
    success: vi.fn(),
    error: toastError,
    info: vi.fn(),
    warn: vi.fn(),
  }),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/api", () => ({
  getGradebookCourse: vi.fn(),
  bulkUpdateCategories: vi.fn(),
  deleteCategory: vi.fn(),
  createGradedAssignment: vi.fn(),
  updateGradedAssignment: vi.fn(),
  deleteGradedAssignment: vi.fn(),
  setLetterScale: vi.fn(),
  getGradescopeStatus: vi.fn(),
  listGradescopeLinks: vi.fn(),
  syncGradescopeCourse: vi.fn(),
  setCurveSettings: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/Gradebook/AssignmentList", () => ({ AssignmentList: () => null }));
vi.mock("@/components/Gradebook/GradescopeSyncModal", () => ({ GradescopeSyncModal: () => null }));
vi.mock("@/components/Gradebook/GradePredictorPanel", () => ({ GradePredictorPanel: () => null }));
vi.mock("@/components/Gradebook/AmbientOrbs", () => ({ AmbientOrbs: () => null }));

import { GradebookCourseScreen } from "./Course";
import { getGradebookCourse, getGradescopeStatus } from "@/lib/api";
import type { GradebookCourse } from "@/lib/types";

const mockedGetCourse = vi.mocked(getGradebookCourse);
const mockedGscopeStatus = vi.mocked(getGradescopeStatus);

const COURSE: GradebookCourse = {
  course_id: "c1",
  course_code: "CS101",
  course_name: "Intro to CS",
  semester: "Fall 2025",
  percent: null,
  letter: null,
  letter_scale: null,
  curve_mode: "raw",
  curve_avg_target: null,
  curve_sd_delta: null,
  categories: [],
  assignments: [],
  dropped_assignment_ids: [],
};

beforeEach(() => {
  mockedGetCourse.mockResolvedValue(COURSE);
  mockedGscopeStatus.mockResolvedValue({
    has_credentials: false,
    auth_mode: null,
    last_synced_at: null,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/gradebook/c1");
});

describe("GradebookCourseScreen ?semester= (#139)", () => {
  it("passes the ?semester= label through to getGradebookCourse", async () => {
    window.history.replaceState({}, "", "/gradebook/c1?semester=Fall+2025");

    render(<GradebookCourseScreen courseId="c1" />);

    await waitFor(() =>
      expect(mockedGetCourse).toHaveBeenCalledWith("u1", "c1", "Fall 2025"),
    );
  });

  it("omits the semester when the URL carries none", async () => {
    render(<GradebookCourseScreen courseId="c1" />);

    await waitFor(() =>
      expect(mockedGetCourse).toHaveBeenCalledWith("u1", "c1", undefined),
    );
  });
});
