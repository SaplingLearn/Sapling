// @vitest-environment jsdom
/**
 * Quiz entry-point wiring on the dashboard (#537 C2, contract §6):
 *   - The "Try this next" suggest card resolves `?suggest=<name>` to its node
 *     id (same case-insensitive match `suggestNode` already does) and opens
 *     the quiz on that concept, carrying `{kind:"dashboard", returnTo:"/dashboard"}`.
 *   - Search and review-due shortcuts stay absent in every layout.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";

const push = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: vi.fn(() => false) }));

// Exercise both shell layouts.
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
  fetchActivity: vi.fn(async () => ({ week: [] })),
  fetchGamificationMe: vi.fn(async () => null),
}));

import { Dashboard } from "./Dashboard";
import {
  getCourses,
  getGraph,
  getRecommendations,
  getSessions,
  getUpcomingAssignments,
} from "@/lib/api";
import { useIsMobile } from "@/lib/useIsMobile";

function course(code: string): EnrolledCourse {
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
    term: "Spring 2026",
  };
}

// Raw (pre-apiToGraphNode) node shape, matching `getGraph`'s wire response.
function apiNode(overrides: Record<string, unknown> = {}) {
  return {
    id: "node-recursion",
    concept_name: "Recursion",
    mastery_score: 0.3,
    mastery_tier: "struggling",
    times_studied: 2,
    last_studied_at: "2026-08-01T00:00:00Z",
    subject: "CS-101",
    course_id: "c-CS-101",
    is_subject_root: false,
    ...overrides,
  };
}

beforeEach(() => {
  layoutState.pref = "topnav";
  searchParams = new URLSearchParams();
  window.localStorage.clear();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  vi.mocked(useIsMobile).mockReturnValue(false);
  vi.mocked(getUpcomingAssignments).mockResolvedValue({ assignments: [] });
  vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [] });
  vi.mocked(getCourses).mockResolvedValue({ courses: [course("CS-101")] });
  vi.mocked(getGraph).mockResolvedValue({ nodes: [apiNode()], edges: [], stats: {} });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Dashboard — suggest card entry (?suggest=<name>)", () => {
  it("resolves the concept name to its node id and opens the quiz on that concept", async () => {
    searchParams = new URLSearchParams("suggest=recursion"); // case-insensitive match

    render(<Dashboard />);

    const startQuiz = await screen.findByText("Start quiz");
    fireEvent.click(startQuiz);

    expect(push).toHaveBeenCalledWith(
      "/quiz?concept=node-recursion&from=dashboard&return=%2Fdashboard",
    );
  });
});

describe("Dashboard — simplified actions", () => {
  for (const layout of ["sidebar", "topnav"]) {
    for (const mobile of [false, true]) {
      it(`omits Search and review-due shortcuts in ${layout}, mobile=${mobile}`, async () => {
        layoutState.pref = layout;
        vi.mocked(useIsMobile).mockReturnValue(mobile);
        render(<Dashboard />);
        await screen.findByText(/concepts across/);
        expect(screen.queryByTestId("dashboard-review-due")).toBeNull();
        expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
        expect(screen.queryByRole("button", { name: /Review what's due/ })).toBeNull();
      });
    }
  }
});
