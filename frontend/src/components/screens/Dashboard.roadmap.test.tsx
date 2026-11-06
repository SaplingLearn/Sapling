// @vitest-environment jsdom
/**
 * A course node on the DASHBOARD's graph opens that course's study roadmap
 * (spec §3.14) — the same answer Tree's canvas gives.
 *
 * The regression this pins: the roadmap routing shipped in Tree only, while
 * the dashboard's two graphs kept calling `learnHrefForNode`, which answers
 * for a course node too (a course-scoped tutor session with no topic, #319).
 * So the same node meant "study plan" on /tree and "tutor" on /dashboard, and
 * nothing failed — both destinations are real screens.
 *
 * Asserted through the graph's `onNodeClick` prop rather than a rendered
 * mark: the real canvas is d3/WebGL and its marks move, which is why the E2E
 * journey drives the a11y list instead. The prop IS the contract between the
 * screen and whichever renderer draws it.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import type { GraphNode } from "@/lib/data";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => ["topnav", vi.fn()] }));

// Capture the click handler the dashboard hands its graph.
const graphState = vi.hoisted(() => ({
  onNodeClick: null as ((n: GraphNode) => void) | null,
}));
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: (props: { onNodeClick?: (n: GraphNode) => void }) => {
    graphState.onNodeClick = props.onNodeClick ?? null;
    return null;
  },
}));
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

function node(over: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1",
    name: "Eigenvalues",
    subject: "Linear Algebra",
    color: "#7a874f",
    is_subject_root: false,
    mastery_tier: "learning",
    mastery_score: 0.5,
    course_id: "c-MATH210",
    ...over,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  graphState.onNodeClick = null;

  vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [], stats: {} });
  vi.mocked(getUpcomingAssignments).mockResolvedValue({ assignments: [] });
  vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [] });
  vi.mocked(getCourses).mockResolvedValue({ courses: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function clickHandler(): Promise<(n: GraphNode) => void> {
  render(<Dashboard />);
  await waitFor(() => expect(graphState.onNodeClick).not.toBeNull());
  return graphState.onNodeClick!;
}

describe("Dashboard graph — activating a node", () => {
  it("sends a course node to its study roadmap, not the tutor", async () => {
    (await clickHandler())(
      node({ id: "subject_root__c-MATH210", name: "Linear Algebra", is_subject_root: true }),
    );

    expect(push).toHaveBeenCalledWith("/roadmap/c-MATH210");
  });

  it("still sends a concept node to the tutor, seeded with its name", async () => {
    (await clickHandler())(node({ name: "Eigenvalues" }));

    expect(push).toHaveBeenCalledTimes(1);
    const href = push.mock.calls[0][0] as string;
    expect(href.startsWith("/learn?")).toBe(true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("topic")).toBe("Eigenvalues");
    expect(params.get("course")).toBe("c-MATH210");
  });
});
