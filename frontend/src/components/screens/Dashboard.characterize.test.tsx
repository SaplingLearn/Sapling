// @vitest-environment jsdom
/**
 * Characterization of the dashboard's load + render behaviour, pinned before
 * the complexity split: what load() puts on screen (stats, graph header,
 * week streak, upcoming chips, Learn next), the error/Retry and loading
 * branches, the streak extras refresh, the legacy course chips <-> graph
 * zoom wiring, the mobile tabs, fullscreen, and the suggest dismiss.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within, fireEvent, act } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";

const push = vi.fn();
const replace = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada Lovelace" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: vi.fn(() => false) }));
const layoutState = vi.hoisted(() => ({ pref: "topnav" }));
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => [layoutState.pref, vi.fn()] }));

type KGProps = Record<string, unknown> & { onNodeClick?: (n: unknown) => void };
const kg = vi.hoisted(() => ({ renders: [] as KGProps[] }));
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: (p: KGProps) => {
    kg.renders.push(p);
    return null;
  },
}));
type ModalProps = { open: boolean; onClose: () => void; onChanged: () => void };
const modal = vi.hoisted(() => ({ last: null as ModalProps | null }));
vi.mock("../ManageCoursesModal", () => ({
  ManageCoursesModal: (p: ModalProps) => {
    modal.last = p;
    return p.open ? <div data-testid="stub-courses-modal" /> : null;
  },
}));
vi.mock("../Skeleton", () => ({ DashboardSkeleton: () => <div data-testid="stub-skeleton" /> }));
vi.mock("../MiniStat", () => ({
  MiniStat: ({ label, value, sub }: { label: string; value: number; sub?: string }) => (
    <div data-testid={`stub-ministat-${label}`}>{`${value}|${sub ?? ""}`}</div>
  ),
}));
vi.mock("../Icon", () => ({ Icon: () => null }));

vi.mock("@/lib/api", () => ({
  getGraph: vi.fn(),
  getCourses: vi.fn(),
  getUpcomingAssignments: vi.fn(),
  getSessions: vi.fn(),
  getRecommendations: vi.fn(),
  fetchActivity: vi.fn(),
  fetchGamificationMe: vi.fn(),
}));

import { Dashboard } from "./Dashboard";
import {
  fetchActivity,
  fetchGamificationMe,
  getCourses,
  getGraph,
  getRecommendations,
  getSessions,
  getUpcomingAssignments,
} from "@/lib/api";
import { useIsMobile } from "@/lib/useIsMobile";

// Wed 4 Mar 2026, 12:00 local.
const NOW = new Date(2026, 2, 4, 12, 0, 0);

function course(code: string, color: string | null = null): EnrolledCourse {
  return {
    enrollment_id: `e-${code}`,
    course_id: `c-${code}`,
    course_code: code,
    course_name: code,
    school: "BU",
    department: "CS",
    color,
    nickname: null,
    node_count: 0,
    enrolled_at: "2025-08-25",
    term: "Spring 2026",
  };
}

function apiNode(id: string, name: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    concept_name: name,
    mastery_score: 0.3,
    mastery_tier: "learning",
    times_studied: 2,
    last_studied_at: null,
    subject: "CS-101",
    course_id: "c-CS-101",
    is_subject_root: false,
    ...overrides,
  };
}

const graphResult = (overrides: Record<string, unknown> = {}) => ({
  nodes: [apiNode("n1", "Recursion"), apiNode("n2", "Loops"), apiNode("root", "CS-101", { is_subject_root: true })],
  edges: [{ source: "n1", target: "n2", strength: 0.5, relationship_type: "prereq", extra: "dropped" }],
  stats: {},
  ...overrides,
});

const mainGraph = () => [...kg.renders].reverse().find((p) => "onHoverCourse" in p)!;
const fullscreenGraph = () => [...kg.renders].reverse().find((p) => !("onHoverCourse" in p))!;

beforeEach(() => {
  layoutState.pref = "topnav";
  searchParams = new URLSearchParams();
  kg.renders = [];
  modal.last = null;
  window.localStorage.clear();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(NOW);

  vi.mocked(useIsMobile).mockReturnValue(false);
  vi.mocked(getGraph).mockResolvedValue(graphResult() as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [course("CS-101", "#123456"), course("MA-201")] });
  vi.mocked(getUpcomingAssignments).mockResolvedValue({ assignments: [] });
  vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [] });
  vi.mocked(fetchActivity).mockResolvedValue({ week: [] } as never);
  vi.mocked(fetchGamificationMe).mockResolvedValue(null as never);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("Dashboard load → screen", () => {
  it("falls back to the non-root node count when stats.total_nodes is absent", async () => {
    render(<Dashboard />);
    expect(await screen.findByText("2 concepts across 2 courses")).toBeInTheDocument();
  });

  it("maps graph stats into the header, the streak copy and the mini stats", async () => {
    vi.mocked(getGraph).mockResolvedValue(graphResult({
      stats: { streak: 3, mastered: 4, total_nodes: 9, learning: 2, struggling: 1, unexplored: 2 },
    }) as never);
    render(<Dashboard />);
    expect(await screen.findByText("9 concepts across 2 courses")).toBeInTheDocument();
    expect(screen.getByText("3-day").parentElement).toHaveTextContent("You're on a 3-day streak.");
    expect(screen.getByTestId("stub-ministat-Mastered")).toHaveTextContent("4|of 9 concepts");
    expect(screen.getByTestId("stub-ministat-Learning")).toHaveTextContent("3|2 unexplored");
  });

  it("with no streak and no total, shows the begin-a-streak copy and no Mastered sub", async () => {
    render(<Dashboard />);
    expect(await screen.findByText("Ready when you are. Open any session to begin a streak.")).toBeInTheDocument();
    expect(screen.getByTestId("stub-ministat-Mastered")).toHaveTextContent(/^0\|$/);
    expect(screen.getByTestId("stub-ministat-Learning")).toHaveTextContent("0|0 unexplored");
  });

  it("maps nodes with the enrolled courses and strips edges to the graph's fields", async () => {
    render(<Dashboard />);
    await screen.findByText(/concepts across/);
    const g = mainGraph();
    const nodes = g.nodes as { id: string; color: string; course_id: string }[];
    expect(nodes.map((n) => n.id)).toEqual(["n1", "n2", "root"]);
    // apiToGraphNode resolved the course colour off the enrolled list.
    expect(nodes[0].color).toBe("#123456");
    expect(g.edges).toEqual([{ source: "n1", target: "n2", strength: 0.5, relationship_type: "prereq" }]);
  });

  it("marks the week from the nodes' last-studied dates", async () => {
    const monday = new Date(2026, 2, 2);
    vi.mocked(getGraph).mockResolvedValue(graphResult({
      nodes: [
        apiNode("n1", "Recursion", { last_studied_at: monday.toISOString() }),
        apiNode("n2", "Loops", { last_studied_at: "not a date" }),
      ],
    }) as never);
    render(<Dashboard />);
    await screen.findByText(/concepts across/);
    const week = screen.getByText("This week").closest(".card") as HTMLElement;
    const marks = within(week).getAllByLabelText(/completed|today|missed|upcoming/).map((el) => el.getAttribute("aria-label"));
    expect(marks).toEqual(["completed", "missed", "today", "upcoming", "upcoming", "upcoming", "upcoming"]);
  });

  it("shows the four nearest upcoming items with their urgency chips", async () => {
    const at = (h: number) => new Date(NOW.getTime() + h * 3600_000).toISOString();
    vi.mocked(getUpcomingAssignments).mockResolvedValue({
      assignments: [
        { id: "a1", user_id: "u1", title: "Overdue PS", due_date: at(-1), course_name: "CS-101", assignment_type: "homework" },
        { id: "a2", user_id: "u1", title: "Now PS", due_date: at(0.5) },
        { id: "a3", user_id: "u1", title: "Soon PS", due_date: at(5) },
        { id: "a4", user_id: "u1", title: "Two days", due_date: at(40) },
        { id: "a5", user_id: "u1", title: "Fifth", due_date: at(200) },
      ],
    } as never);
    render(<Dashboard />);
    const row = async (title: string) => (await screen.findByText(title)).parentElement!.parentElement as HTMLElement;
    const chip = async (title: string) => (await row(title)).querySelector(".chip") as HTMLElement;

    expect(await chip("Overdue PS")).toHaveTextContent("OVERDUE");
    expect(await chip("Overdue PS")).toHaveClass("chip", "chip--err");
    expect((await row("Overdue PS"))).toHaveTextContent("CS-101 · homework");
    expect(await chip("Now PS")).toHaveTextContent("NOW");
    expect(await chip("Now PS")).toHaveClass("chip--err");
    expect((await row("Now PS"))).toHaveTextContent("— · task");
    expect(await chip("Soon PS")).toHaveTextContent("5H");
    expect(await chip("Soon PS")).toHaveClass("chip--err");
    expect(await chip("Two days")).toHaveTextContent("2D");
    expect(await chip("Two days")).toHaveClass("chip--warn");
    expect(screen.queryByText("Fifth")).toBeNull();
  });

  it("an info chip for an item more than two days out", async () => {
    vi.mocked(getUpcomingAssignments).mockResolvedValue({
      assignments: [{ id: "a1", user_id: "u1", title: "Later", due_date: new Date(NOW.getTime() + 100 * 3600_000).toISOString() }],
    } as never);
    render(<Dashboard />);
    const chip = (await screen.findByText("Later")).parentElement!.parentElement!.querySelector(".chip") as HTMLElement;
    expect(chip).toHaveTextContent("5D");
    expect(chip).toHaveClass("chip--info");
  });

  it("shows up to three Learn next recommendations and opens the tutor on one", async () => {
    vi.mocked(getRecommendations).mockResolvedValue({
      recommendations: [
        { concept_name: "Graphs & Trees", reason: "builds on Recursion" },
        { concept_name: "Heaps" },
        { concept_name: "Tries" },
        { concept_name: "Fourth" },
      ],
    });
    render(<Dashboard />);
    expect(await screen.findByText("builds on Recursion")).toBeInTheDocument();
    expect(screen.getByText("Heaps")).toBeInTheDocument();
    expect(screen.getByText("Tries")).toBeInTheDocument();
    expect(screen.queryByText("Fourth")).toBeNull();
    fireEvent.click(screen.getByText("Graphs & Trees"));
    expect(push).toHaveBeenCalledWith("/learn?topic=Graphs%20%26%20Trees&mode=socratic");
  });

  it("a failed recommendations fetch is swallowed: the rest of the dashboard renders", async () => {
    vi.mocked(getRecommendations).mockRejectedValue(new Error("recs down"));
    render(<Dashboard />);
    expect(await screen.findByText("Nothing suggested yet — start a session.")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load dashboard")).toBeNull();
  });
});

describe("Dashboard loading + error branches", () => {
  it("shows the skeleton while the first load is out", async () => {
    vi.mocked(getGraph).mockReturnValue(new Promise(() => {}) as never);
    render(<Dashboard />);
    expect(await screen.findByTestId("stub-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("My courses")).toBeNull();
  });

  it("a failed load shows the error with Retry, and Retry reloads", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(getGraph).mockRejectedValueOnce(new Error("boom"));
    render(<Dashboard />);
    expect(await screen.findByText("Couldn't load dashboard")).toBeInTheDocument();
    expect(screen.getByText("Error: boom")).toBeInTheDocument();
    expect(err).toHaveBeenCalledWith("dashboard load failed", expect.any(Error));

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("My courses")).toBeInTheDocument();
    expect(getGraph).toHaveBeenCalledTimes(2);
    err.mockRestore();
  });

  it("a failed reload keeps the loaded dashboard on screen", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<Dashboard />);
    await screen.findByText("My courses");
    vi.mocked(getGraph).mockRejectedValueOnce(new Error("later"));
    await act(async () => { modal.last!.onChanged(); });
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(2));
    expect(screen.getByText("My courses")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load dashboard")).toBeNull();
    err.mockRestore();
  });
});

describe("Dashboard streak extras", () => {
  it("fetches the extras with every load and shows the best streak (sidebar)", async () => {
    layoutState.pref = "sidebar";
    vi.mocked(fetchGamificationMe).mockResolvedValue({ longest_streak: 7 } as never);
    render(<Dashboard />);
    const streak = await screen.findByTestId("dashboard-streak");
    await waitFor(() => expect(within(streak).getByText("best 7")).toBeInTheDocument());
    // Once on mount, once more for load()'s extrasKey bump.
    expect(fetchActivity).toHaveBeenCalledTimes(2);
    expect(fetchActivity).toHaveBeenCalledWith("u1");
    expect(fetchGamificationMe).toHaveBeenCalledTimes(2);
    // Fired before the dashboard fetches.
    expect(vi.mocked(fetchActivity).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(getGraph).mock.invocationCallOrder[0],
    );

    await act(async () => { modal.last!.onChanged(); });
    await waitFor(() => expect(fetchActivity).toHaveBeenCalledTimes(3));
    expect(getGraph).toHaveBeenCalledTimes(2);
  });

  it("extras failures are swallowed", async () => {
    layoutState.pref = "sidebar";
    vi.mocked(fetchActivity).mockRejectedValue(new Error("x"));
    vi.mocked(fetchGamificationMe).mockRejectedValue(new Error("y"));
    render(<Dashboard />);
    const streak = await screen.findByTestId("dashboard-streak");
    expect(within(streak).queryByText(/^best/)).toBeNull();
  });
});

describe("Dashboard legacy (topnav) wiring", () => {
  it("course chips zoom the graph and toggle back out", async () => {
    vi.mocked(getCourses).mockResolvedValue({
      courses: ["A", "B", "C", "D", "E", "F"].map((c) => course(c)),
    });
    render(<Dashboard />);
    await screen.findByText(/concepts across 6 courses/);
    const chips = screen.getAllByTestId("dashboard-graph-course-chip");
    expect(chips.map((c) => c.getAttribute("data-course-id"))).toEqual(["c-A", "c-B", "c-C", "c-D", "c-E"]);
    expect(chips[1]).toHaveAttribute("aria-pressed", "false");
    expect(chips[1]).toHaveAttribute("title", "Click to zoom to this course");

    fireEvent.click(chips[1]);
    expect(chips[1]).toHaveAttribute("aria-pressed", "true");
    expect(chips[1]).toHaveAttribute("title", "Click to zoom back out");
    expect(mainGraph().zoomRequest).toEqual({ courseId: "c-B", seq: 1 });
    expect(mainGraph().focusCourseId).toBe("c-B");

    fireEvent.pointerEnter(chips[2]);
    expect(mainGraph().focusCourseId).toBe("c-C");
    expect(chips[2]).toHaveStyle({ fontWeight: "600" });
    fireEvent.pointerLeave(chips[2]);
    expect(mainGraph().focusCourseId).toBe("c-B");

    fireEvent.click(chips[1]);
    expect(chips[1]).toHaveAttribute("aria-pressed", "false");
    expect(mainGraph().zoomRequest).toEqual({ courseId: null, seq: 2 });
    expect(mainGraph().focusCourseId).toBeNull();
  });

  it("panel buttons route and open the Courses & Semesters hub", async () => {
    render(<Dashboard />);
    await screen.findByText("My courses");
    fireEvent.click(screen.getByText("Calendar →"));
    expect(push).toHaveBeenLastCalledWith("/calendar");
    fireEvent.click(screen.getByText("Tree →"));
    expect(push).toHaveBeenLastCalledWith("/tree");
    fireEvent.click(screen.getByText("Study room"));
    expect(push).toHaveBeenLastCalledWith("/social");
    fireEvent.click(screen.getByText("Start learning"));
    expect(push).toHaveBeenLastCalledWith("/learn");
    expect(screen.queryByTestId("stub-courses-modal")).toBeNull();
    fireEvent.click(screen.getByText("Courses & Semesters"));
    expect(screen.getByTestId("stub-courses-modal")).toBeInTheDocument();
    act(() => modal.last!.onClose());
    expect(screen.queryByTestId("stub-courses-modal")).toBeNull();
  });

  it("node clicks open the tutor on the node", async () => {
    render(<Dashboard />);
    await screen.findByText(/concepts across/);
    act(() => mainGraph().onNodeClick!(((mainGraph().nodes as unknown[])[0])));
    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0][0]).toMatch(/^\/learn/);
  });

  it("mobile shows tabs: My Courses by default, Stats & More swaps the side panel", async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(<Dashboard />);
    await screen.findByText("My courses");
    expect(screen.queryByText("This week")).toBeNull();
    fireEvent.click(screen.getByText("Stats & More"));
    expect(screen.getByText("This week")).toBeInTheDocument();
    expect(screen.queryByText("My courses")).toBeNull();
    // Mobile: the hero row carries Start learning, the right panel does not.
    expect(screen.getAllByText("Start learning")).toHaveLength(1);
    fireEvent.click(screen.getByText("My Courses"));
    expect(screen.getByText("My courses")).toBeInTheDocument();
  });

  it("mobile: a tab switch reuses the side panel's root node (patched, not remounted)", async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(<Dashboard />);
    const coursesCard = (await screen.findByText("My courses")).closest(".card") as HTMLElement;
    const grid = screen.getByRole("heading", { level: 1 }).parentElement!.parentElement!.parentElement as HTMLElement;
    const slot1 = grid.children[1];
    expect(slot1.contains(coursesCard)).toBe(true);
    fireEvent.click(screen.getByText("Stats & More"));
    expect(grid.children[1]).toBe(slot1);
    expect(slot1.contains(screen.getByText("This week"))).toBe(true);
  });

  it("mobile: a layout flip (topnav ↔ sidebar) keeps the main column mounted", async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    const { rerender } = render(<Dashboard />);
    await screen.findByText("My courses");
    const h1 = screen.getByRole("heading", { level: 1 });
    const main = h1.parentElement!.parentElement as HTMLElement;
    const grid = main.parentElement as HTMLElement;

    // Another tab writes the layout pref (storage event → useLayoutPref).
    layoutState.pref = "sidebar";
    rerender(<Dashboard />);
    expect(await screen.findByTestId("dashboard-today-column")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBe(h1);
    expect(h1.parentElement!.parentElement).toBe(main);
    expect(main.parentElement).toBe(grid);

    layoutState.pref = "topnav";
    rerender(<Dashboard />);
    expect(await screen.findByText("My courses")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBe(h1);
    expect(main.parentElement).toBe(grid);
  });

  it("desktop renders the three columns in order: courses, main, right", async () => {
    render(<Dashboard />);
    const courses = await screen.findByText("My courses");
    const hero = screen.getByRole("heading", { level: 1 });
    const week = screen.getByText("This week");
    expect(courses.compareDocumentPosition(hero) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(hero.compareDocumentPosition(week) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Stats & More")).toBeNull();
  });
});

describe("Dashboard sidebar layout", () => {
  it("desktop: greeting row actions + today column + courses key", async () => {
    layoutState.pref = "sidebar";
    render(<Dashboard />);
    expect(await screen.findByTestId("dashboard-today-column")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-action-start")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-courses-key")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-graph-course-chip")).toBeNull();
    expect(screen.queryByText("My courses")).toBeNull();
  });

  it("mobile: Start learning button in the main column, no greeting-row actions", async () => {
    layoutState.pref = "sidebar";
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(<Dashboard />);
    await screen.findByTestId("dashboard-today-column");
    expect(screen.queryByTestId("dashboard-action-start")).toBeNull();
    fireEvent.click(screen.getByText("Start learning"));
    expect(push).toHaveBeenCalledWith("/learn");
    expect(screen.queryByText("Stats & More")).toBeNull();
  });
});

describe("Dashboard fullscreen graph", () => {
  it("opens, closes on Escape and on the close button, and routes a node click", async () => {
    render(<Dashboard />);
    await screen.findByText(/concepts across/);
    fireEvent.click(screen.getByRole("button", { name: "Fullscreen graph" }));
    expect(screen.getByText("Press Esc to exit")).toBeInTheDocument();
    expect(fullscreenGraph().width).toBe(1200);

    fireEvent.keyDown(document, { key: "Enter" });
    expect(screen.getByText("Press Esc to exit")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Press Esc to exit")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Fullscreen graph" }));
    const header = screen.getByText("Press Esc to exit").parentElement!.parentElement as HTMLElement;
    fireEvent.click(within(header).getByRole("button"));
    expect(screen.queryByText("Press Esc to exit")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Fullscreen graph" }));
    act(() => fullscreenGraph().onNodeClick!((fullscreenGraph().nodes as unknown[])[0]));
    expect(screen.queryByText("Press Esc to exit")).toBeNull();
    expect(push.mock.calls.at(-1)![0]).toMatch(/^\/learn/);
  });
});

describe("Dashboard suggest card", () => {
  it("dismiss hides the card and drops only ?suggest from the URL", async () => {
    searchParams = new URLSearchParams("suggest=Recursion&tab=x");
    render(<Dashboard />);
    expect(await screen.findByText("Try this next:")).toBeInTheDocument();
    expect(mainGraph().highlightId).toBe("n1");
    fireEvent.click(screen.getByText("Dismiss"));
    expect(screen.queryByText("Try this next:")).toBeNull();
    expect(replace).toHaveBeenCalledWith("/dashboard?tab=x");
  });

  it("dismiss with no other params returns to the bare dashboard", async () => {
    searchParams = new URLSearchParams("suggest=Recursion");
    render(<Dashboard />);
    fireEvent.click(await screen.findByText("Dismiss"));
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it("an unknown suggestion renders no card", async () => {
    searchParams = new URLSearchParams("suggest=Nope");
    render(<Dashboard />);
    await screen.findByText(/concepts across/);
    expect(screen.queryByText("Try this next:")).toBeNull();
    expect(mainGraph().highlightId).toBeUndefined();
  });
});
