// @vitest-environment jsdom
/**
 * Semester grouping on the dashboard course list (#140):
 *   1. Current-term courses render; earlier terms don't until Archive opens.
 *   2. An archived course routes into that semester's gradebook.
 *   3. A failed /api/semesters degrades to one flat list, never a blank panel.
 *
 * The graph, modals and skeleton are stubbed — this exercises the course-list
 * partition only.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EnrolledCourse, Semester } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
// "topnav" renders the legacy My Courses panel, which owns the Archive.
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => ["topnav", vi.fn()] }));

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

describe("Dashboard course list by semester", () => {
  it("shows only current-term courses until the archive is opened", async () => {
    render(<Dashboard />);

    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    expect(screen.queryByText("PSY-110")).toBeNull();

    const archive = screen.getByRole("button", { name: /archive/i });
    expect(archive).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(archive);

    expect(await screen.findByText("PSY-110")).toBeInTheDocument();
    expect(panel().getByText("Fall 2025")).toBeInTheDocument();
  });

  it("opens that semester's gradebook when an archived course is picked", async () => {
    render(<Dashboard />);

    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /archive/i }));
    await userEvent.click(
      await screen.findByRole("button", { name: /PSY-110 — open the Fall 2025 gradebook/ }),
    );

    expect(push).toHaveBeenCalledWith("/gradebook?semester=Fall%202025");
  });

  it("falls back to one flat list when /api/semesters fails", async () => {
    mockedGetSemesters.mockRejectedValue(new Error("500"));

    render(<Dashboard />);

    await waitFor(() => expect(panel().getByText("BIO-101")).toBeInTheDocument());
    expect(panel().getByText("PSY-110")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();
  });
});
