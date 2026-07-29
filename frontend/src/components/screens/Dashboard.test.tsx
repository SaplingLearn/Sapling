// @vitest-environment jsdom
/**
 * Active-semester scoping of the dashboard course list (#360):
 *   1. The course list is scoped to the active semester, which defaults to the
 *      most-recent enrolled term by `sort_key` (from /api/semesters).
 *   2. A semester previously chosen (persisted in localStorage) scopes both the
 *      panel and the graph fetch to that term.
 *   3. When /api/semesters fails there is no `sort_key` to rank by, so the
 *      default degrades to the term label's derived rank (still Spring 2026),
 *      not a blank or unscoped panel.
 *
 * There is no separate "current vs. archive" split — the semester selector (the
 * ManageCoursesModal term tabs, stubbed here) is the single source of truth.
 * The graph, modals and skeleton are stubbed — this exercises the scoped
 * course list only.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import type { EnrolledCourse, Semester } from "@/lib/api";
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

vi.mock("../KnowledgeGraph", () => ({ KnowledgeGraph: () => null }));
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
  getSemesters: vi.fn(),
}));

import { Dashboard } from "./Dashboard";
import {
  getCourses,
  getGraph,
  getRecommendations,
  getSemesters,
  getSessions,
  getUpcomingAssignments,
} from "@/lib/api";

const mockedGetCourses = vi.mocked(getCourses);
const mockedGetSemesters = vi.mocked(getSemesters);

const SEMESTERS: Semester[] = [
  { id: "spring-2026", term: "Spring", year: 2026, label: "Spring 2026", start_date: "2026-01-05", end_date: "2026-05-17", sort_key: 20261 },
  { id: "fall-2025", term: "Fall", year: 2025, label: "Fall 2025", start_date: "2025-08-25", end_date: "2026-01-04", sort_key: 20253 },
];

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
  mockedGetSemesters.mockResolvedValue({ semesters: SEMESTERS });
  mockedGetCourses.mockResolvedValue({
    // BIO-101 is enrolled first, so enrollment order ranks it before PSY-110;
    // by sort_key, Spring 2026 (20261) still outranks Fall 2025 (20253).
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
  it("defaults to the most-recent term by sort_key and scopes the list to it", async () => {
    render(<Dashboard />);

    // Spring 2026 has the higher sort_key, so it is the default active term.
    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    expect(screen.queryByText("PSY-110")).toBeNull();

    // No current/archive split any more.
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();

    // The default is resolved and persisted BEFORE the scoped fetch, so the
    // graph is fetched exactly once, already scoped — no unscoped first pass.
    expect(getGraph).toHaveBeenCalledTimes(1);
    expect(getGraph).toHaveBeenCalledWith("u1", "Spring 2026");
  });

  it("loads unscoped in a single pass when the user has no courses", async () => {
    mockedGetCourses.mockResolvedValue({ courses: [] });

    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText("No enrolled courses yet.")).toBeInTheDocument());
    // No term to default to → one unscoped fetch, not a resolution pass + refetch.
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

  it("degrades to label-derived ranking when /api/semesters fails", async () => {
    mockedGetSemesters.mockRejectedValue(new Error("500"));

    render(<Dashboard />);

    // No sort_key to rank by, so the default degrades to the label's derived
    // rank — Spring 2026 (20261) still outranks Fall 2025 (20253).
    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    expect(screen.queryByText("PSY-110")).toBeNull();
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();
  });
});
