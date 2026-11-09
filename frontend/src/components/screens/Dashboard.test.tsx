// @vitest-environment jsdom
/**
 * Home (Sapling Home v2) wiring:
 *   - semester scoping of the graph fetch and the course dropdown (#360);
 *   - every card is derived from real data: pills, Up Next, Quick Reviews,
 *     Last Session, Roadmap, Recent Notes, Coming Up, level and streak;
 *   - the greeting types itself out, then a rotating quote fades in;
 *   - the original knowledge graph card (KnowledgeGraph + CoursesKey) and
 *     the latest-load-wins race (#769).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within, act, fireEvent } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
import { QUOTES } from "../home/homeModel";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const userState = vi.hoisted(() => ({ name: "Ada Lovelace" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: userState.name }),
}));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));

const navState = vi.hoisted(() => ({ hidden: [] as string[] }));
vi.mock("@/lib/useNavSections", () => ({
  useVisibleNavSections: () => [{
    label: "All",
    items: ["/learn", "/study", "/calendar", "/notetaker"].filter((h) => !navState.hidden.includes(h)).map((href) => ({ href, label: href, icon: "x" })),
  }],
}));
// The original force graph needs a real canvas; its own tests cover it.
vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => <div data-testid="knowledge-graph" /> }));
vi.mock("../ManageCoursesModal", () => ({
  ManageCoursesModal: ({ open }: { open: boolean }) => (open ? <div data-testid="manage-courses-modal" /> : null),
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
  getFlashcards: vi.fn(),
  listNotes: vi.fn(),
}));

import { Dashboard } from "./Dashboard";
import {
  fetchActivity, fetchGamificationMe, getCourses, getFlashcards, getGraph, getRecommendations,
  getSessions, getUpcomingAssignments, listNotes,
} from "@/lib/api";

function course(code: string, term: string, name = code): EnrolledCourse {
  return {
    enrollment_id: `e-${code}`, course_id: `c-${code}`, course_code: code, course_name: name, school: "BU",
    department: "CS", color: "#C06020", nickname: null, node_count: 0, enrolled_at: "2025-08-25", term,
  };
}

function node(id: string, name: string, tier: string, score: number, extra: Record<string, unknown> = {}) {
  return {
    id, concept_name: name, mastery_tier: tier, mastery_score: score, subject: "Linear Algebra",
    course_id: "c-MATH210", is_subject_root: false, ...extra,
  };
}

// Vectors (mastered) -> Determinants (learning) -> Eigenvalues (not started).
const GRAPH = {
  nodes: [
    node("vec", "Vectors", "mastered", 0.95, { last_studied_at: "2026-02-27T12:00:00Z" }),
    node("det", "Determinants", "learning", 0.6),
    node("eig", "Eigenvalues", "unexplored", 0),
  ],
  edges: [
    { source: "vec", target: "det", strength: 1, relationship_type: "prerequisite" },
    { source: "det", target: "eig", strength: 1, relationship_type: "prerequisite" },
  ],
  stats: { streak: 4 },
};

beforeEach(() => {
  userState.name = "Ada Lovelace";
  navState.hidden = [];
  window.localStorage.clear();
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(2026, 2, 1, 9, 0, 0)); // Sunday 1 Mar 2026, morning

  vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [], stats: {} });
  vi.mocked(getUpcomingAssignments).mockResolvedValue({ assignments: [] });
  vi.mocked(getSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(getRecommendations).mockResolvedValue({ recommendations: [] });
  vi.mocked(getCourses).mockResolvedValue({
    courses: [course("BIO-101", "Spring 2026"), course("PSY-110", "Fall 2025")],
  });
  vi.mocked(fetchActivity).mockResolvedValue({ week: [], trend: [], daily_goal_xp: 0, tiles: { week_total: 0, daily_avg: 0, best_day: 0, best_day_label: "", streak: 0 } });
  vi.mocked(fetchGamificationMe).mockRejectedValue(new Error("nope"));
  vi.mocked(getFlashcards).mockResolvedValue({ flashcards: [] });
  vi.mocked(listNotes).mockResolvedValue({ notes: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

// Course codes in the original "My courses" key overlaid on the graph.
const keyCodes = async () => {
  const key = await screen.findByTestId("dashboard-courses-key");
  return within(key).getAllByTestId("dashboard-course-code").map((el) => el.textContent?.trim());
};

describe("Home: semester scoping", () => {
  it("defaults to All semesters: every course keyed, one unscoped fetch", async () => {
    render(<Dashboard />);
    await waitFor(async () => expect(await keyCodes()).toEqual(expect.arrayContaining(["BIO-101", "PSY-110"])));
    expect(getGraph).toHaveBeenCalledTimes(1);
    expect(getGraph).toHaveBeenCalledWith("u1", undefined);
  });

  it("scopes the course key and the graph fetch to a stored semester", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    render(<Dashboard />);
    await waitFor(async () => expect(await keyCodes()).toEqual(["PSY-110"]));
    expect(getGraph).toHaveBeenCalledWith("u1", "Fall 2025");
    expect(getGraph).not.toHaveBeenCalledWith("u1", undefined);
    expect(getFlashcards).toHaveBeenCalledWith("u1", undefined, "Fall 2025");
  });

  it("opens the Courses & Semesters hub from the graph card", async () => {
    render(<Dashboard />);
    fireEvent.click(await screen.findByTestId("dashboard-courses-manage"));
    expect(screen.getByTestId("manage-courses-modal")).toBeInTheDocument();
  });

  it("keeps the course key away when there are no courses", async () => {
    vi.mocked(getCourses).mockResolvedValue({ courses: [] });
    render(<Dashboard />);
    await screen.findByTestId("knowledge-graph");
    expect(screen.queryByTestId("dashboard-courses-key")).toBeNull();
  });
});

describe("Home: header", () => {
  it("greets by first name and links exam / deadline pills to Study", async () => {
    vi.mocked(getUpcomingAssignments).mockResolvedValue({
      assignments: [
        { id: "a1", user_id: "u1", title: "Midterm", due_date: "2026-03-05", assignment_type: "exam", course_id: "c-BIO-101" },
        { id: "a2", user_id: "u1", title: "Problem Set 6", due_date: "2026-03-03", assignment_type: "homework", course_id: "c-PSY-110" },
        { id: "a3", user_id: "u1", title: "Participation", due_date: null },
      ],
    });
    render(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good morning, Ada" })).toBeInTheDocument();
    const exam = await screen.findByTestId("home-pill-exam");
    expect(exam).toHaveTextContent("Midterm in 4 days");
    expect(exam).toHaveAttribute("href", "/study?course=c-BIO-101");
    expect(screen.getByTestId("home-pill-deadline")).toHaveTextContent("Problem Set 6 due in 2 days");
    // Undated rows never reach Coming Up.
    const coming = screen.getByTestId("home-coming-up");
    expect(within(coming).getAllByTestId("home-coming-up-row")).toHaveLength(2);
    expect(within(coming).queryByText("Participation")).toBeNull();
    expect(within(coming).getByText("Calendar")).toHaveAttribute("href", "/calendar");
  });

  it("derives Up Next from the graph and Quick Reviews from due flashcards", async () => {
    vi.mocked(getCourses).mockResolvedValue({ courses: [course("MATH210", "Spring 2026", "Linear Algebra")] });
    vi.mocked(getGraph).mockResolvedValue(GRAPH);
    vi.mocked(getFlashcards).mockResolvedValue({
      flashcards: [
        { topic: "Vectors", times_reviewed: 0 },
        { topic: "vectors", times_reviewed: 0 },
        { topic: "Determinants", times_reviewed: 2, last_rating: 1, last_reviewed_at: "2026-02-20T00:00:00Z" },
        { topic: "Eigenvalues", times_reviewed: 1, last_rating: 3, last_reviewed_at: "2026-02-28T00:00:00Z" },
      ],
    });
    render(<Dashboard />);
    const upNext = await screen.findByTestId("home-up-next");
    await waitFor(() => expect(upNext).toHaveTextContent("Determinants"));
    expect(within(upNext).getByRole("link")).toHaveAttribute("href", "/study?course=c-MATH210");
    const reviews = screen.getByTestId("home-quick-reviews");
    await waitFor(() => expect(reviews).toHaveTextContent("2 Concepts"));
    expect(within(reviews).getByRole("link")).toHaveAttribute("href", "/flashcards");
  });

  it("types the greeting, then fades in one of the original quotes", async () => {
    render(<Dashboard />);
    const heading = await screen.findByRole("heading", { level: 1, name: "Good morning, Ada" });
    const quote = await screen.findByTestId("home-quote");
    // Hidden from assistive tech (and faded out) while the greeting types.
    expect(quote.closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "true");
    await waitFor(
      () => expect(within(heading).getByTestId("home-greeting-typed")).toHaveTextContent("Good morning, Ada"),
      { timeout: 3000 },
    );
    await waitFor(() => expect(quote.closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "false"), { timeout: 3000 });
    const shown = `${quote.textContent} ${quote.parentElement?.querySelector("figcaption")?.textContent ?? ""}`.trim();
    expect(QUOTES).toContain(shown);
  });
});

describe("Home: right column", () => {
  it("wires Last Session, Roadmap, notes, level and streak to real data", async () => {
    vi.mocked(getCourses).mockResolvedValue({ courses: [course("MATH210", "Spring 2026", "Linear Algebra")] });
    vi.mocked(getGraph).mockResolvedValue(GRAPH);
    vi.mocked(getSessions).mockResolvedValue({
      sessions: [{ id: "s1", topic: "Determinants", mode: "socratic", course_id: "c-MATH210", started_at: "2026-02-26T15:00:00", ended_at: "2026-02-26T16:00:00", message_count: 4, is_active: false }],
    });
    vi.mocked(listNotes).mockResolvedValue({
      notes: [
        { id: "n1", user_id: "u1", course_id: "c-MATH210", title: "Cofactors", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2026-02-01", updated_at: "2026-03-01T08:00:00" },
        { id: "n2", user_id: "u1", course_id: "c-MATH210", title: "Old", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2026-01-01", updated_at: "2026-01-01T08:00:00" },
        { id: "n3", user_id: "u1", course_id: "c-MATH210", title: "Oldest", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2025-01-01", updated_at: "2025-01-01T08:00:00" },
      ],
    });
    vi.mocked(fetchGamificationMe).mockResolvedValue({
      level: 3, next_level: 4, stage: "sprout" as never, total_xp: 900, xp_into_level: 240, xp_for_level: 500, level_pct: 48,
      streak: 4, longest_streak: 9, daily_goal_xp: 50, today_xp: 0, earned_count: 0, total_count: 0,
    });
    render(<Dashboard />);

    const last = await screen.findByTestId("home-last-session");
    await waitFor(() => expect(last).toHaveTextContent("Determinants"));
    expect(last).toHaveTextContent("Learning");
    expect(last).toHaveTextContent("Thursday");
    expect(within(last).getByTestId("dashboard-resume-s1")).toHaveAttribute("href", "/learn?resume=s1");

    const road = screen.getByTestId("home-roadmap");
    const goal = within(road).getAllByTestId("home-roadmap-row")[0];
    expect(goal).toHaveTextContent("Goal: Eigenvalues");
    expect(goal).toHaveTextContent("1 of 3 solid");
    expect(goal).toHaveTextContent("Determinants is the next step.");

    const notes = await screen.findByTestId("home-recent-notes");
    await waitFor(() => expect(within(notes).getByText(/Cofactors/)).toBeInTheDocument());
    expect(within(notes).getByText(/Cofactors/).closest("a")).toHaveAttribute("href", "/notetaker?note=n1");
    expect(within(notes).getByText("MATH210 · Edited today")).toBeInTheDocument();
    expect(within(notes).queryByText(/Oldest/)).toBeNull();
    expect(within(notes).getByText("Add note +")).toHaveAttribute("href", "/notetaker");

    fireEvent.mouseEnter(await screen.findByTestId("home-level"));
    const lvl = screen.getByRole("tooltip");
    expect(lvl).toHaveTextContent("Level 3");
    expect(lvl).toHaveTextContent("260 XP to go");
    fireEvent.mouseLeave(screen.getByTestId("home-level"));

    fireEvent.mouseEnter(screen.getByTestId("home-streak"));
    const stk = screen.getByRole("tooltip");
    expect(stk).toHaveTextContent("Days in a Row");
    expect(stk).toHaveTextContent("Best 9");
    const days = within(stk).getAllByTestId("home-streak-day");
    expect(days).toHaveLength(7);
    // The session (Thu) and Vectors study (Fri) light their flames.
    expect(days.map((d) => d.getAttribute("data-done"))).toEqual(["false", "false", "false", "true", "true", "false", "false"]);
  });

  it("hides Recent Notes when the notetaker is flagged off", async () => {
    navState.hidden = ["/notetaker"];
    render(<Dashboard />);
    await screen.findByTestId("home-roadmap");
    expect(screen.queryByTestId("home-recent-notes")).toBeNull();
  });
});

describe("Home: knowledge graph", () => {
  it("renders the original graph card with its concept count", async () => {
    vi.mocked(getCourses).mockResolvedValue({ courses: [course("MATH210", "Spring 2026", "Linear Algebra")] });
    vi.mocked(getGraph).mockResolvedValue(GRAPH);
    render(<Dashboard />);
    expect(await screen.findByTestId("knowledge-graph")).toBeInTheDocument();
    expect(screen.getByText("Knowledge Graph")).toBeInTheDocument();
    expect(screen.getByText(/concepts across 1 courses/)).toBeInTheDocument();
  });

  it("opens and closes the fullscreen graph", async () => {
    render(<Dashboard />);
    fireEvent.click(await screen.findByTestId("home-graph-fullscreen"));
    expect(screen.getByText("Press Esc to exit")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Press Esc to exit")).toBeNull());
  });
});

describe("Home async races (#769)", () => {
  it("a slow load for the previous semester can't repaint over the newer one", async () => {
    let resolveStale!: (v: { recommendations: { concept_name: string }[] }) => void;
    vi.mocked(getRecommendations).mockImplementation(async (_u, semester) =>
      semester === "Fall 2025"
        ? { recommendations: [{ concept_name: "FRESH-REC" }] }
        : new Promise((res) => { resolveStale = res; }),
    );
    render(<Dashboard />);
    await waitFor(() => expect(getRecommendations).toHaveBeenCalledWith("u1", undefined));
    await act(async () => {
      window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
      window.dispatchEvent(new Event("sapling-active-semester-change"));
    });
    expect(await screen.findByText("FRESH-REC")).toBeInTheDocument();
    await act(async () => { resolveStale({ recommendations: [{ concept_name: "STALE-REC" }] }); });
    expect(screen.queryByText("STALE-REC")).toBeNull();
    expect(screen.getByText("FRESH-REC")).toBeInTheDocument();
  });
});
