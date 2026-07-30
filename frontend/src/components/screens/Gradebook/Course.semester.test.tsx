// @vitest-environment jsdom
/**
 * GradebookCourseScreen ?semester= plumbing (#139/#468).
 *
 * The landing's course cards carry the selected term
 * (`/gradebook/<id>?semester=<label>`) so a course the user took in TWO terms
 * resolves to the right enrollment — without it the backend's
 * `_resolve_enrollment(user, course, None)` picks the CURRENT term and the
 * archived enrollment 404s ("Course not in your gradebook"). This pins the
 * screen half of the fix, READS and WRITES both: the query param must reach
 * getGradebookCourse AND every course-keyed mutation (#468 review — a write
 * that drops the term silently lands on the CURRENT term's enrollment).
 * Screen rendering concerns live elsewhere; heavy children are stubbed,
 * except the real EditWeightsModal/AssignmentModal, whose Save buttons drive
 * the mutation call sites under test.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
// The stub exposes onAdd so the tests can open the REAL AssignmentModal
// without rendering the full list.
vi.mock("@/components/Gradebook/AssignmentList", () => ({
  AssignmentList: ({ onAdd }: { onAdd: () => void }) => (
    <button type="button" data-testid="stub-add-assignment" onClick={onAdd}>
      add
    </button>
  ),
}));
vi.mock("@/components/Gradebook/GradescopeSyncModal", () => ({ GradescopeSyncModal: () => null }));
vi.mock("@/components/Gradebook/GradePredictorPanel", () => ({ GradePredictorPanel: () => null }));
vi.mock("@/components/Gradebook/AmbientOrbs", () => ({ AmbientOrbs: () => null }));

import { GradebookCourseScreen } from "./Course";
import {
  getGradebookCourse,
  getGradescopeStatus,
  bulkUpdateCategories,
  createGradedAssignment,
} from "@/lib/api";
import type { GradebookCourse, GradedAssignment } from "@/lib/types";

const mockedGetCourse = vi.mocked(getGradebookCourse);
const mockedGscopeStatus = vi.mocked(getGradescopeStatus);
const mockedBulkUpdate = vi.mocked(bulkUpdateCategories);
const mockedCreateAssignment = vi.mocked(createGradedAssignment);

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
  // One 100%-weight category so EditWeightsModal's Save validity gate
  // (weights must sum to 100) is already satisfied.
  categories: [{ id: "cat1", name: "Homework", weight: 100, sort_order: 0, drop_lowest: 0 }],
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
  mockedBulkUpdate.mockResolvedValue({ categories: [] });
  mockedCreateAssignment.mockResolvedValue({ assignment: {} as GradedAssignment });
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

// #468 review: mutations must resolve the SAME enrollment the page shows.
// Each helper drives the real modal UI down to its Save click.
async function saveWeightsThroughModal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Edit Weights" }));
  await screen.findByRole("dialog");
  await user.click(screen.getByRole("button", { name: "Save" }));
}

async function createAssignmentThroughModal(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  await user.click(await screen.findByTestId("stub-add-assignment"));
  await screen.findByRole("dialog");
  await user.type(screen.getByTestId("gradebook-assignment-title"), title);
  await user.click(screen.getByTestId("gradebook-assignment-save"));
}

describe("GradebookCourseScreen term-scoped mutations (#468)", () => {
  it("passes the URL's semester to bulkUpdateCategories", async () => {
    window.history.replaceState({}, "", "/gradebook/c1?semester=Fall+2025");
    const user = userEvent.setup();

    render(<GradebookCourseScreen courseId="c1" />);
    await saveWeightsThroughModal(user);

    await waitFor(() =>
      expect(mockedBulkUpdate).toHaveBeenCalledWith(
        "u1",
        "c1",
        expect.any(Array),
        "Fall 2025",
      ),
    );
  });

  it("omits the semester from bulkUpdateCategories when the URL carries none", async () => {
    const user = userEvent.setup();

    render(<GradebookCourseScreen courseId="c1" />);
    await saveWeightsThroughModal(user);

    await waitFor(() =>
      expect(mockedBulkUpdate).toHaveBeenCalledWith(
        "u1",
        "c1",
        expect.any(Array),
        undefined,
      ),
    );
  });

  it("passes the URL's semester to createGradedAssignment", async () => {
    window.history.replaceState({}, "", "/gradebook/c1?semester=Fall+2025");
    const user = userEvent.setup();

    render(<GradebookCourseScreen courseId="c1" />);
    await createAssignmentThroughModal(user, "Essay 1");

    await waitFor(() =>
      expect(mockedCreateAssignment).toHaveBeenCalledWith(
        "u1",
        "c1",
        expect.objectContaining({ title: "Essay 1" }),
        "Fall 2025",
      ),
    );
  });

  it("omits the semester from createGradedAssignment when the URL carries none", async () => {
    const user = userEvent.setup();

    render(<GradebookCourseScreen courseId="c1" />);
    await createAssignmentThroughModal(user, "Essay 1");

    await waitFor(() =>
      expect(mockedCreateAssignment).toHaveBeenCalledWith(
        "u1",
        "c1",
        expect.objectContaining({ title: "Essay 1" }),
        undefined,
      ),
    );
  });
});
