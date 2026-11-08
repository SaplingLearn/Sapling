// @vitest-environment jsdom
/**
 * The tutor screen's session lifecycle (#762, workstream E2 of the implicit
 * state-machine audit). Every async path on /learn — start, resume, send,
 * hint/confused/skip, mode switch, and the knowledge-map add/remove — used to
 * apply its result to WHATEVER session happened to be on screen when it
 * settled. These tests drive the real screen through the races the audit
 * found and pin that a late result only ever lands in the session that asked
 * for it.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act, within } from "@testing-library/react";

// ── Navigation: a STATIC searchParams snapshot. `router.replace` is recorded
// but never feeds back into `useSearchParams`, which is exactly the window a
// real Next transition leaves open (the URL write lands after the render
// that reads the params).
const nav = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
// These pin the legacy tutor's session state: the learning loop's kill-switch
// path (PKG-14b), which Learn renders when the loop status probe says inactive.
vi.mock("../learn/useLoopStatus", () => ({
  useLoopStatus: () => ({ status: false, retry: () => {} }),
}));
vi.mock("@/lib/useActiveSemester", () => ({
  useActiveSemester: () => ["", () => {}, true],
  courseInTerm: () => true,
}));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
// The 3D graph is irrelevant here; a node is a button that reports its click.
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: ({ nodes, onNodeClick }: { nodes: { id: string; name: string }[]; onNodeClick?: (n: unknown) => void }) => (
    <div>
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
import crisisFixture from "@/test-utils/crisisSupport.json";
import { ChatStreamError } from "@/lib/api";
import { __resetFeedbackPacingForTests, currentLearningSession, feedbackHeld } from "@/lib/feedbackPacing";

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
const SESSION_B = {
  session: { id: "sess-b", topic: "Vectors", mode: "socratic", course_id: "c1" },
  messages: [{ role: "assistant", content: "What is a dot product?" }],
};

function sessionRow(id: string, topic: string) {
  return {
    id, topic, mode: "socratic", course_id: "c1", started_at: "2026-11-01T00:00:00Z",
    ended_at: null, message_count: 2, is_active: true,
  };
}

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "CS101", course_name: "Intro CS",
  school: "", department: "", color: null, nickname: null, node_count: 3,
  enrolled_at: "2026-09-01T00:00:00Z", term: "", terms: [],
};

const GRAPH = {
  nodes: [
    { id: "root-c1", concept_name: "Intro CS", subject: "Intro CS", course_id: "c1", is_subject_root: true, mastery_score: 0, mastery_tier: "subject_root", times_studied: 0, last_studied_at: null },
    { id: "n-rec", concept_name: "Recursion", subject: "Intro CS", course_id: "c1", mastery_score: 0.5, mastery_tier: "learning", times_studied: 1, last_studied_at: null, description: "Self-reference." },
    { id: "n-trees", concept_name: "Trees", subject: "Intro CS", course_id: "c1", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0, last_studied_at: null, description: "Hierarchies." },
  ],
  edges: [
    { source: "root-c1", target: "n-rec", strength: 0.5 },
    { source: "root-c1", target: "n-trees", strength: 0.5 },
  ],
  stats: {},
};

/** A promise whose settlement the test controls. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const httpError = (status: number, message = `HTTP ${status}`) =>
  Object.assign(new Error(message), { status });

// The backend's typed refusal for a turn on an ended session (#761/E1): a
// 409 whose envelope carries `error.code: "SESSION_ENDED"`. `fetchJSON`
// surfaces it as `ApiError.code`; `streamSSE` attaches the same `code`.
const ENDED_DETAIL = "This tutoring session has ended. Start a new session to keep learning.";
const sessionEnded = () =>
  Object.assign(new Error(JSON.stringify({ detail: ENDED_DETAIL, error: { code: "SESSION_ENDED" } })), {
    status: 409,
    code: "SESSION_ENDED",
  });

const TURN_ID = /^[A-Za-z0-9_\-]{8,128}$/;

function renderLearn() {
  return render(
    <ToastProvider>
      <Learn />
    </ToastProvider>,
  );
}

const log = () => screen.getByTestId("tutor-messages");

/** Opens a session from the entry screen's Recent sessions list. */
async function openSession(id: "sess-a" | "sess-b") {
  fireEvent.click(await screen.findByTestId(`tutor-session-resume-${id}`));
  await screen.findByTestId("tutor-messages");
  await waitFor(() =>
    expect(log()).toHaveTextContent(id === "sess-a" ? "A function calling itself." : "What is a dot product?"),
  );
}

/** Back to the picker, then into the other session. */
async function hopTo(id: "sess-a" | "sess-b") {
  fireEvent.click(screen.getByTestId("tutor-back-to-learn"));
  await openSession(id);
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.search = "";
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = StubResizeObserver;
  localStorage.clear();
  sessionStorage.clear();
  api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-a", "Recursion"), sessionRow("sess-b", "Vectors")] });
  api.getCourses.mockResolvedValue({ courses: [COURSE] });
  api.getGraph.mockResolvedValue(GRAPH);
  api.describeConcept.mockResolvedValue({ description: "" });
  api.resumeSession.mockImplementation(async (id: string) => (id === "sess-a" ? SESSION_A : SESSION_B));
  api.streamChat.mockResolvedValue({ reply: "stream reply" });
  api.sendChat.mockResolvedValue({ reply: "json reply" });
  api.startSessionStream.mockResolvedValue({ session_id: "sess-new", reply: "Welcome to Trees." });
  api.startSession.mockResolvedValue({ session_id: "sess-new", initial_message: "Welcome (json)." });
  api.learnAction.mockResolvedValue({ reply: "Here is a hint.", graph_update: null });
  api.switchMode.mockResolvedValue({ reply: "Switched to expository." });
  api.endSession.mockResolvedValue({ summary: null });
  api.addGraphNode.mockResolvedValue({ node: { id: "n-real", concept_name: "Graphs", course_id: "c1", mastery_score: 0, mastery_tier: "unexplored" }, already_existed: false });
  api.deleteGraphNode.mockResolvedValue({ deleted: true });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ─────────────────────────── switching concepts ───────────────────────────

describe("switchToConcept (start a new session from the map)", () => {
  async function startTreesFromMap() {
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByRole("button", { name: /Start session/ }));
  }

  it("a failed start leaves no session behind — back to the picker, not the OLD session under the new title", async () => {
    api.startSessionStream.mockRejectedValue(new ChatStreamError("tutor down", undefined, false));
    await startTreesFromMap();

    expect(await screen.findByTestId("tutor-start")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-messages")).toBeNull();
    // Nothing can be sent into sess-a by accident.
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("a stopped start leaves no session behind either", async () => {
    let signal: AbortSignal | undefined;
    api.startSessionStream.mockImplementation((...args: unknown[]) => {
      signal = (args[6] as { signal: AbortSignal }).signal;
      return new Promise((_, reject) => signal!.addEventListener("abort", () => reject(new Error("aborted"))));
    });
    await startTreesFromMap();
    await waitFor(() => expect(signal).toBeDefined());

    fireEvent.click(screen.getByTestId("tutor-stop"));
    expect(await screen.findByTestId("tutor-start")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-messages")).toBeNull();
  });
});

// ──────────────────────── resume vs. an in-flight start ────────────────────────

describe("resume supersedes an in-flight start", () => {
  it("aborts the start's stream, and a late (unabortable) JSON start never overwrites the resumed session", async () => {
    let streamSignal: AbortSignal | undefined;
    api.startSessionStream.mockImplementation(async (...args: unknown[]) => {
      streamSignal = (args[6] as { signal: AbortSignal }).signal;
      throw new Error("stream refused"); // Rung 3 → the JSON start below
    });
    const lateStart = deferred<{ session_id: string; initial_message: string }>();
    api.startSession.mockReturnValue(lateStart.promise);

    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByRole("button", { name: /Start session/ }));
    await waitFor(() => expect(api.startSession).toHaveBeenCalled());
    expect(streamSignal).toBeDefined();

    // While the JSON start is still out: pick a different session.
    await hopTo("sess-b");

    await act(async () => {
      lateStart.resolve({ session_id: "sess-late", initial_message: "Welcome (late)." });
    });

    expect(log()).toHaveTextContent("What is a dot product?");
    expect(log()).not.toHaveTextContent("Welcome (late).");
    // …and the composer still talks to sess-b, not the late session.
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "hello b" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await waitFor(() => expect(api.streamChat).toHaveBeenCalled());
    expect(api.streamChat.mock.calls[0][0]).toBe("sess-b");
  });

  it("a deep-link resume aborts an in-flight streamed start", async () => {
    let signal: AbortSignal | undefined;
    api.startSessionStream.mockImplementation((...args: unknown[]) => {
      signal = (args[6] as { signal: AbortSignal }).signal;
      return new Promise((_, reject) => signal!.addEventListener("abort", () => reject(new Error("aborted"))));
    });
    const view = renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByRole("button", { name: /Start session/ }));
    await waitFor(() => expect(signal).toBeDefined());

    nav.search = "resume=sess-b";
    view.rerender(
      <ToastProvider>
        <Learn />
      </ToastProvider>,
    );

    await waitFor(() => expect(signal!.aborted).toBe(true));
    await waitFor(() => expect(log()).toHaveTextContent("What is a dot product?"));
  });
});

// ───────────────────────────── hint / confused / skip ─────────────────────────────

describe("handleAction", () => {
  it("drops a late reply when the session changed while it was in flight", async () => {
    const late = deferred<{ reply: string; graph_update: null }>();
    api.learnAction.mockReturnValue(late.promise);
    renderLearn();
    await openSession("sess-a");

    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    await hopTo("sess-b");
    await act(async () => { late.resolve({ reply: "A hint for sess-a.", graph_update: null }); });

    expect(log()).not.toHaveTextContent("A hint for sess-a.");
    expect(log()).not.toHaveTextContent("(Requested a hint)");
    // The composer is usable in the new session.
    expect(screen.getByTestId("tutor-action-hint")).not.toBeDisabled();
  });

  it("shows its wait the same way a streamed turn does — a Thinking bubble, not a placeholder message — and offers no Stop it can't honour", async () => {
    const late = deferred<{ reply: string; graph_update: null }>();
    api.learnAction.mockReturnValue(late.promise);
    renderLearn();
    await openSession("sess-a");

    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    expect(await within(log()).findByText("Thinking…")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-stop")).toBeNull();

    await act(async () => { late.resolve({ reply: "Here is a hint.", graph_update: null }); });
    expect(log()).toHaveTextContent("Here is a hint.");
    expect(within(log()).queryByText("Thinking…")).toBeNull();
  });

  it("on failure removes exactly its own label — not whatever the last two messages are", async () => {
    const late = deferred<{ reply: string; graph_update: null }>();
    api.learnAction.mockReturnValue(late.promise);
    renderLearn();
    await openSession("sess-a");

    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    // Another reply lands while the action is still out (a mode switch).
    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    await waitFor(() => expect(log()).toHaveTextContent("Switched to expository."));

    await act(async () => { late.reject(new Error("action broke")); });

    expect(log()).toHaveTextContent("Switched to expository.");
    expect(log()).toHaveTextContent("A function calling itself.");
    expect(log()).not.toHaveTextContent("(Requested a hint)");
  });
});

// ─────────────────────────────── mode switch ───────────────────────────────

describe("handleModeSwitch", () => {
  it("drops a late reply when the session changed while it was in flight", async () => {
    const late = deferred<{ reply: string }>();
    api.switchMode.mockReturnValue(late.promise);
    renderLearn();
    await openSession("sess-a");

    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    await hopTo("sess-b");
    await act(async () => { late.resolve({ reply: "Switched (sess-a)." }); });

    expect(log()).not.toHaveTextContent("Switched (sess-a).");
  });

  it("a failed switch rolls the URL back with the mode, even before the params caught up", async () => {
    nav.search = "mode=socratic";
    api.switchMode.mockRejectedValue(new Error("nope"));
    renderLearn();
    await openSession("sess-a");
    nav.replace.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(expect.stringContaining("mode=expository"), expect.anything()));
    await waitFor(() => expect(nav.replace).toHaveBeenLastCalledWith(expect.stringContaining("mode=socratic"), expect.anything()));
    // The Socratic pill is the active one again.
    expect(screen.getByRole("button", { name: "Socratic" })).toHaveStyle({ background: "var(--accent)" });
  });

  it("an older failed switch does not roll back a newer one", async () => {
    const first = deferred<{ reply: string }>();
    api.switchMode.mockReturnValueOnce(first.promise).mockResolvedValueOnce({ reply: "Now teach-back." });
    renderLearn();
    await openSession("sess-a");

    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    fireEvent.click(screen.getByRole("button", { name: "Teach-back" }));
    await waitFor(() => expect(log()).toHaveTextContent("Now teach-back."));
    await act(async () => { first.reject(new Error("late failure")); });

    expect(screen.getByRole("button", { name: "Teach-back" })).toHaveStyle({ background: "var(--accent)" });
  });
});

// ──────────────────────────── a session that ended ────────────────────────────

describe("a turn on a session the server has ended (409)", () => {
  it("send: shows the session-ended state and offers a new session instead of an error bubble", async () => {
    api.streamChat.mockRejectedValue(sessionEnded());
    renderLearn();
    await openSession("sess-a");

    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "one more" } });
    fireEvent.click(screen.getByTestId("tutor-send"));

    expect(await screen.findByTestId("tutor-session-ended")).toBeInTheDocument();
    // No JSON retry of a turn that can never succeed, no interrupted+Retry bubble.
    expect(api.sendChat).not.toHaveBeenCalled();
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
    expect(log()).not.toHaveTextContent("one more");
    expect(screen.getByTestId("tutor-input")).toBeDisabled();

    fireEvent.click(screen.getByTestId("tutor-session-ended-new"));
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalled());
    expect(api.startSessionStream.mock.calls[0][1]).toBe("Recursion");
  });

  it("action: same state", async () => {
    api.learnAction.mockRejectedValue(sessionEnded());
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    expect(await screen.findByTestId("tutor-session-ended")).toBeInTheDocument();
    expect(log()).not.toHaveTextContent("(Requested a hint)");
  });

  it("mode switch: same state", async () => {
    api.switchMode.mockRejectedValue(sessionEnded());
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    expect(await screen.findByTestId("tutor-session-ended")).toBeInTheDocument();
  });

  it("the ended state does not follow the student into another session", async () => {
    api.learnAction.mockRejectedValue(sessionEnded());
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    await screen.findByTestId("tutor-session-ended");
    await hopTo("sess-b");
    expect(screen.queryByTestId("tutor-session-ended")).toBeNull();
  });

  it("a 409 with no code still reads as ended (an older backend)", async () => {
    api.learnAction.mockRejectedValue(httpError(409));
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    expect(await screen.findByTestId("tutor-session-ended")).toBeInTheDocument();
  });

  it("a 409 with a DIFFERENT code is an ordinary error, not the ended state", async () => {
    api.learnAction.mockRejectedValue(
      Object.assign(new Error('{"detail":"Something else conflicted."}'), { status: 409, code: "OTHER_CONFLICT" }),
    );
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByTestId("tutor-action-hint"));
    expect(await screen.findByText("Something else conflicted.")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-session-ended")).toBeNull();
    expect(log()).not.toHaveTextContent("(Requested a hint)");
  });

  it("mode switch: a 422 'Unknown tutor mode' is surfaced as a normal error and rolled back", async () => {
    api.switchMode.mockRejectedValue(httpError(422, '{"detail":"Unknown tutor mode"}'));
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    expect(await screen.findByText("Unknown tutor mode")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-session-ended")).toBeNull();
    expect(screen.getByRole("button", { name: "Socratic" })).toHaveStyle({ background: "var(--accent)" });
  });
});

describe("resuming a session that has already ended", () => {
  it("opens it read-only: the transcript, the ended banner, a disabled composer, and no turn ever sent", async () => {
    api.resumeSession.mockImplementation(async (id: string) =>
      id === "sess-a"
        ? { ...SESSION_A, session: { ...SESSION_A.session, ended_at: "2026-11-01T01:00:00Z" } }
        : SESSION_B,
    );
    renderLearn();
    await openSession("sess-a");

    expect(screen.getByTestId("tutor-session-ended")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-input")).toBeDisabled();
    expect(screen.getByTestId("tutor-action-hint")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Expository" }));
    expect(api.switchMode).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("tutor-session-ended-new"));
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalled());
    expect(api.startSessionStream.mock.calls[0][1]).toBe("Recursion");
  });

  it("an open session resumes as usual", async () => {
    renderLearn();
    await openSession("sess-a");
    expect(screen.queryByTestId("tutor-session-ended")).toBeNull();
    expect(screen.getByTestId("tutor-input")).not.toBeDisabled();
  });
});

// ─────────────────────────────── turn_id (#761) ───────────────────────────────

describe("turn_id", () => {
  async function sendOneMore() {
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "one more" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
  }

  it("mints one turn_id per turn and sends it unchanged on the stream AND its JSON fallback", async () => {
    api.streamChat.mockRejectedValueOnce(new Error("stream refused")); // Rung 3
    renderLearn();
    await openSession("sess-a");
    await sendOneMore();
    await waitFor(() => expect(api.sendChat).toHaveBeenCalled());

    const streamTurn = api.streamChat.mock.calls[0][7];
    expect(streamTurn).toMatch(TURN_ID);
    expect(api.sendChat.mock.calls[0][6]).toBe(streamTurn);

    // The next turn is a different turn.
    await waitFor(() => expect(log()).toHaveTextContent("json reply"));
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "and another" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.streamChat.mock.calls[1][7]).toMatch(TURN_ID);
    expect(api.streamChat.mock.calls[1][7]).not.toBe(streamTurn);
  });

  it("Retry re-sends the interrupted turn's SAME turn_id, and a replayed reply renders as one ordinary bubble", async () => {
    api.streamChat.mockRejectedValueOnce(new ChatStreamError("tutor down", undefined, false));
    renderLearn();
    await openSession("sess-a");
    await sendOneMore();
    const retry = await screen.findByTestId("tutor-retry");
    const firstTurn = api.streamChat.mock.calls[0][7];
    expect(firstTurn).toMatch(TURN_ID);

    api.streamChat.mockResolvedValueOnce({ reply: "The stored reply.", graph_update: {}, mastery_changes: [], replayed: true });
    fireEvent.click(retry);
    await waitFor(() => expect(log()).toHaveTextContent("The stored reply."));

    expect(api.streamChat.mock.calls[1][7]).toBe(firstTurn);
    expect(within(log()).getAllByText("The stored reply.")).toHaveLength(1);
    expect(within(log()).getAllByText("one more")).toHaveLength(1);
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
  });
});

// ─────────────────────────── knowledge-map add / remove ───────────────────────────

describe("knowledge-map optimistic add/remove", () => {
  async function addGraphsConcept() {
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByRole("button", { name: /Add concept/ }));
    fireEvent.change(screen.getByPlaceholderText("New concept name…"), { target: { value: "Graphs" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
  }

  it("removing a concept before its add has saved never deletes the temp id — it deletes the real row once the add lands", async () => {
    const add = deferred<{ node: { id: string; concept_name: string; course_id: string; mastery_score: number; mastery_tier: string }; already_existed: boolean }>();
    api.addGraphNode.mockReturnValue(add.promise);
    await addGraphsConcept();

    // The new concept is focused; remove it while the add is still out.
    fireEvent.click(await screen.findByTitle("Remove concept"));
    expect(api.deleteGraphNode).not.toHaveBeenCalled();

    await act(async () => {
      add.resolve({ node: { id: "n-real", concept_name: "Graphs", course_id: "c1", mastery_score: 0, mastery_tier: "unexplored" }, already_existed: false });
    });

    await waitFor(() => expect(api.deleteGraphNode).toHaveBeenCalledWith("u1", "n-real"));
    expect(screen.queryByTestId("kg-node-n-real")).toBeNull();
  });

  it("a removed in-flight add that merged into an EXISTING node does not delete that node", async () => {
    const add = deferred<{ node: { id: string; concept_name: string; course_id: string; mastery_score: number; mastery_tier: string }; already_existed: boolean }>();
    api.addGraphNode.mockReturnValue(add.promise);
    await addGraphsConcept();
    fireEvent.click(await screen.findByTitle("Remove concept"));

    await act(async () => {
      add.resolve({ node: { id: "n-trees", concept_name: "Trees", course_id: "c1", mastery_score: 0, mastery_tier: "unexplored" }, already_existed: true });
    });

    expect(api.deleteGraphNode).not.toHaveBeenCalled();
    expect(screen.getByTestId("kg-node-n-trees")).toBeInTheDocument();
  });

  it("a failed remove puts the concept (and its edges) back and says so", async () => {
    api.deleteGraphNode.mockRejectedValue(httpError(500, "boom"));
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByTitle("Remove concept"));

    await waitFor(() => expect(api.deleteGraphNode).toHaveBeenCalledWith("u1", "n-trees"));
    expect(await screen.findByTestId("kg-node-n-trees")).toBeInTheDocument();
    expect(await screen.findByText(/Couldn't remove/)).toBeInTheDocument();
  });

  it("a remove the server answers 404 (already gone) is not rolled back", async () => {
    api.deleteGraphNode.mockRejectedValue(httpError(404, "Node not found"));
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByTitle("Remove concept"));
    await waitFor(() => expect(api.deleteGraphNode).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByTestId("kg-node-n-trees")).toBeNull();
  });
});

// ─────────────────────────── session-feedback bookkeeping ───────────────────────────

describe("session-feedback bookkeeping", () => {
  it("ending a session records its context but no longer writes the dead end-count key", async () => {
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(screen.getByRole("button", { name: "End session" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm end" }));
    await waitFor(() => expect(api.endSession).toHaveBeenCalled());
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem("sapling_last_session_context") ?? "null")).toEqual({ sessionId: "sess-a", topic: "Recursion" }),
    );
    expect(localStorage.getItem("sapling_session_end_count")).toBeNull();
  });

  it("a live session holds the shell's feedback prompts; ending it releases them (lib/feedbackPacing.ts)", async () => {
    __resetFeedbackPacingForTests();
    renderLearn();
    await openSession("sess-a");
    await act(async () => {}); // a findBy can resolve before the commit's passive effects run
    expect(feedbackHeld()).toBe(true);
    expect(currentLearningSession()).toBe("sess-a");
    fireEvent.click(screen.getByRole("button", { name: "End session" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm end" }));
    await waitFor(() => expect(feedbackHeld()).toBe(false));
  });

  it("starting or resuming another session clears the previous session's feedback context", async () => {
    sessionStorage.setItem("sapling_last_session_context", JSON.stringify({ sessionId: "old", topic: "Old" }));
    renderLearn();
    await openSession("sess-b");
    expect(sessionStorage.getItem("sapling_last_session_context")).toBeNull();
  });
});

// ─────────────────── crisis support (docs/safety/crisis-support.md) ───────────────────

describe("crisis support", () => {
  const CRISIS = { reply: "the card as text", graph_update: {}, mastery_changes: [], crisis_support: crisisFixture };

  it("a turn answered with the card shows it in the conversation; the composer stays open", async () => {
    api.streamChat.mockResolvedValueOnce(CRISIS);
    renderLearn();
    await openSession("sess-a");
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "i want to kill myself" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    const card = await within(log()).findByTestId("crisis-support-card");
    expect(card).toHaveTextContent(crisisFixture.title);
    expect(log()).not.toHaveTextContent("the card as text");
    expect(api.sendChat).not.toHaveBeenCalled(); // a complete stream: no JSON rung
    await waitFor(() => expect(screen.getByTestId("tutor-input")).not.toBeDisabled());
  });

  it("the JSON fallback's card renders the same way", async () => {
    api.streamChat.mockRejectedValueOnce(new Error("stream refused")); // Rung 3
    api.sendChat.mockResolvedValueOnce(CRISIS);
    renderLearn();
    await openSession("sess-a");
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "i want to kill myself" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect(await within(log()).findByTestId("crisis-support-card")).toBeTruthy();
  });

  it("a session start answered with the card opens no session and shows the card over the picker", async () => {
    api.startSessionStream.mockResolvedValueOnce({ session_id: null, reply: "…", crisis_support: crisisFixture });
    renderLearn();
    await openSession("sess-a");
    fireEvent.click(await screen.findByTestId("kg-node-n-trees"));
    fireEvent.click(await screen.findByRole("button", { name: /Start session/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(crisisFixture.title);
    expect(screen.getByTestId("tutor-start")).toBeInTheDocument(); // back at the picker
    expect(api.startSession).not.toHaveBeenCalled(); // a complete answer: no JSON rung
    expect(api.streamChat).not.toHaveBeenCalled();
  });
});
