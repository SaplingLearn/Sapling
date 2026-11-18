// @vitest-environment jsdom
/**
 * Study screen: the hub, and what became of the retired `?mode=` panes.
 *
 * The tabbed Study screen is gone: Study Guide, Flashcards and Quiz have
 * pages of their own. `?mode=guide` / `?mode=cards` survive only as
 * redirects, so a bookmark or an open tab still lands somewhere real.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const replace = vi.fn();
const search = { qs: "" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.qs),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: vi.fn(async () => ({ topics: [] })) }));
vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getGraph: vi.fn(async () => ({ nodes: [], edges: [], stats: {} })),
  getAllAssignments: vi.fn(async () => ({ assignments: [] })),
  saveAssignments: vi.fn(),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  // PKG-12: the learning loop's status probe; off unless a case turns it on.
  getLoopStatus: vi.fn(async () => ({ active: false })),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));
vi.mock("@/lib/quiz/api", () => ({ listAttempts: vi.fn(async () => ({ attempts: [] })) }));
vi.mock("@/lib/studyApi", () => ({
  getStudyDaily: vi.fn(async () => ({ goal_minutes: 30, days: [] })),
  setStudyDailyGoal: vi.fn(),
}));

vi.mock("../learn/DueQueue", () => ({
  DueQueue: ({ userId, courseId }: { userId: string; courseId?: string }) => (
    <div data-testid="review-due-panel">{`${userId}:${courseId ?? "-"}`}</div>
  ),
}));
vi.mock("../learn/RetentionCheck", () => ({
  RetentionCheck: ({ initialCourseId, courses }: { initialCourseId?: string; courses: { course_id: string }[] }) => (
    <div data-testid="retention-panel" data-courses={courses.map(c => c.course_id).join(",")}>{initialCourseId || "-"}</div>
  ),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { getCourses, getLoopStatus, type EnrolledCourse } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";

const renderStudy = () => render(<ToastProvider><Study /></ToastProvider>);

beforeEach(() => {
  search.qs = "";
  replace.mockReset();
  vi.mocked(getLoopStatus).mockReset().mockResolvedValue({ active: false });
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.mocked(getCourses).mockResolvedValue({ courses: [] } as never);
});

describe("Study — the retired ?mode= panes", () => {
  it("sends ?mode=guide to the Study Guides home, with or without a course", async () => {
    search.qs = "mode=guide&course=c1";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/study/guide"));
  });

  it("sends ?mode=cards to the Flashcards page, keeping the course", async () => {
    search.qs = "mode=cards&course=c1";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/flashcards?course=c1"));
  });

  it("redirects a course-less pane link too", async () => {
    search.qs = "mode=cards";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/flashcards"));
  });

  it("paints nothing while redirecting, so the hub never flashes first", () => {
    search.qs = "mode=guide";
    const { container } = renderStudy();
    // ToastProvider's own wrapper is all that's left.
    expect(container.querySelector("h1")).toBeNull();
  });

  it("renders the hub for a bare /study, with no redirect", async () => {
    renderStudy();
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("ignores an unknown mode rather than redirecting somewhere arbitrary", async () => {
    search.qs = "mode=nonsense";
    renderStudy();
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("Study — the learning loop's reviews above the hub (PKG-12)", () => {
  it("renders the due queue (every course) and the retention check when the loop is on", async () => {
    vi.mocked(getLoopStatus).mockResolvedValue({ active: true });
    renderStudy();
    expect((await screen.findByTestId("review-due-panel")).textContent).toBe("u1:-");
    expect(screen.getByTestId("retention-panel")).toBeTruthy();
    expect(getLoopStatus).toHaveBeenCalledWith("u1");
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy(); // the hub stays below
  });

  it("lays both cards out together in one review grid, so they share an edge and a width", async () => {
    vi.mocked(getLoopStatus).mockResolvedValue({ active: true });
    renderStudy();
    const grid = await screen.findByTestId("study-reviews");
    expect(grid).toContainElement(screen.getByTestId("review-due-panel"));
    expect(grid).toContainElement(screen.getByTestId("retention-panel"));
    expect(grid.children).toHaveLength(2);
  });

  it("keeps the hub alone when the loop is off", async () => {
    renderStudy();
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy();
    await waitFor(() => expect(getLoopStatus).toHaveBeenCalled());
    expect(screen.queryByTestId("review-due-panel")).toBeNull();
    expect(screen.queryByTestId("retention-panel")).toBeNull();
  });

  it("offers a retry after a failed status read, keeping the hub", async () => {
    vi.mocked(getLoopStatus).mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ active: true });
    renderStudy();
    fireEvent.click(await screen.findByRole("button", { name: "Retry due reviews" }));
    expect(await screen.findByTestId("review-due-panel")).toBeTruthy();
    expect(getLoopStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "Study" })).toBeTruthy();
  });

  it("opens the retention check on the course a deep link names", async () => {
    vi.mocked(getLoopStatus).mockResolvedValue({ active: true });
    search.qs = "retention-course=c1";
    renderStudy();
    expect((await screen.findByTestId("retention-panel")).textContent).toBe("c1");
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps a retired cards link that names a retention course on the hub", async () => {
    search.qs = "mode=cards&retention-course=c 1";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/study?retention-course=c+1"));
  });
});

describe("Study — the retention deep link keeps its course (F4)", () => {
  const course = (id: string, term: string) =>
    ({ course_id: id, course_code: id.toUpperCase(), course_name: id, term, terms: [term] }) as unknown as EnrolledCourse;

  it("adds the linked course to the retention check's list when the active semester left it out", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2026");
    vi.mocked(getCourses).mockResolvedValue({ courses: [course("c1", "Fall 2026"), course("old", "Spring 2026")] } as never);
    vi.mocked(getLoopStatus).mockResolvedValue({ active: true });
    search.qs = "retention-course=old";
    renderStudy();
    const panel = await screen.findByTestId("retention-panel");
    await waitFor(() => expect(panel.getAttribute("data-courses")).toBe("c1,old"));
    expect(panel.textContent).toBe("old");
  });

  it("adds nothing without a link, or for a course that is not the student's", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2026");
    vi.mocked(getCourses).mockResolvedValue({ courses: [course("c1", "Fall 2026"), course("old", "Spring 2026")] } as never);
    vi.mocked(getLoopStatus).mockResolvedValue({ active: true });
    search.qs = "retention-course=nope";
    renderStudy();
    const panel = await screen.findByTestId("retention-panel");
    await waitFor(() => expect(panel.getAttribute("data-courses")).toBe("c1"));
  });
});
