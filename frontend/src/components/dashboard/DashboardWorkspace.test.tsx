// @vitest-environment jsdom
/**
 * Dashboard / Today learning workspace (redesign prompt 07) — behaviour.
 *
 *  - Arrival is READ-ONLY: only the read clients are called; no session,
 *    goal, plan, probe/check, answer, close or note mutation ever runs, and
 *    nothing reaches fetch directly.
 *  - The ONE primary action follows the real loop phase (pending, failure +
 *    Retry, no course, no concepts, no session, probe/plan/teach/check/
 *    feedback/close, legacy kill switch) and resumes by session id, also
 *    across courses.
 *  - Selection / Back change the page only; Practice is explicit, honours
 *    an open session with a confirm whose Cancel changes nothing, and keeps
 *    the real topic + course ids. Same-named topics stay distinct by id.
 *  - Scope: the course filter keeps counts and canvas together and clears a
 *    selection the scope no longer shows; a late answer for an old semester
 *    never paints over the current one.
 *  - Notes: real rows only, empty ≠ failure, the hide_notetaker flag.
 *  - Phone: a static preview (no gestures), View topics → selected-topic
 *    sheet with Escape + focus return; the full map dialog.
 *
 * The graph renderer is stubbed (one button per node) so these tests read
 * what the page passes it — selection, interactivity — not d3 geometry.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";

const push = vi.fn();
const replace = vi.fn();
const nav = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
  usePathname: () => "/dashboard",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));
const viewport = vi.hoisted(() => ({ phone: false }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => viewport.phone, MOBILE_BREAKPOINT: 768 }));
const flags = vi.hoisted(() => ({ map: {} as Record<string, string> }));
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (k: string) => flags.map[k] ?? "off",
  useFlagMap: () => ({ flags: flags.map, ready: true }),
}));
vi.mock("@/components/ManageCoursesModal", () => ({
  ManageCoursesModal: ({ open }: { open: boolean }) => (open ? <div data-testid="manage-courses-modal" /> : null),
}));

// The renderer stub: one button per node, plus the props the page passed.
vi.mock("@/components/graph/KnowledgeGraph", () => ({
  KnowledgeGraph: (p: {
    nodes: { id: string; name: string }[];
    selectedId?: string | null;
    interactive?: boolean;
    appearance?: string;
    onNodeClick?: (n: unknown) => void;
  }) => (
    <div
      data-testid="graph-stub"
      data-selected={p.selectedId ?? ""}
      data-interactive={String(p.interactive !== false)}
      data-appearance={p.appearance}
      data-count={p.nodes.length}
    >
      {p.nodes.map((n) => (
        <button key={n.id} type="button" data-testid={`stub-node-${n.id}`} onClick={() => p.onNodeClick?.(n)}>
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/lib/api", () => ({
  // reads
  getGraph: vi.fn(),
  getCourses: vi.fn(),
  getUpcomingAssignments: vi.fn(),
  getSessions: vi.fn(),
  listNotes: vi.fn(),
  getLoopStatus: vi.fn(),
  listLoopSessionsFor: vi.fn(),
  getLoopSessionStatus: vi.fn(),
  getRecommendations: vi.fn(),
  // mutations — the dashboard must never call any of these
  startLoopSession: vi.fn(),
  setLoopGoal: vi.fn(),
  nextLoopProbe: vi.fn(),
  answerLoopProbe: vi.fn(),
  approveLoopPlan: vi.fn(),
  nextLoopCheck: vi.fn(),
  streamLoopCheckAnswer: vi.fn(),
  streamLoopChat: vi.fn(),
  closeLoopSession: vi.fn(),
  startSession: vi.fn(),
  createNote: vi.fn(),
  patchNote: vi.fn(),
  addCourse: vi.fn(),
}));

import { Dashboard } from "@/components/screens/Dashboard";
import * as api from "@/lib/api";
import type { EnrolledCourse, LoopSessionStatus, Session } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
// Mirrors KnowledgeGraph.tsx GRAPH_MODE_STORAGE_KEY (the module is stubbed here).
const GRAPH_MODE_STORAGE_KEY = "sapling.kg.mode";

const m = vi.mocked(api);
const MUTATIONS = [
  "startLoopSession", "setLoopGoal", "nextLoopProbe", "answerLoopProbe", "approveLoopPlan",
  "nextLoopCheck", "streamLoopCheckAnswer", "streamLoopChat", "closeLoopSession", "startSession",
  "createNote", "patchNote", "addCourse",
] as const;

const course = (id: string, code: string, term = "Spring 2026"): EnrolledCourse => ({
  enrollment_id: `e-${id}`,
  course_id: id,
  course_code: code,
  course_name: `${code} name`,
  school: "BU",
  department: "CS",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term,
});
const apiNode = (id: string, name: string, courseId: string, subject: string, extra: Record<string, unknown> = {}) => ({
  id,
  concept_name: name,
  mastery_score: 0.4,
  mastery_tier: "learning",
  times_studied: 3,
  last_studied_at: "2026-03-10T12:00:00Z",
  subject,
  course_id: courseId,
  is_subject_root: false,
  ...extra,
});
const hub = (courseId: string, label: string) =>
  apiNode(`subject_root__${courseId}`, label, courseId, label, { is_subject_root: true, mastery_tier: "subject_root", times_studied: 0 });
const session = (id: string, courseId: string, active = true, topic = "Topic"): Session => ({
  id,
  topic,
  mode: "socratic",
  course_id: courseId,
  started_at: "2026-03-10T12:00:00Z",
  ended_at: active ? null : "2026-03-10T13:00:00Z",
  message_count: 2,
  is_active: active,
});
const status = (sessionId: string, loop_phase: string, phase = loop_phase, extra: Partial<LoopSessionStatus> = {}): LoopSessionStatus => ({
  active: true,
  session_id: sessionId,
  loop_phase,
  phase,
  goal_version: 2,
  goal: { text: "Understand recursion", target_node_ids: ["n-rec"] },
  diagnosis: null,
  goal_progress: null,
  ...extra,
});

const CS = course("c-cs", "CS101");
const MATH = course("c-math", "MATH210");
const GRAPH = {
  nodes: [
    hub("c-cs", "CS101 - Intro"),
    hub("c-math", "MATH210 - Linear Algebra"),
    apiNode("n-rec", "Recursion", "c-cs", "CS101 name", { description: "A function calling itself." }),
    apiNode("n-loop", "Loops", "c-cs", "CS101 name", { mastery_tier: "mastered", mastery_score: 0.97 }),
    apiNode("n-vec", "Vectors", "c-math", "MATH210 name", { mastery_tier: "struggling", mastery_score: 0.2, times_studied: 0 }),
  ],
  edges: [],
  stats: { streak: 4 },
};

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  nav.search = "";
  viewport.phone = false;
  flags.map = {};
  window.localStorage.clear();
  __resetScrollLocksForTests();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  fetchSpy = vi.fn(() => Promise.reject(new Error("no direct fetch from the dashboard")));
  vi.stubGlobal("fetch", fetchSpy);

  m.getCourses.mockResolvedValue({ courses: [CS, MATH] });
  m.getGraph.mockResolvedValue(GRAPH);
  m.getUpcomingAssignments.mockResolvedValue({
    assignments: [
      { id: "a1", user_id: "u1", title: "Problem Set 4", due_date: "2026-03-20", course_code: "MATH210" },
      { id: "a2", user_id: "u1", title: "Participation", due_date: null },
    ],
  });
  m.getSessions.mockResolvedValue({ sessions: [session("s-cs", "c-cs", true, "Recursion")] });
  m.listNotes.mockResolvedValue({
    notes: [
      { id: "note-1", user_id: "u1", course_id: "c-cs", title: "Week 1", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2026-03-01", updated_at: "2026-03-10T12:00:00Z" },
      { id: "note-2", user_id: "u1", course_id: "c-math", title: "Vectors", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2026-03-01", updated_at: "2026-03-09T12:00:00Z" },
      { id: "note-3", user_id: "u1", course_id: "c-math", title: "Older", body: "", tags: [], last_summary: null, last_summary_at: null, created_at: "2026-03-01", updated_at: "2026-03-01T12:00:00Z" },
    ],
  });
  m.getLoopStatus.mockResolvedValue({ active: true });
  m.listLoopSessionsFor.mockImplementation(async (_u, courseId, resume) => ({
    sessions: courseId === "c-cs" ? [{ session_id: "s-cs", topic: "Recursion", started_at: "2026-03-10T12:00:00Z", phase: "teach" }] : [],
    resume: resume === "s-cs" ? { session_id: "s-cs", topic: "Recursion", started_at: "2026-03-10T12:00:00Z", phase: "teach", course_id: "c-cs" } : null,
  }));
  m.getLoopSessionStatus.mockResolvedValue(status("s-cs", "teach"));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const expectNoMutation = () => {
  for (const name of MUTATIONS) expect(m[name], `${name} must not be called`).not.toHaveBeenCalled();
  expect(fetchSpy).not.toHaveBeenCalled();
};
const nextAction = () => screen.findByTestId("dashboard-next-action");
async function arrive() {
  render(<Dashboard />);
  await waitFor(() => expect(screen.getByTestId("dashboard-next")).not.toHaveAttribute("data-state", "pending"));
}

describe("arrival is read-only and offers ONE state-driven action", () => {
  it("resumes the open session by id after reads only", async () => {
    await arrive();
    const action = await nextAction();
    expect(action).toHaveTextContent("Continue learning");
    expect(screen.getAllByTestId("dashboard-next-action")).toHaveLength(1);
    expect(screen.getByTestId("dashboard-goal-text")).toHaveTextContent("Understand recursion");
    expect(screen.getByTestId("dashboard-goal-scope")).toHaveTextContent("CS101 · Recursion");
    expect(m.listLoopSessionsFor).toHaveBeenCalledWith("u1", "c-cs", "s-cs");
    expect(m.getLoopSessionStatus).toHaveBeenCalledWith("s-cs", "u1");
    expectNoMutation();
    fireEvent.click(action);
    expect(push).toHaveBeenCalledWith("/learn?resume=s-cs");
    expectNoMutation();
  });

  it.each([
    ["probe", "probe", "Resume check-in"],
    ["plan", "plan", "Review plan"],
    ["teach", "teach", "Continue learning"],
    ["teach", "check", "Resume check"],
    ["teach", "feedback", "Review feedback"],
    ["close", "close", "See wrap-up"],
  ])("loop_phase %s / phase %s → %s", async (loopPhase, phase, label) => {
    m.getLoopSessionStatus.mockResolvedValue(status("s-cs", loopPhase, phase));
    await arrive();
    await waitFor(async () => expect(await nextAction()).toHaveTextContent(label));
    fireEvent.click(await nextAction());
    expect(push).toHaveBeenCalledWith("/learn?resume=s-cs");
    expectNoMutation();
  });

  it("a pending plan says approval is explicit and never approves", async () => {
    m.getLoopSessionStatus.mockResolvedValue(status("s-cs", "plan"));
    await arrive();
    expect(await screen.findByTestId("dashboard-next-reason")).toHaveTextContent("only after you approve it");
    expect(m.approveLoopPlan).not.toHaveBeenCalled();
  });

  it("while discovery is pending there is no new-session or continue offer", async () => {
    m.getLoopStatus.mockReturnValue(new Promise(() => {}));
    render(<Dashboard />);
    const action = await screen.findByTestId("dashboard-next-action");
    expect(action).toBeDisabled();
    expect(action).toHaveTextContent("Checking");
    expect(screen.queryByText(/Start a check-in/)).toBeNull();
    expectNoMutation();
  });

  it("a failed discovery shows Retry, starts nothing, and Retry re-reads", async () => {
    m.listLoopSessionsFor.mockRejectedValueOnce(new Error("503"));
    await arrive();
    expect(await screen.findByTestId("dashboard-discovery-error")).toHaveTextContent("Nothing was started");
    expect(screen.queryByTestId("dashboard-next-action")).toBeNull();
    fireEvent.click(screen.getByTestId("dashboard-discovery-error-retry"));
    await waitFor(async () => expect(await nextAction()).toHaveTextContent("Continue learning"));
    expect(m.listLoopSessionsFor).toHaveBeenCalledTimes(2);
    expectNoMutation();
  });

  it("a missing /status still resumes the listed session, saying the goal detail is missing", async () => {
    m.getLoopSessionStatus.mockRejectedValue(new Error("500"));
    await arrive();
    expect(await nextAction()).toHaveTextContent("Continue learning");
    expect(screen.getByTestId("dashboard-next-details")).toHaveTextContent("couldn't load");
  });

  it("restores an open session in ANOTHER course by its real id", async () => {
    m.getSessions.mockResolvedValue({ sessions: [session("s-math", "c-math", true, "Vectors")] });
    m.listLoopSessionsFor.mockImplementation(async (_u, _c, resume) => ({
      sessions: [],
      resume: resume === "s-math" ? { session_id: "s-math", topic: "Vectors", started_at: "x", phase: "probe", course_id: "c-math" } : null,
    }));
    m.getLoopSessionStatus.mockResolvedValue(status("s-math", "probe", "probe", { goal: null }));
    await arrive();
    expect(await nextAction()).toHaveTextContent("Resume check-in");
    expect(screen.getByTestId("dashboard-goal-text")).toHaveTextContent("Explore MATH210");
    fireEvent.click(await nextAction());
    expect(push).toHaveBeenCalledWith("/learn?resume=s-math");
  });

  it("no open session: a deliberate check-in in a named course (created only by Learn on click)", async () => {
    m.getSessions.mockResolvedValue({ sessions: [session("s-old", "c-math", false, "Vectors")] });
    m.listLoopSessionsFor.mockResolvedValue({ sessions: [], resume: null });
    await arrive();
    const action = await nextAction();
    expect(action).toHaveTextContent("Start a check-in");
    expect(screen.getByTestId("dashboard-next-title")).toHaveTextContent("MATH210");
    expect(screen.getByTestId("dashboard-goal-text")).toHaveTextContent("No saved goal yet");
    expect(screen.getByTestId("dashboard-next-last-session")).toHaveAttribute("href", "/learn?resume=s-old");
    expect(m.getLoopSessionStatus).not.toHaveBeenCalled();
    fireEvent.click(action);
    expect(push).toHaveBeenCalledWith("/learn?course=c-math");
    expectNoMutation();
  });

  it("no courses: Add a course opens the Courses & Semesters hub", async () => {
    m.getCourses.mockResolvedValue({ courses: [] });
    m.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
    m.getSessions.mockResolvedValue({ sessions: [] });
    await arrive();
    expect(screen.getByTestId("dashboard-next")).toHaveAttribute("data-state", "no-course");
    fireEvent.click(await nextAction());
    expect(screen.getByTestId("manage-courses-modal")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-next-library")).toHaveAttribute("href", "/library");
  });

  it("a course with no concepts points at its Library instead of a check-in", async () => {
    m.getCourses.mockResolvedValue({ courses: [CS] });
    m.getGraph.mockResolvedValue({ nodes: [hub("c-cs", "CS101 - Intro")], edges: [], stats: {} });
    m.getSessions.mockResolvedValue({ sessions: [] });
    m.listLoopSessionsFor.mockResolvedValue({ sessions: [], resume: null });
    await arrive();
    await waitFor(() => expect(screen.getByTestId("dashboard-next")).toHaveAttribute("data-state", "no-concepts"));
    fireEvent.click(await nextAction());
    expect(push).toHaveBeenCalledWith("/library?course=c-cs");
  });

  it("kill switch (loop off): the legacy tutor session resumes; loop routes are not called", async () => {
    m.getLoopStatus.mockResolvedValue({ active: false });
    await arrive();
    expect(await nextAction()).toHaveTextContent("Continue session");
    expect(m.listLoopSessionsFor).not.toHaveBeenCalled();
    fireEvent.click(await nextAction());
    expect(push).toHaveBeenCalledWith("/learn?resume=s-cs");
  });
});

describe("selection is UI context only; practice is explicit", () => {
  it("selecting shows course/state/explanation/evidence; Back restores the next step; nothing is written", async () => {
    await arrive();
    fireEvent.click(await screen.findByTestId("stub-node-n-rec"));
    const detail = await screen.findByTestId("dashboard-concept");
    expect(within(detail).getByRole("heading", { name: "Recursion" })).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-concept-state")).toHaveTextContent("CS101");
    expect(screen.getByTestId("dashboard-concept-state")).toHaveTextContent("Learning");
    expect(screen.getByTestId("dashboard-concept-explanation")).toHaveTextContent("A function calling itself.");
    expect(screen.getByTestId("dashboard-concept-evidence")).toHaveTextContent("3 recorded answers");
    expect(screen.getByTestId("dashboard-concept-evidence")).toHaveTextContent("Part of your saved goal");
    expect(screen.getByTestId("graph-stub")).toHaveAttribute("data-selected", "n-rec");
    expect(screen.queryByTestId("dashboard-next")).toBeNull();
    fireEvent.click(screen.getByTestId("dashboard-concept-back"));
    expect(await screen.findByTestId("dashboard-next")).toBeInTheDocument();
    expect(screen.getByTestId("graph-stub")).toHaveAttribute("data-selected", "");
    expect(push).not.toHaveBeenCalled();
    expectNoMutation();
  });

  it("an unrecorded concept says its state is a starting estimate, and never invents an explanation", async () => {
    await arrive();
    fireEvent.click(await screen.findByTestId("stub-node-n-vec"));
    expect(await screen.findByTestId("dashboard-concept-evidence")).toHaveTextContent("No answers recorded yet");
    expect(screen.getByTestId("dashboard-concept-explanation")).toHaveTextContent("No explanation is saved");
  });

  it("with an open session, Practice asks first; Cancel changes nothing; Continue keeps topic + course ids", async () => {
    await arrive();
    fireEvent.click(await screen.findByTestId("stub-node-n-vec"));
    fireEvent.click(await screen.findByTestId("dashboard-concept-practice"));
    const confirm = screen.getByTestId("dashboard-concept-confirm");
    expect(confirm).toHaveTextContent("open session in CS101 stays saved");
    fireEvent.click(screen.getByTestId("dashboard-concept-confirm-cancel"));
    expect(screen.queryByTestId("dashboard-concept-confirm")).toBeNull();
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("dashboard-concept-practice"));
    fireEvent.click(screen.getByTestId("dashboard-concept-confirm-go"));
    expect(push).toHaveBeenCalledWith("/learn?topic=Vectors&mode=socratic&course=c-math");
    expectNoMutation();
  });

  it("without an open session Practice goes straight to Learn with the ids", async () => {
    m.getSessions.mockResolvedValue({ sessions: [] });
    m.listLoopSessionsFor.mockResolvedValue({ sessions: [], resume: null });
    await arrive();
    fireEvent.click(await screen.findByTestId("stub-node-n-rec"));
    fireEvent.click(await screen.findByTestId("dashboard-concept-practice"));
    expect(push).toHaveBeenCalledWith("/learn?topic=Recursion&mode=socratic&course=c-cs");
  });

  it("a course hub gets course counts and an explicit course-scoped action", async () => {
    m.getSessions.mockResolvedValue({ sessions: [] });
    m.listLoopSessionsFor.mockResolvedValue({ sessions: [], resume: null });
    await arrive();
    fireEvent.click(await screen.findByTestId("stub-node-subject_root__c-cs"));
    expect(await screen.findByTestId("dashboard-concept-course-counts")).toHaveTextContent("2 concepts: 1 mastered · 1 learning");
    const go = screen.getByTestId("dashboard-concept-practice");
    expect(go).toHaveTextContent("Learn in CS101");
    fireEvent.click(go);
    expect(push).toHaveBeenCalledWith("/learn?course=c-cs");
  });

  it("same-named topics in two courses stay distinct by id", async () => {
    m.getGraph.mockResolvedValue({
      ...GRAPH,
      nodes: [...GRAPH.nodes, apiNode("n-rec-math", "Recursion", "c-math", "MATH210 name", { mastery_tier: "mastered" })],
    });
    await arrive();
    fireEvent.click(await screen.findByTestId("dashboard-view-topics"));
    const sheet = await screen.findByTestId("dashboard-topics");
    expect(within(sheet).getByTestId("dashboard-topic-n-rec")).toHaveTextContent("Recursion (CS101)");
    expect(within(sheet).getByTestId("dashboard-topic-n-rec-math")).toHaveTextContent("Recursion (MATH210)");
    fireEvent.click(within(sheet).getByTestId("dashboard-topic-n-rec-math"));
    const state = await screen.findByTestId("dashboard-concept-state");
    expect(state).toHaveTextContent("MATH210");
    expect(state).toHaveTextContent("Mastered");
    expect(screen.getByTestId("dashboard-concept")).toHaveAttribute("data-node-id", "n-rec-math");
  });
});

describe("scope", () => {
  it("the course filter keeps counts and canvas together and clears an out-of-scope selection", async () => {
    await arrive();
    expect(await screen.findByTestId("dashboard-map-counts")).toHaveTextContent("3 concepts · 2 courses");
    expect(screen.getByTestId("dashboard-scope-line")).toHaveTextContent("All courses · All semesters");
    fireEvent.click(screen.getByTestId("stub-node-n-vec"));
    expect(await screen.findByTestId("dashboard-concept")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("dashboard-course-filter"), { target: { value: "c-cs" } });
    expect(screen.getByTestId("dashboard-map-counts")).toHaveTextContent("2 concepts · 1 course");
    expect(screen.getByTestId("graph-stub")).toHaveAttribute("data-count", "3");
    expect(screen.queryByTestId("dashboard-concept")).toBeNull();
    // the goal / session are untouched by a scope change
    expect(await nextAction()).toHaveTextContent("Continue learning");
    expect(screen.getByTestId("dashboard-goal-text")).toHaveTextContent("Understand recursion");
    expectNoMutation();
  });

  it("ignores a late graph answer for the previous semester", async () => {
    let resolveOld!: (v: unknown) => void;
    m.getGraph.mockImplementation((_u, sem) =>
      sem === "Fall 2025"
        ? Promise.resolve({ nodes: [hub("c-cs", "CS101"), apiNode("n-fall", "Fall topic", "c-cs", "CS101 name")], edges: [], stats: {} })
        : (new Promise((r) => (resolveOld = r)) as never),
    );
    m.getCourses.mockResolvedValue({ courses: [course("c-cs", "CS101", "Fall 2025"), course("c-math", "MATH210", "Spring 2026")] });
    await arrive();
    act(() => {
      window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
      window.dispatchEvent(new Event("sapling-active-semester-change"));
    });
    expect(await screen.findByTestId("stub-node-n-fall")).toBeInTheDocument();
    await act(async () => {
      resolveOld(GRAPH);
    });
    expect(screen.getByTestId("stub-node-n-fall")).toBeInTheDocument();
    expect(screen.queryByTestId("stub-node-n-vec")).toBeNull();
    expect(screen.getByTestId("dashboard-scope-line")).toHaveTextContent("Fall 2025");
  });

  it("the courses key lists courses with state counts in words and opens the hub", async () => {
    await arrive();
    fireEvent.click(await screen.findByTestId("dashboard-courses-key-toggle"));
    const codes = screen.getAllByTestId("dashboard-course-code").map((e) => e.textContent);
    expect(codes).toEqual(["CS101", "MATH210"]);
    expect(screen.getByTestId("dashboard-courses")).toHaveTextContent("1 mastered · 1 learning · 0 struggling · 0 unexplored");
    fireEvent.click(screen.getByTestId("dashboard-courses-manage"));
    expect(screen.getByTestId("manage-courses-modal")).toBeInTheDocument();
  });
});

describe("truthful regions", () => {
  it("notes: at most two real rows, each opening that note", async () => {
    await arrive();
    expect(await screen.findByTestId("dashboard-note-note-1")).toHaveAttribute("href", "/notetaker?note=note-1");
    expect(screen.getByTestId("dashboard-note-note-2")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-note-note-3")).toBeNull();
    expect(screen.getByTestId("dashboard-note-note-1")).toHaveTextContent("CS101 · Edited");
  });

  it("notes: a failed read is an error with Retry, not 'no notes'", async () => {
    m.listNotes.mockRejectedValueOnce(new Error("500"));
    await arrive();
    expect(await screen.findByTestId("dashboard-notes-error")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-notes-empty")).toBeNull();
    fireEvent.click(screen.getByTestId("dashboard-notes-error-retry"));
    expect(await screen.findByTestId("dashboard-note-note-1")).toBeInTheDocument();
  });

  it("notes: empty says so; the notetaker flag hides notes without reading them", async () => {
    m.listNotes.mockResolvedValue({ notes: [] });
    await arrive();
    expect(await screen.findByTestId("dashboard-notes-empty")).toBeInTheDocument();
    cleanup();
    vi.clearAllMocks();
    flags.map = { hide_notetaker: "on" };
    m.listNotes.mockResolvedValue({ notes: [] });
    await arrive();
    expect(screen.getByTestId("dashboard-notes-off")).toBeInTheDocument();
    expect(m.listNotes).not.toHaveBeenCalled();
  });

  it("a map failure is local: Retry, while the next step and notes still work", async () => {
    m.getGraph.mockRejectedValueOnce(new Error("503"));
    await arrive();
    expect(await screen.findByTestId("dashboard-map-error")).toBeInTheDocument();
    expect(await nextAction()).toHaveTextContent("Continue learning");
    expect(await screen.findByTestId("dashboard-note-note-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dashboard-map-error-retry"));
    expect(await screen.findByTestId("stub-node-n-rec")).toBeInTheDocument();
  });

  it("coming up: only dated assignments, with an explicit date; the due review keeps its return context", async () => {
    await arrive();
    expect(await screen.findByTestId("dashboard-assignment-a1")).toHaveTextContent("Due");
    expect(screen.queryByText("Participation")).toBeNull();
    fireEvent.click(screen.getByTestId("dashboard-review-due"));
    expect(push).toHaveBeenCalledWith("/quiz?scope=due&from=dashboard&return=%2Fdashboard");
  });

  it("streak is quiet metadata from the real field; there is no 'personal best'", async () => {
    await arrive();
    expect(await screen.findByTestId("dashboard-meta")).toHaveTextContent("4-day streak");
    expect(screen.queryByText(/personal best/i)).toBeNull();
  });
});

describe("retained destinations", () => {
  it("Library, Calendar, Learn, sessions, notes, map tools and course management are all reachable", async () => {
    await arrive();
    expect(await screen.findByTestId("dashboard-view-library")).toHaveAttribute("href", "/library");
    expect(screen.getByTestId("dashboard-open-calendar")).toHaveAttribute("href", "/calendar");
    expect(screen.getByTestId("dashboard-open-learn")).toHaveAttribute("href", "/learn");
    fireEvent.click(await screen.findByTestId("dashboard-resume-s-cs"));
    expect(push).toHaveBeenCalledWith("/learn?resume=s-cs");
    expect(screen.getByTestId("dashboard-open-map")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-view-topics")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-courses-key-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("graph-stub")).toHaveAttribute("data-appearance", "sapling");
  });

  it("?suggest= highlights a real concept with Start quiz; Dismiss clears the query", async () => {
    nav.search = "suggest=recursion&x=1";
    await arrive();
    expect(await screen.findByTestId("dashboard-suggest")).toHaveTextContent("Recursion · CS101");
    fireEvent.click(screen.getByText("Start quiz"));
    expect(push).toHaveBeenCalledWith("/quiz?concept=n-rec&from=dashboard&return=%2Fdashboard");
    fireEvent.click(screen.getByTestId("dashboard-suggest-dismiss"));
    expect(replace).toHaveBeenCalledWith("/dashboard?x=1");
  });

  it("an unknown ?suggest= says so instead of silently vanishing", async () => {
    nav.search = "suggest=Renamed%20thing";
    await arrive();
    expect(await screen.findByTestId("dashboard-suggest-missing")).toHaveTextContent("couldn't find “Renamed thing”");
  });

  it("?layout=legacy keeps the pre-redesign dashboard", async () => {
    nav.search = "layout=legacy";
    m.getRecommendations.mockResolvedValue({ recommendations: [] });
    render(<Dashboard />);
    expect(await screen.findAllByTestId("dashboard-review-due")).not.toHaveLength(0);
    expect(screen.queryByTestId("dashboard-workspace")).toBeNull();
  });
});

describe("full map and phone", () => {
  it("Open full map is a labelled dialog; selection there shows details; Escape returns focus", async () => {
    await arrive();
    const opener = await screen.findByTestId("dashboard-open-map");
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Your knowledge map" });
    expect(screen.getAllByTestId("graph-stub")).toHaveLength(1); // the inline canvas stood down
    expect(within(dialog).getByTestId("graph-stub")).toHaveAttribute("data-interactive", "true");
    fireEvent.click(within(dialog).getByTestId("stub-node-n-rec"));
    expect(within(dialog).getByTestId("dashboard-full-map-concept")).toHaveTextContent("Recursion");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("dashboard-open-map")));
    expectNoMutation();
  });

  it("phone: a static preview the page scrolls past; View topics → selected-topic sheet; Escape closes and returns focus", async () => {
    viewport.phone = true;
    window.localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "3d");
    await arrive();
    const stub = await screen.findByTestId("graph-stub");
    expect(stub).toHaveAttribute("data-interactive", "false");
    expect(screen.getByTestId("dashboard-map-preview")).toBeInTheDocument();
    // the preview is not a selection surface (no tap traps)
    fireEvent.click(screen.getByTestId("stub-node-n-rec"));
    expect(screen.queryByTestId("dashboard-concept-sheet")).toBeNull();
    // the persisted 2D/3D preference is untouched by the preview
    expect(window.localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("3d");

    const topics = screen.getByTestId("dashboard-view-topics");
    topics.focus();
    fireEvent.click(topics);
    const list = await screen.findByTestId("dashboard-topics");
    fireEvent.click(within(list).getByTestId("dashboard-topic-n-rec"));
    const sheet = await screen.findByTestId("dashboard-concept-sheet");
    expect(sheet).toHaveAttribute("role", "dialog");
    expect(within(sheet).getByTestId("dashboard-sheet-concept-practice")).toHaveTextContent("Practice this concept");
    expect(within(sheet).getByTestId("dashboard-sheet-concept-back")).toBeInTheDocument();
    fireEvent.keyDown(sheet, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("dashboard-concept-sheet")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("dashboard-view-topics")));
    expect(screen.getByTestId("dashboard-next")).toBeInTheDocument();
    expectNoMutation();
  });
});
