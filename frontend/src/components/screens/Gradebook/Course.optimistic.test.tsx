// @vitest-environment jsdom
/**
 * GradebookCourseScreen optimistic-update + request-ordering contract (#770).
 *
 *  - a failed grade save undoes ONLY that assignment's score, never other
 *    edits made while it was in flight (it used to restore a whole-object
 *    snapshot);
 *  - a failed curve-mode toggle is undone AND announced (it used to flip back
 *    silently);
 *  - course reads are latest-wins, and a course change cancels the old read;
 *  - only the typed Gradescope rejection opens the Gradescope dialog — a 401
 *    is Sapling's own session.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Stable, like the real (memoised) ToastProvider value.
const toast = vi.hoisted(() => ({
  show: vi.fn(), dismiss: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));
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
vi.mock("@/components/TopBar", () => ({
  TopBar: ({ actions }: { actions?: React.ReactNode }) => <div>{actions}</div>,
}));
vi.mock("@/components/Gradebook/AssignmentList", () => ({
  AssignmentList: ({ assignments, onEditGrade, onSyncGradescope }: {
    assignments: { id: string; points_earned: number | null }[];
    onEditGrade: (id: string, points: number | null) => void;
    onSyncGradescope: () => void;
  }) => (
    <>
      {assignments.map((a) => (
        <span key={a.id} data-testid={`pts-${a.id}`}>{String(a.points_earned)}</span>
      ))}
      <button type="button" onClick={() => onEditGrade("a1", 5)}>edit a1</button>
      <button type="button" onClick={() => onEditGrade("a2", 7)}>edit a2</button>
      <button type="button" onClick={onSyncGradescope}>Sync Gradescope</button>
    </>
  ),
}));
vi.mock("@/components/Gradebook/GradescopeSyncModal", () => ({
  GradescopeSyncModal: ({ open }: { open: boolean }) => (open ? <div>gradescope dialog</div> : null),
}));
vi.mock("@/components/Gradebook/GradePredictorPanel", () => ({ GradePredictorPanel: () => null }));

import { GradebookCourseScreen } from "./Course";
import {
  getGradebookCourse,
  getGradescopeStatus,
  listGradescopeLinks,
  setCurveSettings,
  syncGradescopeCourse,
  updateGradedAssignment,
} from "@/lib/api";
import type { GradebookCourse, GradedAssignment } from "@/lib/types";

function assignment(id: string, points: number | null, curved = false): GradedAssignment {
  return {
    id, title: id, course_id: "c1", category_id: "cat1", points_possible: 10,
    points_earned: points, due_date: null, assignment_type: null, notes: null,
    source: "manual", curve_class_mean: curved ? 7 : null, curve_class_sd: curved ? 1 : null,
    curve_avg_target: null, curve_sd_delta: null,
  };
}

function course(overrides: Partial<GradebookCourse> = {}): GradebookCourse {
  return {
    course_id: "c1", course_code: "CS101", course_name: "Intro", semester: "Fall 2025",
    percent: null, letter: null, letter_scale: null, curve_mode: "raw",
    curve_avg_target: null, curve_sd_delta: null,
    categories: [{ id: "cat1", name: "Homework", weight: 100, sort_order: 0, drop_lowest: 0 }],
    assignments: [assignment("a1", 1), assignment("a2", 2)],
    dropped_assignment_ids: [],
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.mocked(getGradebookCourse).mockResolvedValue(course());
  vi.mocked(getGradescopeStatus).mockResolvedValue({
    has_credentials: false, auth_mode: null, last_synced_at: null,
  });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.history.replaceState({}, "", "/gradebook/c1");
});

describe("optimistic grade edits", () => {
  it("rolls back only the failed assignment, keeping a concurrent edit", async () => {
    const save1 = deferred<unknown>();
    vi.mocked(updateGradedAssignment)
      .mockImplementationOnce(() => save1.promise as never)
      .mockResolvedValueOnce({} as never);
    const user = userEvent.setup();
    render(<GradebookCourseScreen courseId="c1" />);
    await screen.findByTestId("pts-a1");
    // a2's save succeeds but its follow-up read never answers, so the screen
    // only knows a2=7 from the optimistic write.
    vi.mocked(getGradebookCourse).mockImplementation(() => new Promise(() => {}));

    await user.click(screen.getByRole("button", { name: "edit a1" }));
    await user.click(screen.getByRole("button", { name: "edit a2" }));
    expect(screen.getByTestId("pts-a1")).toHaveTextContent("5");
    expect(screen.getByTestId("pts-a2")).toHaveTextContent("7");

    await act(async () => save1.reject(Object.assign(new Error('{"detail":"Nope."}'), { status: 500 })));
    expect(screen.getByTestId("pts-a1")).toHaveTextContent("1");
    expect(screen.getByTestId("pts-a2")).toHaveTextContent("7");
    expect(toast.error).toHaveBeenCalledWith("Couldn't save: Nope.");
  });

  it("does not let an older course read overwrite a newer one", async () => {
    const stale = deferred<GradebookCourse>();
    const user = userEvent.setup();
    render(<GradebookCourseScreen courseId="c1" />);
    await screen.findByTestId("pts-a1");
    vi.mocked(updateGradedAssignment).mockResolvedValue({} as never);
    vi.mocked(getGradebookCourse)
      .mockImplementationOnce(() => stale.promise)
      .mockResolvedValueOnce(course({ assignments: [assignment("a1", 5), assignment("a2", 7)] }));

    await user.click(screen.getByRole("button", { name: "edit a1" }));
    await user.click(screen.getByRole("button", { name: "edit a2" }));
    await waitFor(() => expect(getGradebookCourse).toHaveBeenCalledTimes(3));
    await act(async () => stale.resolve(course({ assignments: [assignment("a1", 5), assignment("a2", 2)] })));
    expect(screen.getByTestId("pts-a2")).toHaveTextContent("7");
  });

  it("drops a previous course's read after navigating to another course", async () => {
    const c1Read = deferred<GradebookCourse>();
    vi.mocked(getGradebookCourse).mockImplementation((_u, courseId) =>
      courseId === "c1"
        ? c1Read.promise
        : Promise.resolve(course({ course_id: "c2", assignments: [assignment("b1", 9)] })),
    );
    const { rerender } = render(<GradebookCourseScreen courseId="c1" />);
    rerender(<GradebookCourseScreen courseId="c2" />);
    expect(await screen.findByTestId("pts-b1")).toHaveTextContent("9");
    await act(async () => c1Read.resolve(course()));
    expect(screen.queryByTestId("pts-a1")).not.toBeInTheDocument();
    expect(screen.getByTestId("pts-b1")).toBeInTheDocument();
  });
});

describe("curve-mode toggle", () => {
  it("announces a failed toggle and restores the previous mode", async () => {
    vi.mocked(getGradebookCourse).mockResolvedValue(course({
      assignments: [assignment("a1", 8, true)],
    }));
    vi.mocked(setCurveSettings).mockRejectedValue(Object.assign(new Error('{"detail":"Server unavailable."}'), { status: 503 }));
    const user = userEvent.setup();
    render(<GradebookCourseScreen courseId="c1" />);
    await user.click(await screen.findByRole("button", { name: "Curved" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      "Couldn't switch to curved grades: Server unavailable.",
    ));
    // Back on raw: "Curved" is clickable again, "Raw" is the active pill.
    expect(screen.getByRole("button", { name: "Curved" })).toHaveStyle({ cursor: "pointer" });
    expect(screen.getByRole("button", { name: "Raw" })).toHaveStyle({ cursor: "default" });
  });
});

describe("direct Gradescope sync errors", () => {
  async function failDirectSync(err: unknown) {
    window.history.replaceState({}, "", "/gradebook/c1?semester=Fall+2025");
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: true, auth_mode: "cookies", last_synced_at: null, state: "connected",
    });
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [{
      id: "link", sapling_course_id: "c1", gradescope_course_id: "123", last_synced_at: null,
    }] });
    vi.mocked(syncGradescopeCourse).mockRejectedValue(err);
    const user = userEvent.setup();
    render(<GradebookCourseScreen courseId="c1" />);
    await waitFor(() => expect(listGradescopeLinks).toHaveBeenCalled());
    await user.click(await screen.findByRole("button", { name: "Sync Gradescope" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  }

  it("opens the Gradescope dialog for the typed reconnect error", async () => {
    await failDirectSync(Object.assign(new Error('{"detail":"Session expired"}'), {
      status: 409, code: "gradescope_reauth_required",
    }));
    expect(await screen.findByText("gradescope dialog")).toBeInTheDocument();
  });

  it("leaves a Sapling 401 to the session handling", async () => {
    await failDirectSync(Object.assign(new Error('{"detail":"Not authenticated"}'), { status: 401 }));
    expect(screen.queryByText("gradescope dialog")).not.toBeInTheDocument();
  });

  it("does not treat a connection with rejected credentials as one-click ready", async () => {
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: true, auth_mode: "cookies", last_synced_at: null, state: "needs_reauth",
    });
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [{
      id: "link", sapling_course_id: "c1", gradescope_course_id: "123", last_synced_at: null,
    }] });
    const user = userEvent.setup();
    render(<GradebookCourseScreen courseId="c1" />);
    await waitFor(() => expect(getGradescopeStatus).toHaveBeenCalled());
    await user.click(await screen.findByRole("button", { name: "Sync Gradescope" }));
    expect(await screen.findByText("gradescope dialog")).toBeInTheDocument();
    expect(syncGradescopeCourse).not.toHaveBeenCalled();
  });
});
