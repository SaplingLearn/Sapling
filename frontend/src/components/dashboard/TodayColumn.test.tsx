// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { Session } from "@/lib/api";
import type { GraphNode } from "@/lib/data";

vi.mock("../Icon", () => ({ Icon: () => null }));

import { buildTodayPlan, DashboardActions, dueAtMs, localDayKey, TodayColumn } from "./TodayColumn";

// Sat 7 Nov 2026, 15:00 local.
const NOW = new Date(2026, 10, 7, 15, 0, 0).getTime();
const TODAY = new Date(2026, 10, 7, 9, 0, 0).toISOString();
const YESTERDAY = new Date(2026, 10, 6, 20, 0, 0).toISOString();

function session(id: string, topic: string, started_at: string, ended_at: string | null = null): Session {
  return { id, topic, mode: "socratic", course_id: "c-math", started_at, ended_at, message_count: 4, is_active: false };
}

function node(id: string, name: string, tier: GraphNode["mastery_tier"], score: number, last?: string): GraphNode {
  return { id, name, subject: "Math", color: "#000", mastery_tier: tier, mastery_score: score, course_id: "c-math", last_studied_at: last };
}

const base = {
  sessions: [] as Session[],
  nodes: [] as GraphNode[],
  assignments: [] as (Parameters<typeof buildTodayPlan>[0]["assignments"]),
  hasCourses: true,
  nowMs: NOW,
  courseLabel: () => "MATH210",
  relTime: () => "14h ago",
};

afterEach(() => cleanup());

describe("dueAtMs", () => {
  it("reads a date-only due date as the end of that local day, not UTC midnight", () => {
    expect(dueAtMs("2026-11-07")).toBe(new Date(2026, 10, 7, 23, 59, 59, 999).getTime());
    expect(dueAtMs("2026-11-07T09:00:00Z")).toBe(Date.parse("2026-11-07T09:00:00Z"));
  });

  it("never calls work due later today OVERDUE", () => {
    const plan = buildTodayPlan({
      ...base,
      assignments: [{ id: "a", user_id: "u", title: "PS", due_date: "2026-11-07" }],
    });
    expect(plan.find((i) => i.key === "due-a")?.chip?.label).not.toBe("OVERDUE");
  });
});

describe("localDayKey", () => {
  it("keys on the local calendar day, not UTC", () => {
    expect(localDayKey(new Date(2026, 10, 7, 23, 30))).toBe("2026-11-07");
    expect(localDayKey(null)).toBeNull();
    expect(localDayKey("not a date")).toBeNull();
  });
});

describe("buildTodayPlan", () => {
  it("offers to resume the latest session when nothing was studied today", () => {
    const plan = buildTodayPlan({ ...base, sessions: [session("s2", "Vectors", YESTERDAY), session("s1", "Recursion", YESTERDAY)] });
    expect(plan[0]).toMatchObject({
      title: "Resume Vectors",
      done: false,
      checkable: true,
      href: "/learn?resume=s2",
      testId: "dashboard-resume-s2",
    });
  });

  it("ticks the session item off when a session ran today", () => {
    const plan = buildTodayPlan({
      ...base,
      sessions: [session("s2", "Vectors", YESTERDAY, TODAY), session("s1", "Recursion", YESTERDAY)],
    });
    expect(plan[0]).toMatchObject({ title: "Vectors", done: true, meta: "MATH210 · studied today" });
  });

  it("walks a first-run student through adding courses and a first session", () => {
    const fresh = buildTodayPlan({ ...base, hasCourses: false });
    expect(fresh.map((i) => [i.title, i.done])).toEqual([
      ["Add your courses", false],
      ["Start your first session", false],
    ]);
    const withCourses = buildTodayPlan({ ...base, hasCourses: true });
    expect(withCourses.map((i) => [i.title, i.done])).toEqual([
      ["Add your courses", true],
      ["Start your first session", false],
    ]);
  });

  it("quizzes the weakest struggling concept before any learning one", () => {
    const plan = buildTodayPlan({
      ...base,
      nodes: [
        node("n1", "Matrices", "learning", 0.1),
        node("n2", "Eigenvalues", "struggling", 0.3),
        node("n3", "Determinants", "struggling", 0.2),
      ],
    });
    const quiz = plan.find((i) => i.key.startsWith("quiz-"));
    expect(quiz).toMatchObject({ title: "Quiz: Determinants", meta: "MATH210 · you're struggling here", done: false });
    expect(quiz?.href).toContain("concept=n3");
  });

  it("falls back to a learning concept and marks it done once studied today", () => {
    const plan = buildTodayPlan({ ...base, nodes: [node("n1", "Matrices", "learning", 0.4, TODAY)] });
    expect(plan.find((i) => i.key === "quiz-n1")).toMatchObject({ meta: "MATH210 · reviewed today", done: true });
    const fresh = buildTodayPlan({ ...base, nodes: [node("n1", "Matrices", "learning", 0.4)] });
    expect(fresh.find((i) => i.key === "quiz-n1")).toMatchObject({ meta: "MATH210 · still learning", done: false });
  });

  it("keeps a concept reviewed today in the slot, ticked, once a weaker one exists", () => {
    // A was the weakest; the quiz lifted it above B. Re-picking the weakest
    // would swap in 'Quiz: B' and the item could never complete.
    const plan = buildTodayPlan({
      ...base,
      nodes: [node("a", "A", "learning", 0.3, TODAY), node("b", "B", "struggling", 0.2)],
    });
    expect(plan.find((i) => i.key.startsWith("quiz-"))).toMatchObject({ title: "Quiz: A", done: true, meta: "MATH210 · reviewed today" });
  });

  it("never quizzes a course root", () => {
    const root = { ...node("r", "MATH210", "struggling", 0), is_subject_root: true };
    expect(buildTodayPlan({ ...base, nodes: [root] }).some((i) => i.key.startsWith("quiz-"))).toBe(false);
  });

  it("adds only a near deadline, as an uncheckable reminder", () => {
    const soon = { id: "a1", user_id: "u", title: "Problem Set 4", due_date: new Date(2026, 10, 9, 23, 0).toISOString(), course_code: "CS101", assignment_type: "homework" };
    const later = { id: "a2", user_id: "u", title: "Essay", due_date: new Date(2026, 10, 20).toISOString() };
    const plan = buildTodayPlan({ ...base, assignments: [later, soon] });
    const due = plan.filter((i) => i.key.startsWith("due-"));
    expect(due).toHaveLength(1);
    expect(due[0]).toMatchObject({ title: "Problem Set 4", meta: "CS101 · homework", checkable: false, href: "/calendar" });
    expect(due[0].chip?.label).toBe("3D");
  });

  it("lists finished items first", () => {
    const plan = buildTodayPlan({
      ...base,
      sessions: [session("s1", "Vectors", YESTERDAY)],
      nodes: [node("n1", "Matrices", "struggling", 0.2, TODAY)],
    });
    expect(plan.map((i) => i.key)).toEqual(["quiz-n1", "session-s1"]);
  });
});

describe("DashboardActions", () => {
  it("routes to the calendar and the tutor", () => {
    const navigate = vi.fn();
    render(<DashboardActions navigate={navigate} />);
    fireEvent.click(screen.getByTestId("dashboard-action-calendar"));
    expect(navigate).toHaveBeenCalledWith("/calendar");
    fireEvent.click(screen.getByTestId("dashboard-action-start"));
    expect(navigate).toHaveBeenCalledWith("/learn");
  });
});

describe("TodayColumn", () => {
  const props = {
    ...base,
    sessions: [session("s1", "Vectors", YESTERDAY)],
    nodes: [node("n1", "Matrices", "struggling", 0.2, TODAY)],
    stats: { streak: 12, mastered: 4, total: 13, learning: 3, struggling: 2, unexplored: 4 },
    bestStreak: 14,
    xpDays: new Set<string>(),
    today: new Date(2026, 10, 7),
    weekDays: Array.from({ length: 7 }, (_, i) => new Date(2026, 10, 2 + i)),
    navigate: vi.fn(),
    openCourses: vi.fn(),
  };

  it("counts only checkable items and resumes from the plan", () => {
    render(<TodayColumn {...props} />);
    expect(screen.getByTestId("dashboard-plan-progress")).toHaveTextContent("1 of 2 done today");
    expect(screen.getByText("best 14")).toBeInTheDocument();
    expect(screen.getByText("Today counted. Nice work.")).toBeInTheDocument();
    expect(screen.getByText("of 13 concepts mastered")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("dashboard-resume-s1"));
    expect(props.navigate).toHaveBeenCalledWith("/learn?resume=s1");
  });

  it("never says 'Today counted' over a zero streak", () => {
    render(<TodayColumn {...props} stats={{ ...props.stats, streak: 0 }} />);
    expect(screen.queryByText(/Today counted/)).toBeNull();
    expect(screen.getByText("Nice work today.")).toBeInTheDocument();
  });

  it("invites a first session when there is no streak yet", () => {
    render(<TodayColumn {...props} nodes={[]} sessions={[]} bestStreak={0} stats={{ ...props.stats, streak: 0, total: 0 }} />);
    expect(screen.getByText("One session today starts your streak.")).toBeInTheDocument();
    expect(screen.queryByText(/^best /)).toBeNull();
    expect(screen.getByText(/No concepts yet/)).toBeInTheDocument();
    // Already done (they have courses), but the row still opens the manager.
    fireEvent.click(screen.getByText("Add your courses"));
    expect(props.openCourses).toHaveBeenCalled();
  });
});
