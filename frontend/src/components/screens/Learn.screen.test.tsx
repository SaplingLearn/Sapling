// @vitest-environment jsdom
/**
 * Characterization of the tutor screen's render paths and UI handlers — the
 * parts of `LearnInner` that Learn.sessionState.test.tsx (the #762 race
 * suite) does not pin: the entry screen, the resume loading state, the chat
 * header, the knowledge-map rail (focus card, branch list, elsewhere chips,
 * add-concept composer, collapse tab), the mobile tabs, the summary modal and
 * the recent-session row actions. Written against the pre-split component so
 * the complexity refactor can be checked against it unchanged.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act, within } from "@testing-library/react";

const nav = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

const env = vi.hoisted(() => ({ mobile: false }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => env.mobile }));
vi.mock("@/lib/useActiveSemester", () => ({
  useActiveSemester: () => ["", () => {}, true],
  courseInTerm: () => true,
}));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: ({ nodes, highlightId, onNodeClick }: { nodes: { id: string; name: string }[]; highlightId?: string; onNodeClick?: (n: unknown) => void }) => (
    <div data-testid="kg" data-highlight={highlightId ?? ""}>
      {nodes.map(n => (
        <button key={n.id} data-testid={`kg-node-${n.id}`} onClick={() => onNodeClick?.(n)}>
          {n.name}
        </button>
      ))}
    </div>
  ),
}));
vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));

const api = vi.hoisted(() => ({
  startSession: vi.fn(),
  startSessionStream: vi.fn(),
  sendChat: vi.fn(),
  streamChat: vi.fn(),
  getSessions: vi.fn(),
  resumeSession: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  endSession: vi.fn(),
  switchMode: vi.fn(),
  learnAction: vi.fn(),
  getCourses: vi.fn(),
  getGraph: vi.fn(),
  addGraphNode: vi.fn(),
  deleteGraphNode: vi.fn(),
  describeConcept: vi.fn(),
}));
vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { Learn } from "./Learn";
import { ToastProvider } from "../ToastProvider";

class StubResizeObserver {
  constructor(private cb: (entries: { contentRect: { width: number } }[]) => void) {}
  observe() { this.cb([{ contentRect: { width: 300 } }]); }
  unobserve() {}
  disconnect() {}
}

const SESSION_A = {
  session: { id: "sess-a", topic: "Recursion", mode: "socratic", course_id: "c1" },
  messages: [
    { role: "user", content: "what is recursion" },
    { role: "assistant", content: "A function calling itself." },
  ],
};
const SESSION_FREE = {
  session: { id: "sess-free", topic: "Free topic", mode: "expository", course_id: null },
  messages: [{ role: "assistant", content: "Free-form." }],
};

function sessionRow(id: string, topic: string, message_count = 2) {
  return {
    id, topic, mode: "socratic", course_id: "c1", started_at: "2026-11-01T00:00:00Z",
    ended_at: null, message_count, is_active: true,
  };
}

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "CS101", course_name: "Intro CS",
  school: "", department: "", color: null, nickname: null, node_count: 3,
  enrolled_at: "2026-09-01T00:00:00Z", term: "", terms: [],
};

const node = (id: string, name: string, score: number, tier: string, extra: Record<string, unknown> = {}) => ({
  id, concept_name: name, subject: "Intro CS", course_id: "c1", mastery_score: score, mastery_tier: tier,
  times_studied: 0, last_studied_at: null, ...extra,
});

const GRAPH = {
  nodes: [
    node("root-c1", "Intro CS", 0, "subject_root", { is_subject_root: true }),
    node("n-rec", "Recursion", 0.5, "learning", { description: "Self-reference." }),
    node("n-trees", "Trees", 0, "unexplored", { description: "Hierarchies." }),
    node("n-vec", "Vectors", 0.9, "mastered"),
    node("n-loops", "Loops", 0.2, "struggling", { description: "Repetition." }),
  ],
  edges: [
    { source: "root-c1", target: "n-rec", strength: 0.5 },
    { source: "root-c1", target: "n-trees", strength: 0.5 },
    { source: "root-c1", target: "n-vec", strength: 0.5 },
    { source: "n-rec", target: "n-trees", strength: 0.5 },
  ],
  stats: {},
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function renderLearn() {
  return render(
    <ToastProvider>
      <Learn />
    </ToastProvider>,
  );
}

const log = () => screen.getByTestId("tutor-messages");
const rail = () => document.querySelector(".learn-map-rail") as HTMLElement;
const aside = () => document.querySelector("aside") as HTMLElement;
const tab = () => screen.getByRole("button", { name: "Toggle knowledge map" });

async function openSession(id: string, text: string) {
  fireEvent.click(await screen.findByTestId(`tutor-session-resume-${id}`));
  await screen.findByTestId("tutor-messages");
  await waitFor(() => expect(log()).toHaveTextContent(text));
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.search = "";
  env.mobile = false;
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = StubResizeObserver;
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  localStorage.clear();
  sessionStorage.clear();
  api.getSessions.mockResolvedValue({
    sessions: [sessionRow("sess-a", "Recursion"), sessionRow("sess-vec", "Vectors", 1), sessionRow("sess-empty", "Empty", 0)],
  });
  api.getCourses.mockResolvedValue({ courses: [COURSE] });
  api.getGraph.mockResolvedValue(GRAPH);
  api.describeConcept.mockResolvedValue({ description: "" });
  api.resumeSession.mockImplementation(async (id: string) => {
    if (id === "sess-a") return SESSION_A;
    if (id === "sess-free") return SESSION_FREE;
    return { session: { id, topic: "Vectors", mode: "socratic", course_id: "c1" }, messages: [{ role: "assistant", content: "Dot products." }] };
  });
  api.streamChat.mockResolvedValue({ reply: "stream reply" });
  api.sendChat.mockResolvedValue({ reply: "json reply" });
  api.startSessionStream.mockResolvedValue({ session_id: "sess-new", reply: "Welcome." });
  api.startSession.mockResolvedValue({ session_id: "sess-new", initial_message: "Welcome (json)." });
  api.learnAction.mockResolvedValue({ reply: "Here is a hint.", graph_update: null });
  api.switchMode.mockResolvedValue({ reply: "Switched." });
  api.endSession.mockResolvedValue({ summary: null });
  api.renameSession.mockResolvedValue({});
  api.deleteSession.mockResolvedValue({});
  api.addGraphNode.mockResolvedValue({ node: { id: "n-real", concept_name: "Graphs", course_id: "c1", mastery_score: 0, mastery_tier: "unexplored" }, already_existed: false });
  api.deleteGraphNode.mockResolvedValue({ deleted: true });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ───────────────────────────────── entry screen ─────────────────────────────────

describe("entry screen", () => {
  it("lists only sessions with messages, offers the enrolled courses, and gates Start on a topic", async () => {
    renderLearn();
    expect(await screen.findByTestId("tutor-session-resume-sess-a")).toHaveTextContent("Recursion");
    expect(screen.getByTestId("tutor-session-resume-sess-vec")).toHaveTextContent("socratic · 1 msg");
    expect(screen.getByTestId("tutor-session-resume-sess-a")).toHaveTextContent("socratic · 2 msgs");
    expect(screen.queryByTestId("tutor-session-resume-sess-empty")).toBeNull();
    expect(screen.queryByText("No recent sessions yet.")).toBeNull();
    expect(screen.getByText("Start a session")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-start")).toBeDisabled();

    fireEvent.click(screen.getByTestId("tutor-topic-picker"));
    fireEvent.click(await screen.findByRole("button", { name: /^Trees/ }));
    expect(screen.getByTestId("tutor-topic-picker")).toHaveTextContent("Trees");
    expect(screen.getByTestId("tutor-start")).not.toBeDisabled();
  });

  it("says so when there are no recent sessions", async () => {
    api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-empty", "Empty", 0)] });
    renderLearn();
    expect(await screen.findByText("No recent sessions yet.")).toBeInTheDocument();
  });

  it("a ?topic=&mode=&course= link pre-fills the picker and starts the streamed greeting with those values", async () => {
    nav.search = "topic=Trees&mode=teachback&course=c1";
    const stream = deferred<{ session_id: string; reply: string }>();
    let handlers: { onToken: (d: string) => void; onProgress: (s: unknown) => void } | undefined;
    api.startSessionStream.mockImplementation((...args: unknown[]) => {
      handlers = args[6] as typeof handlers;
      return stream.promise;
    });
    renderLearn();
    await screen.findByTestId("tutor-session-resume-sess-a");
    expect(screen.getByTestId("tutor-topic-picker")).toHaveTextContent("Trees");
    fireEvent.click(screen.getByTestId("tutor-start"));

    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalled());
    const call = api.startSessionStream.mock.calls[0];
    expect(call.slice(0, 5)).toEqual(["u1", "Trees", "teachback", true, "c1"]);
    expect(await screen.findByTestId("tutor-stop")).toBeInTheDocument();
    act(() => handlers!.onProgress("search_course_materials"));
    expect(await screen.findByText("Searching your course materials…")).toBeInTheDocument();
    act(() => handlers!.onProgress("unknown_step"));
    expect(screen.getByText("Searching your course materials…")).toBeInTheDocument();
    act(() => handlers!.onToken("Hello "));
    act(() => handlers!.onToken("there"));
    await waitFor(() => expect(log()).toHaveTextContent("Hello there"));

    await act(async () => { stream.resolve({ session_id: "sess-new", reply: "Hello there, final." }); });
    await waitFor(() => expect(log()).toHaveTextContent("Hello there, final."));
    expect(screen.queryByTestId("tutor-stop")).toBeNull();
    expect(screen.getByText("CS101 · Teach-back Tutor · 1 Messages")).toBeInTheDocument();
  });

  it("the entry-screen mode toggle writes the mode into the URL", async () => {
    renderLearn();
    await screen.findByTestId("tutor-session-resume-sess-a");
    nav.replace.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/learn?mode=expository", { scroll: false }));
  });

  it("renames a session row optimistically", async () => {
    renderLearn();
    await screen.findByTestId("tutor-session-resume-sess-a");
    fireEvent.click(screen.getAllByRole("button", { name: "Rename session" })[0]);
    const input = screen.getByRole("textbox", { name: "Session name" });
    fireEvent.change(input, { target: { value: "Recursion II" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByTestId("tutor-session-resume-sess-a")).toHaveTextContent("Recursion II");
    expect(api.renameSession).toHaveBeenCalledWith("sess-a", "u1", "Recursion II");
  });

  it("a failed rename resyncs the list from the server and toasts", async () => {
    api.renameSession.mockRejectedValue(new Error("rename broke"));
    renderLearn();
    await screen.findByTestId("tutor-session-resume-sess-a");
    api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-a", "Server name")] });
    fireEvent.click(screen.getAllByRole("button", { name: "Rename session" })[0]);
    const input = screen.getByRole("textbox", { name: "Session name" });
    fireEvent.change(input, { target: { value: "Recursion II" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("rename broke")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("tutor-session-resume-sess-a")).toHaveTextContent("Server name"));
    expect(screen.queryByTestId("tutor-session-resume-sess-vec")).toBeNull();
  });

  it("deletes a session row after the confirm click", async () => {
    renderLearn();
    await screen.findByTestId("tutor-session-resume-sess-a");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete session" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(screen.queryByTestId("tutor-session-resume-sess-a")).toBeNull());
    expect(api.deleteSession).toHaveBeenCalledWith("sess-a", "u1");
    expect(await screen.findByText("Session deleted.")).toBeInTheDocument();
  });
});

// ───────────────────────────────── resume loading ─────────────────────────────────

describe("resume deep link", () => {
  it("shows the loading state (not the picker) until the resume lands", async () => {
    nav.search = "resume=sess-a";
    const late = deferred<typeof SESSION_A>();
    api.resumeSession.mockReturnValue(late.promise);
    renderLearn();
    expect(screen.getByTestId("tutor-resume-loading")).toHaveTextContent("Loading…");
    expect(screen.queryByTestId("tutor-start")).toBeNull();
    await act(async () => { late.resolve(SESSION_A); });
    await waitFor(() => expect(log()).toHaveTextContent("A function calling itself."));
    expect(screen.queryByTestId("tutor-resume-loading")).toBeNull();
  });

  it("the legacy ?session= param resumes too", async () => {
    nav.search = "session=sess-a";
    renderLearn();
    await waitFor(() => expect(log()).toHaveTextContent("A function calling itself."));
    expect(api.resumeSession).toHaveBeenCalledWith("sess-a");
  });
});

// ───────────────────────────────── chat header ─────────────────────────────────

describe("active session header", () => {
  it("shows course code, mode name and message count, and a two-click End session", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(screen.getByText("CS101 · Socratic Tutor · 2 Messages")).toBeInTheDocument();
    const end = screen.getByRole("button", { name: "End session" });
    expect(end).toHaveClass("btn", "btn--sm");
    expect(end).not.toHaveClass("btn--danger");
    expect(end).toHaveAttribute("title", "End session");
    fireEvent.click(end);
    const confirm = screen.getByRole("button", { name: "Confirm end" });
    expect(confirm).toHaveClass("btn--danger");
    expect(confirm).toHaveAttribute("title", "Click again to confirm");
  });

  it("a session with no course drops the course prefix", async () => {
    api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-free", "Free topic")] });
    renderLearn();
    await openSession("sess-free", "Free-form.");
    expect(screen.getByText("Expository Tutor · 1 Messages")).toBeInTheDocument();
  });

  it("the active mode pill is highlighted", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(screen.getByRole("button", { name: "Socratic" })).toHaveStyle({ background: "var(--accent)", color: "var(--accent-fg)" });
    expect(screen.getByRole("button", { name: "Expository" })).toHaveStyle({ background: "var(--bg-subtle)", color: "var(--text-dim)" });
  });

  it("Back to Learn leaves the session and rewrites the URL to the mode only", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    nav.replace.mockClear();
    fireEvent.click(screen.getByTestId("tutor-back-to-learn"));
    expect(await screen.findByTestId("tutor-start")).toBeInTheDocument();
    expect(nav.replace).toHaveBeenCalledWith("/learn?mode=socratic", { scroll: false });
    expect(screen.getByTestId("tutor-topic-picker")).toHaveTextContent("Pick or type a topic…");
  });

  it("a streamed reply's tool progress shows as the waiting status, then the reply lands", async () => {
    const turn = deferred<{ reply: string }>();
    let handlers: { onProgress: (s: unknown) => void } | undefined;
    api.streamChat.mockImplementation((...args: unknown[]) => {
      handlers = args[6] as typeof handlers;
      return turn.promise;
    });
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "more" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await waitFor(() => expect(handlers).toBeDefined());
    expect(api.streamChat.mock.calls[0].slice(0, 6)).toEqual(["sess-a", "u1", "more", "socratic", true, "fast"]);
    act(() => handlers!.onProgress("read_session_history_tool"));
    expect(await screen.findByText("Reviewing this conversation…")).toBeInTheDocument();
    await act(async () => { turn.resolve({ reply: "Here you go." }); });
    await waitFor(() => expect(log()).toHaveTextContent("Here you go."));
    expect(screen.queryByText("Reviewing this conversation…")).toBeNull();
    expect(screen.getByText("CS101 · Socratic Tutor · 4 Messages")).toBeInTheDocument();
  });
});

// ───────────────────────────────── summary modal ─────────────────────────────────

describe("session summary", () => {
  const SUMMARY = {
    concepts_covered: ["Recursion"], mastery_changes: [], new_connections: [],
    time_spent_minutes: 5, recommended_next: ["Trees"],
  };

  async function endWithSummary() {
    api.endSession.mockResolvedValue({ summary: SUMMARY });
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByRole("button", { name: "End session" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm end" }));
    await screen.findByText("Recommended next");
  }

  it("Done closes the summary and returns to an empty picker", async () => {
    await endWithSummary();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByTestId("tutor-start")).toBeDisabled();
    expect(screen.queryByText("Recommended next")).toBeNull();
  });

  it("a recommended concept pre-fills the picker and the URL", async () => {
    await endWithSummary();
    nav.replace.mockClear();
    fireEvent.click(within(screen.getByText("Recommended next").parentElement!).getByRole("button", { name: /Trees/ }));
    expect(await screen.findByTestId("tutor-start")).not.toBeDisabled();
    expect(screen.getByTestId("tutor-topic-picker")).toHaveTextContent("Trees");
    expect(nav.replace).toHaveBeenCalledWith("/learn?topic=Trees&mode=socratic", { scroll: false });
  });
});

// ───────────────────────────────── knowledge-map rail ─────────────────────────────────

describe("knowledge-map rail", () => {
  it("header, legend, and the focus card for the session's own concept", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    const r = within(rail());
    expect(r.getByText("Knowledge map")).toBeInTheDocument();
    expect(r.getByText("CS101")).toBeInTheDocument();
    for (const l of ["Mastered", "In progress", "Needs work", "Not started"]) {
      expect(r.getAllByText(l).length).toBeGreaterThan(0);
    }
    expect(r.getByText("Focused concept")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent("Self-reference.");
    expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-rec");
    // Already chatting about it: no switch button; Remove takes the row.
    expect(r.queryByRole("button", { name: /Start session|Resume session/ })).toBeNull();
    expect(r.getByTitle("Remove concept")).toHaveStyle({ flex: "1" });
  });

  it("'In this branch' lists the focused concept's neighbours and 'Elsewhere' the rest of the course", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    const branch = within(screen.getByText("In this branch").parentElement!);
    expect(branch.getAllByRole("button").map(b => b.title)).toEqual(["Focus Trees"]);
    const elsewhere = within(screen.getByText("Elsewhere in course").parentElement!);
    expect(elsewhere.getAllByRole("button").map(b => b.textContent)).toEqual(["Vectors", "Loops"]);

    fireEvent.click(elsewhere.getByRole("button", { name: "Vectors" }));
    expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-vec");
    expect(within(rail()).getByText("Mastered", { selector: "span[style*='padding']" })).toBeInTheDocument();
  });

  it("clicking another node focuses it without touching the chat; its switch button resumes or starts", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByTestId("kg-node-n-trees"));
    expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent("Hierarchies.");
    expect(within(rail()).getByRole("button", { name: /Start session/ })).toBeInTheDocument();
    expect(within(rail()).getByTitle("Remove concept")).not.toHaveStyle({ flex: "1" });

    fireEvent.click(screen.getByTestId("kg-node-n-vec"));
    fireEvent.click(within(rail()).getByRole("button", { name: /Resume session/ }));
    await waitFor(() => expect(log()).toHaveTextContent("Dot products."));
    expect(api.resumeSession).toHaveBeenLastCalledWith("sess-vec");
  });

  it("a double click on a node switches the session to it", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByTestId("kg-node-n-trees"));
    fireEvent.click(screen.getByTestId("kg-node-n-trees"));
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalled());
    expect(api.startSessionStream.mock.calls[0][1]).toBe("Trees");
  });

  it("clicking the subject root does nothing", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByTestId("kg-node-root-c1"));
    expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-rec");
  });

  it("a concept without a stored description gets the AI blurb, else the connected-concepts sentence", async () => {
    api.describeConcept.mockResolvedValueOnce({ description: "Magnitude and direction." });
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByTestId("kg-node-n-vec"));
    await waitFor(() => expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent("Magnitude and direction."));
    expect(api.describeConcept).toHaveBeenCalledWith("u1", "Vectors", "Intro CS");
  });

  it("falls back to the connected-concepts sentence when no description is available", async () => {
    api.getGraph.mockResolvedValue({
      ...GRAPH,
      nodes: GRAPH.nodes.map(n => (n.id === "n-rec" ? { ...n, description: undefined } : n)),
    });
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    await waitFor(() => expect(api.describeConcept).toHaveBeenCalledWith("u1", "Recursion", "Intro CS"));
    expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent(
      "2 connected concepts · this is where your session is anchored on the course map.",
    );
  });

  it("a topic that is no concept anchors the card on the course", async () => {
    api.resumeSession.mockResolvedValue({
      session: { id: "sess-x", topic: "Exam prep", mode: "socratic", course_id: "c1" },
      messages: [{ role: "assistant", content: "Let's prep." }],
    });
    api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-x", "Exam prep")] });
    renderLearn();
    await openSession("sess-x", "Let's prep.");
    const r = within(rail());
    expect(r.getByText("Focused course")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent(
      "4 concepts in this course · pick one to anchor your session.",
    );
    expect(r.queryByTitle("Remove concept")).toBeNull();
    // Branch falls back to the course's concepts by mastery.
    const branch = within(screen.getByText("In this branch").parentElement!);
    expect(branch.getAllByRole("button").map(b => b.title)).toEqual(["Focus Vectors", "Focus Recursion", "Focus Loops", "Focus Trees"]);
  });

  it("a ?suggest= concept takes the focus", async () => {
    nav.search = "suggest=loops";
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-loops");
    expect(screen.getByTestId("tutor-focus-concept-description")).toHaveTextContent("Repetition.");
  });

  it("the add-concept composer: Add disabled until typed, Escape cancels, Add focuses the new node", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByRole("button", { name: /Add concept/ }));
    const add = screen.getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    expect(add).toHaveStyle({ cursor: "not-allowed" });
    const input = screen.getByPlaceholderText("New concept name…");
    fireEvent.change(input, { target: { value: "Heaps" } });
    expect(add).not.toBeDisabled();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByPlaceholderText("New concept name…")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Add concept/ }));
    expect(screen.getByPlaceholderText("New concept name…")).toHaveValue("");
    fireEvent.change(screen.getByPlaceholderText("New concept name…"), { target: { value: "Heaps" } });
    fireEvent.keyDown(screen.getByPlaceholderText("New concept name…"), { key: "Enter" });
    await waitFor(() => expect(api.addGraphNode).toHaveBeenCalledWith("u1", { concept_name: "Heaps", course_id: "c1", anchor_node_id: "n-rec" }));
    await waitFor(() => expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-real"));
  });

  it("a failed add is rolled back with a toast", async () => {
    api.addGraphNode.mockRejectedValue(new Error("nope"));
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.click(screen.getByRole("button", { name: /Add concept/ }));
    fireEvent.change(screen.getByPlaceholderText("New concept name…"), { target: { value: "Heaps" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Couldn't save the concept — it was removed.")).toBeInTheDocument();
    expect(screen.queryByText("Heaps")).toBeNull();
    expect(screen.getByTestId("kg")).toHaveAttribute("data-highlight", "n-rec");
  });
});

// ───────────────────────────────── rail collapse tab ─────────────────────────────────

describe("rail collapse tab", () => {
  it("is open by default; keyboard toggles it and the choice persists", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(tab()).toHaveAttribute("aria-expanded", "true");
    expect(tab()).toHaveAttribute("title", "Collapse knowledge map");
    expect(aside()).toHaveStyle({ width: "400px" });
    await waitFor(() => expect(localStorage.getItem("sapling_learn_rail_open")).toBe("1"));

    fireEvent.keyDown(tab(), { key: "Enter" });
    expect(tab()).toHaveAttribute("aria-expanded", "false");
    expect(tab()).toHaveAttribute("title", "Show knowledge map");
    expect(aside()).toHaveStyle({ width: "0px" });
    await waitFor(() => expect(localStorage.getItem("sapling_learn_rail_open")).toBe("0"));
    fireEvent.keyDown(tab(), { key: " " });
    expect(tab()).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(tab(), { key: "a" });
    expect(tab()).toHaveAttribute("aria-expanded", "true");
  });

  it("restores a stored collapsed state", async () => {
    localStorage.setItem("sapling_learn_rail_open", "0");
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(tab()).toHaveAttribute("aria-expanded", "false");
  });

  it("a press without movement toggles; a drag past halfway snaps closed; a cancel changes nothing", async () => {
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    fireEvent.pointerDown(tab(), { pointerId: 1, clientX: 100 });
    fireEvent.pointerUp(tab(), { pointerId: 1, clientX: 101 });
    expect(tab()).toHaveAttribute("aria-expanded", "false");
    fireEvent.pointerDown(tab(), { pointerId: 1, clientX: 100 });
    fireEvent.pointerUp(tab(), { pointerId: 1, clientX: 100 });
    expect(tab()).toHaveAttribute("aria-expanded", "true");

    fireEvent.pointerDown(tab(), { pointerId: 2, clientX: 100 });
    fireEvent.pointerMove(tab(), { pointerId: 2, clientX: 350 });
    expect(aside()).toHaveStyle({ width: "150px", transition: "none" });
    expect(tab()).toHaveStyle({ right: "150px", cursor: "grabbing" });
    // A stray pointer is ignored.
    fireEvent.pointerMove(tab(), { pointerId: 9, clientX: 100 });
    expect(aside()).toHaveStyle({ width: "150px" });
    fireEvent.pointerUp(tab(), { pointerId: 2, clientX: 350 });
    expect(tab()).toHaveAttribute("aria-expanded", "false");
    expect(aside()).toHaveStyle({ width: "0px" });

    fireEvent.pointerDown(tab(), { pointerId: 3, clientX: 300 });
    fireEvent.pointerMove(tab(), { pointerId: 3, clientX: 100 });
    expect(aside()).toHaveStyle({ width: "200px" });
    fireEvent.pointerCancel(tab(), { pointerId: 3, clientX: 100 });
    expect(tab()).toHaveAttribute("aria-expanded", "false");
    expect(aside()).toHaveStyle({ width: "0px" });

    fireEvent.pointerDown(tab(), { pointerId: 4, clientX: 300 });
    fireEvent.pointerMove(tab(), { pointerId: 4, clientX: 50 });
    fireEvent.pointerUp(tab(), { pointerId: 4, clientX: 50 });
    expect(tab()).toHaveAttribute("aria-expanded", "true");
  });
});

// ───────────────────────────────── mobile ─────────────────────────────────

describe("mobile", () => {
  it("shows one pane at a time behind chat/graph tabs, with no collapse tab", async () => {
    env.mobile = true;
    renderLearn();
    await openSession("sess-a", "A function calling itself.");
    expect(screen.queryByRole("button", { name: "Toggle knowledge map" })).toBeNull();
    expect(rail()).toBeNull();
    const chatTab = screen.getByRole("button", { name: "chat" });
    expect(chatTab).toHaveStyle({ color: "var(--accent)" });

    fireEvent.click(screen.getByRole("button", { name: "graph" }));
    expect(screen.queryByTestId("tutor-messages")).toBeNull();
    expect(rail()).not.toBeNull();
    expect(aside()).toHaveStyle({ width: "100%" });
    expect(screen.getByRole("button", { name: "graph" })).toHaveStyle({ color: "var(--accent)" });

    fireEvent.click(chatTab);
    expect(screen.getByTestId("tutor-messages")).toBeInTheDocument();
  });

  it("the entry screen stacks to one column", async () => {
    env.mobile = true;
    renderLearn();
    const start = await screen.findByTestId("tutor-start");
    const grid = start.closest(".card")!.parentElement!;
    expect(grid).toHaveStyle({ gridTemplateColumns: "1fr" });
  });
});
