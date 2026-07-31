// @vitest-environment jsdom
/**
 * Active-semester scoping of the dashboard course list (#360):
 *   1. DEFAULT = ALL SEMESTERS: with nothing stored, every enrolled course is
 *      visible and the graph is fetched unscoped, exactly once — nothing
 *      auto-resolves a default term (the e2e lane vetoed that: an auto-picked
 *      term hid cross-term fixtures).
 *   2. A semester previously chosen in the Courses & Semesters hub (persisted
 *      in localStorage) scopes both the panel and the graph fetch to that term.
 *   3. A picked term that scopes to zero courses keeps the CoursesKey mounted
 *      so its "Nothing enrolled this semester." empty state is reachable.
 *
 * There is no separate "current vs. archive" split — the semester selector (the
 * ManageCoursesModal term tabs, stubbed here) is the single source of truth.
 * The graph, modals and skeleton are stubbed — this exercises the scoped
 * course list only.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
// "topnav" renders the legacy My Courses panel, the easiest surface to assert
// on; the CoursesKey empty-state test flips this to "sidebar".
const layoutState = vi.hoisted(() => ({ pref: "topnav" }));
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => [layoutState.pref, vi.fn()] }));

vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => null }));
vi.mock("../ManageCoursesModal", () => ({ ManageCoursesModal: () => null }));
vi.mock("../Skeleton", () => ({ DashboardSkeleton: () => null }));
vi.mock("../MiniStat", () => ({ MiniStat: () => null }));
vi.mock("../Icon", () => ({ Icon: () => null }));

vi.mock("@/lib/api", () => ({
  getGraph: vi.fn(),
  getCourses: vi.fn(),
  getUpcomingAssignments: vi.fn(),
  getSessions: vi.fn(),
  getRecommendations: vi.fn(),
}));

import { Dashboard } from "./Dashboard";
import {
  getCourses,
  getGraph,
  getRecommendations,
  getSessions,
  getUpcomingAssignments,
} from "@/lib/api";

const mockedGetCourses = vi.mocked(getCourses);

function course(code: string, term: string): EnrolledCourse {
  return {
    enrollment_id: `e-${code}`,
    course_id: `c-${code}`,
    course_code: code,
    course_name: code,
    school: "BU",
    department: "CS",
    color: null,
    nickname: null,
    node_count: 0,
    enrolled_at: "2025-08-25",
    term,
  };
}

beforeEach(() => {
  layoutState.pref = "topnav";
  window.localStorage.clear();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(2026, 2, 1));

  vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [], stats: {} });
  vi.mocked(getUpcomingAssignments).mockResolvedValue({ assignments: [] });
  vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [] });
  mockedGetCourses.mockResolvedValue({
    courses: [course("BIO-101", "Spring 2026"), course("PSY-110", "Fall 2025")],
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

// The "My courses" card. Course codes also appear in the graph legend, so
// panel assertions have to be scoped.
const panel = () => within(screen.getByText("My courses").closest(".card") as HTMLElement);

describe("Dashboard course list by active semester", () => {
  it("defaults to All semesters: every course visible, one unscoped fetch", async () => {
    render(<Dashboard />);

    // Nothing stored → All semesters: BOTH terms' courses render.
    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    expect(panel().getByText("PSY-110")).toBeInTheDocument();

    // No current/archive split any more.
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();

    // No auto-default resolution: exactly one fetch, unscoped — never an
    // unscoped-then-scoped double, never a silently picked term.
    expect(getGraph).toHaveBeenCalledTimes(1);
    expect(getGraph).toHaveBeenCalledWith("u1", undefined);
  });

  it("loads unscoped in a single pass when the user has no courses", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [] });

    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText("No enrolled courses yet.")).toBeInTheDocument());
    expect(getGraph).toHaveBeenCalledTimes(1);
    expect(getGraph).toHaveBeenCalledWith("u1", undefined);
  });

  it("scopes the list and the graph fetch to a semester chosen from storage", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");

    render(<Dashboard />);

    await waitFor(() => expect(panel().getByText("PSY-110")).toBeInTheDocument());
    expect(screen.queryByText("BIO-101")).toBeNull();
    // The graph is fetched scoped to the stored term, no unscoped first pass.
    expect(getGraph).toHaveBeenCalledWith("u1", "Fall 2025");
    expect(getGraph).not.toHaveBeenCalledWith("u1", undefined);
  });

  it("shows the courses-key empty state when the active semester has no courses", async () => {
    // Sidebar layout renders the CoursesKey overlay instead of the legacy panel.
    layoutState.pref = "sidebar";
    // A stored semester none of the enrolled courses belong to → courseProgress
    // is empty, but courses exist, so the key must render its empty state
    // rather than disappearing entirely.
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Summer 2026");

    render(<Dashboard />);

    const toggle = await screen.findByTestId("dashboard-courses-key-toggle");
    fireEvent.click(toggle);
    expect(screen.getByText("Nothing enrolled this semester.")).toBeInTheDocument();
  });
});
