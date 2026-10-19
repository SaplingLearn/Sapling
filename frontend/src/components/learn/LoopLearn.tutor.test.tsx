// @vitest-environment jsdom
/**
 * Redesign prompt 04 — the Clov tutor view and the loop's Retry.
 *
 * Retry: only an interrupted CONVERSATIONAL turn of the current session is
 * re-sent, once, through the same chat stream; the stored transcript is read
 * first so a turn the server already saved is never duplicated; a graded
 * submission is never replayed (status first). Tutor: `?view=tutor` behind
 * the tutor_view flag renders the SAME controller — welcome only after a
 * successful discovery with nothing open, starters only seed, history splits
 * open (resume) from past (read-only), context lives in a panel or a sheet.
 * Every loop client is mocked; assertions are on calls made and testids.
 */
import React from "react";
import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

// Retry flows chain several mocked reads; under a parallel full-suite run the
// 1 s default was occasionally too tight (seen once in four runs).
configure({ asyncUtilTimeout: 3000 });
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => search.params,
  usePathname: () => "/learn",
  useRouter: () => router,
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
const flags = vi.hoisted(() => ({ map: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (key: string) => (flags.ready ? flags.map[key] ?? "off" : "off"),
  useFlagMap: () => ({ flags: flags.map, ready: flags.ready }),
}));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn() }));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));
vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));
vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => <div data-testid="kg-stub" /> }));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
const viewport = vi.hoisted(() => ({ compact: false }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => viewport.compact, MOBILE_BREAKPOINT: 768 }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

const api = vi.hoisted(() => ({
  getCourses: vi.fn(), listLoopSessionsFor: vi.fn(), resumeSession: vi.fn(), getLoopSessionStatus: vi.fn(),
  startLoopSession: vi.fn(), setLoopGoal: vi.fn(), nextLoopProbe: vi.fn(), answerLoopProbe: vi.fn(),
  getLoopPlan: vi.fn(), approveLoopPlan: vi.fn(), streamLoopChat: vi.fn(), streamLoopCheckAnswer: vi.fn(),
  postLoopAttempt: vi.fn(), requestLoopHint: vi.fn(), requestLoopHintTurn: vi.fn(), closeLoopSession: vi.fn(),
  getGraph: vi.fn(), nextLoopCheck: vi.fn(), submitLoopRating: vi.fn(), getDocuments: vi.fn(), getSessions: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { ApiError, type StreamChatHandlers } from "@/lib/api";
import { LoopLearn } from "./LoopLearn";

const course = { course_id: "c1", course_name: "Intro CS", course_code: "CS 101" };
const open = (id: string, phase: string, started: string) => ({ session_id: id, topic: `t ${id}`, started_at: started, phase });
const probeItem = { done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "What is a base case?", options: null };
const pose = { question_hash: "qh7", format: "free", difficulty: 2, prompt: "Why does it stop?", options: null };
const status = (over: object = {}) => ({ active: true, session_id: "s2", loop_phase: "teach", phase: "teach", check: null, ...over });
const turn = (over: object = {}) => ({ reply: "ok", graph_update: {}, mastery_changes: [], leak_redacted: false, ...over });
const listed = (sessions: object[], resume: object | null = null) => ({ sessions, resume });
const welcomeRow = { id: "m1", role: "assistant", content: "welcome back", created_at: "" };

beforeEach(() => {
  viewport.compact = false;
  flags.map = {};
  flags.ready = true;
  search.params = new URLSearchParams();
  Object.values(api).forEach((f) => f.mockReset());
  router.replace.mockReset();
  Object.values(toast).forEach((f) => f.mockReset());
  api.getCourses.mockResolvedValue({ courses: [course] });
  api.getLoopSessionStatus.mockImplementation(async (id: string) => status({ session_id: id }));
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [welcomeRow] });
  api.getDocuments.mockResolvedValue({ documents: [] });
  api.getSessions.mockResolvedValue({ sessions: [] });
});
afterEach(cleanup);

async function resumedTeach(sessions: object[] = [open("s2", "teach", "2026-09-21T10:00:00Z")]) {
  api.listLoopSessionsFor.mockResolvedValue(listed(sessions));
  render(<LoopLearn />);
  await screen.findByText("welcome back");
}

function sendChat(text: string) {
  fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: text } });
  fireEvent.click(screen.getByTestId("tutor-send"));
}

/** The user turns the conversation log shows with exactly this text. */
const userTurns = (text: string) =>
  Array.from(screen.getByRole("log").querySelectorAll(".fa26-message--user")).filter((el) => el.textContent?.includes(text));

// ── Retry ────────────────────────────────────────────────────────────────

describe("loop Retry of an interrupted conversational turn", () => {
  it("a zero-token failure keeps the student's turn, marks it interrupted and offers Retry; Retry re-sends once with no duplicate", async () => {
    api.streamLoopChat
      .mockRejectedValueOnce(new ApiError("boom", 503))
      .mockResolvedValueOnce(turn({ reply: "Base cases stop recursion." }));
    await resumedTeach();
    sendChat("why?");
    const marker = await screen.findByTestId("tutor-interrupted");
    expect(marker.textContent).toContain("This reply was interrupted.");
    expect(toast.error).not.toHaveBeenCalled(); // the turn itself says so
    expect(userTurns("why?")).toHaveLength(1);
    // the stored transcript does not hold the turn: nothing was saved
    api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [welcomeRow] });
    fireEvent.click(screen.getByTestId("tutor-retry"));
    expect(await screen.findByText("Base cases stop recursion.")).toBeTruthy();
    expect(api.streamLoopChat).toHaveBeenCalledTimes(2);
    expect(api.streamLoopChat.mock.calls[1].slice(0, 3)).toEqual(["s2", "u1", "why?"]);
    expect(userTurns("why?")).toHaveLength(1); // the pair was replaced, not repeated
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
    expect(api.streamLoopCheckAnswer).not.toHaveBeenCalled(); // chat never grades
  });

  it("a partial reply stays visible, marked interrupted, until Retry replaces it", async () => {
    api.streamLoopChat
      .mockImplementationOnce(async (_s: string, _u: string, _m: string, h: StreamChatHandlers) => {
        h.onToken?.("Half an ans");
        throw new Error("The tutor was interrupted.");
      })
      .mockResolvedValueOnce(turn({ reply: "The whole answer." }));
    await resumedTeach();
    sendChat("explain");
    await screen.findByTestId("tutor-interrupted");
    expect(screen.getByText("Half an ans")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-retry"));
    expect(await screen.findByText("The whole answer.")).toBeTruthy();
    expect(screen.queryByText("Half an ans")).toBeNull();
  });

  it("Stop keeps the partial text as stopped, ignores later tokens, and Retry is offered", async () => {
    let handlers: StreamChatHandlers | undefined;
    let finish: (v: unknown) => void = () => {};
    api.streamLoopChat.mockImplementationOnce((_s: string, _u: string, _m: string, h: StreamChatHandlers) => {
      handlers = h;
      h.onToken?.("So far");
      return new Promise((resolve) => { finish = resolve; });
    });
    await resumedTeach();
    sendChat("go on");
    await screen.findByText("So far");
    fireEvent.click(screen.getByTestId("tutor-stop"));
    await act(async () => {
      handlers?.onToken?.(" and more");
      handlers?.onPhase?.("check");
      finish(turn({ reply: "late final", phase: "check", check: pose }));
    });
    expect((await screen.findByTestId("tutor-interrupted")).textContent).toContain("You stopped this reply.");
    expect(screen.getByText("So far")).toBeTruthy();
    expect(screen.queryByText(/and more|late final/)).toBeNull();
    expect(screen.queryByTestId("loop-check-prompt")).toBeNull(); // a late pose cannot open a check
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach");
    expect((screen.getByTestId("tutor-retry") as HTMLButtonElement).disabled).toBe(false);
  });

  it("a Stop that raced the server's save: Retry finds the stored turn and sends nothing again", async () => {
    let finish: (v: unknown) => void = () => {};
    api.streamLoopChat.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    await resumedTeach();
    sendChat("why?");
    fireEvent.click(await screen.findByTestId("tutor-stop"));
    await act(async () => { finish(turn({ reply: "saved reply" })); });
    await screen.findByTestId("tutor-interrupted");
    api.resumeSession.mockResolvedValue({
      session: { id: "s2" },
      messages: [welcomeRow, { id: "m2", role: "user", content: "why?", created_at: "" }, { id: "m3", role: "assistant", content: "saved reply", created_at: "" }],
    });
    const statusCalls = api.getLoopSessionStatus.mock.calls.length;
    fireEvent.click(screen.getByTestId("tutor-retry"));
    expect(await screen.findByText("saved reply")).toBeTruthy();
    expect(await screen.findByTestId("loop-recovery-note")).toBeTruthy();
    expect(api.streamLoopChat).toHaveBeenCalledTimes(1); // never re-sent
    expect(userTurns("why?")).toHaveLength(1);
    await waitFor(() => expect(api.getLoopSessionStatus.mock.calls.length).toBeGreaterThan(statusCalls));
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
  });

  it("if the transcript cannot be checked, nothing is sent and Retry stays available", async () => {
    api.streamLoopChat.mockRejectedValueOnce(new ApiError("boom", 503));
    await resumedTeach();
    sendChat("why?");
    await screen.findByTestId("tutor-interrupted");
    api.resumeSession.mockRejectedValueOnce(new ApiError("down", 503));
    fireEvent.click(screen.getByTestId("tutor-retry"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1)); // the check failed; the chat failure was inline
    expect(api.streamLoopChat).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("tutor-interrupted")).toBeTruthy();
    expect((screen.getByTestId("tutor-retry") as HTMLButtonElement).disabled).toBe(false);
  });

  it("a second Retry while one is checking is refused: one re-send only", async () => {
    api.streamLoopChat.mockRejectedValueOnce(new ApiError("boom", 503)).mockResolvedValueOnce(turn({ reply: "once" }));
    await resumedTeach();
    sendChat("why?");
    await screen.findByTestId("tutor-interrupted");
    let release: (v: unknown) => void = () => {};
    api.resumeSession.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    fireEvent.click(screen.getByTestId("tutor-retry"));
    await waitFor(() => expect((screen.getByTestId("tutor-retry") as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(screen.getByTestId("tutor-retry"));
    await act(async () => { release({ session: { id: "s2" }, messages: [welcomeRow] }); });
    await screen.findByText("once");
    expect(api.resumeSession).toHaveBeenCalledTimes(2); // the resume + ONE transcript check
    expect(api.streamLoopChat).toHaveBeenCalledTimes(2);
  });

  it("only the latest turn can be retried; an older interrupted turn's Retry is disabled", async () => {
    api.streamLoopChat.mockRejectedValueOnce(new ApiError("boom", 503)).mockResolvedValueOnce(turn({ reply: "second reply" }));
    await resumedTeach();
    sendChat("first?");
    await screen.findByTestId("tutor-interrupted");
    sendChat("second?");
    await screen.findByText("second reply");
    expect((screen.getByTestId("tutor-retry") as HTMLButtonElement).disabled).toBe(true);
  });

  it("switching sessions mid-check abandons the retry: nothing is sent into either session", async () => {
    api.streamLoopChat.mockRejectedValueOnce(new ApiError("boom", 503));
    await resumedTeach([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "teach", "2026-09-20T10:00:00Z")]);
    sendChat("why?");
    await screen.findByTestId("tutor-interrupted");
    let release: (v: unknown) => void = () => {};
    api.resumeSession.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    fireEvent.click(screen.getByTestId("tutor-retry"));
    api.resumeSession.mockResolvedValue({ session: { id: "s1" }, messages: [{ id: "x", role: "assistant", content: "session one", created_at: "" }] });
    fireEvent.click(screen.getByTestId("loop-session-s1"));
    await screen.findByText("session one");
    await act(async () => { release({ session: { id: "s2" }, messages: [welcomeRow] }); });
    expect(api.streamLoopChat).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s1");
  });

  it("a budget pause marks the turn paused and Retry waits until chat is allowed again", async () => {
    api.streamLoopChat.mockImplementationOnce(async (_s: string, _u: string, _m: string, h: StreamChatHandlers) => {
      h.onBudget?.({ level: "hard", reset_at: null, scope: "daily_usd", session_capped: true });
      throw new Error("Chat stream ended without a done event.");
    });
    await resumedTeach();
    sendChat("why?");
    expect((await screen.findByTestId("tutor-interrupted")).textContent).toContain("Chat paused");
    expect(screen.getByTestId("loop-budget-paused")).toBeTruthy();
    expect((screen.getByTestId("tutor-retry") as HTMLButtonElement).disabled).toBe(true);
  });

  it("offline: the turn says so, and nothing is queued", async () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    api.streamLoopChat.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await resumedTeach();
    sendChat("why?");
    expect((await screen.findByTestId("tutor-interrupted")).textContent).toContain("You're offline");
    expect(toast.error).not.toHaveBeenCalled(); // said once, inline, beside the Retry
    expect(api.streamLoopChat).toHaveBeenCalledTimes(1);
    online.mockRestore();
  });
});

describe("graded checks recover status-first and are never replayed", () => {
  async function withCheck() {
    api.getLoopSessionStatus.mockResolvedValueOnce(status());
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    await screen.findByTestId("loop-check-prompt");
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
  }

  it("a feedback stream that breaks after grading offers no Retry: status is read and Continue is the way on", async () => {
    api.streamLoopCheckAnswer.mockImplementationOnce(async (_s: string, _u: string, _q: string, _a: object, h: StreamChatHandlers) => {
      h.onPhase?.("feedback");
      h.onToken?.("Good start —");
      throw new Error("The tutor was interrupted.");
    });
    api.getLoopSessionStatus.mockResolvedValue(status({ phase: "feedback", check: null }));
    await withCheck();
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    expect((await screen.findByTestId("loop-recovery-note")).textContent).toMatch(/may already be graded/);
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("feedback"));
    expect(screen.getByText("Good start —")).toBeTruthy(); // partial feedback kept
    expect(screen.queryByTestId("tutor-retry")).toBeNull(); // no replay of a graded answer
    expect(screen.getByTestId("loop-continue")).toBeTruthy();
    expect(api.streamLoopCheckAnswer).toHaveBeenCalledTimes(1);
  });

  it("a 409 already-graded says so and restores the server's state without a second submission", async () => {
    api.streamLoopCheckAnswer.mockRejectedValueOnce(new ApiError("x", 409, { body: { detail: "already graded" } }));
    api.getLoopSessionStatus.mockResolvedValue(status({ phase: "feedback", check: null }));
    await withCheck();
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    expect((await screen.findByTestId("loop-recovery-note")).textContent).toMatch(/already graded/);
    await waitFor(() => expect(screen.queryByTestId("loop-check-prompt")).toBeNull());
    expect(api.streamLoopCheckAnswer).toHaveBeenCalledTimes(1);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("late check/phase/hint events from a settled submission cannot reopen the graded check", async () => {
    let handlers: StreamChatHandlers | undefined;
    api.streamLoopCheckAnswer.mockImplementationOnce(async (_s: string, _u: string, _q: string, _a: object, h: StreamChatHandlers) => {
      handlers = h;
      return turn({ reply: "Graded: not yet.", phase: "feedback", graded: true, verdict: "not_yet" });
    });
    await withCheck();
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await screen.findByText("Graded: not yet.");
    await act(async () => {
      handlers?.onCheck?.({ question_hash: "qh7", format: "free", difficulty: 2 });
      handlers?.onPhase?.("hint");
      handlers?.onBudget?.({ level: "hard", reset_at: null, scope: "daily", session_capped: false });
    });
    expect(screen.queryByTestId("loop-check-prompt")).toBeNull();
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("feedback");
    expect(screen.queryByTestId("loop-budget-paused")).toBeNull();
  });
});

describe("conversation seeds while teaching", () => {
  it("'I'm confused' and 'Another example' are chat turns through the chat stream — never a grade", async () => {
    api.streamLoopChat.mockResolvedValue(turn({ reply: "Let's try it another way." }));
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-seed-confused"));
    await screen.findByText("Let's try it another way.");
    fireEvent.click(screen.getByTestId("loop-seed-example"));
    await waitFor(() => expect(api.streamLoopChat).toHaveBeenCalledTimes(2));
    expect(api.streamLoopChat.mock.calls.map((c) => c[2])).toEqual([
      "I'm confused. Can you explain that another way?",
      "Can you show me another example?",
    ]);
    expect(api.streamLoopCheckAnswer).not.toHaveBeenCalled();
    expect(api.nextLoopCheck).not.toHaveBeenCalled();
  });

  it("the composer links to the course's real materials, not an attachment", async () => {
    await resumedTeach();
    // Scoped to the open course: Library pre-selects it from ?course=.
    expect(screen.getByTestId("loop-materials-link").getAttribute("href")).toBe("/library?course=c1");
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});

// ── Tutor view ─────────────────────────────────────────────────────────────

describe("the Clov tutor view (?view=tutor, tutor_view flag)", () => {
  beforeEach(() => {
    flags.map = { tutor_view: "on" };
    search.params = new URLSearchParams("view=tutor");
  });

  it("with the flag off, ?view=tutor is ignored: the studio renders and boots as before", async () => {
    flags.map = {};
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "Hello" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("tutor-bar")).toBeNull();
    expect(screen.getByTestId("loop-heading")).toBeTruthy();
    expect(screen.queryByTestId("loop-view-tutor")).toBeNull();
  });

  it("waits for the flag answer before discovery, so it never auto-starts a session the welcome should offer", async () => {
    flags.ready = false;
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    const { rerender } = render(<LoopLearn />);
    await waitFor(() => expect(api.getCourses).toHaveBeenCalled());
    expect(api.listLoopSessionsFor).not.toHaveBeenCalled();
    flags.ready = true;
    rerender(<LoopLearn />);
    expect(await screen.findByTestId("tutor-welcome")).toBeTruthy();
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });

  it("nothing open: the welcome waits for a choice; starters only fill the field", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    render(<LoopLearn />);
    const welcome = await screen.findByTestId("tutor-welcome");
    expect(within(welcome).getByRole("heading", { level: 1, name: "What would you like to understand?" })).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-starter-0"));
    expect((screen.getByTestId("tutor-welcome-composer-input") as HTMLTextAreaElement).value).toBe("Explain ");
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.streamLoopChat).not.toHaveBeenCalled();
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("");
  });

  it("'Start check-in' starts the guided session: check-in first, then a plan to approve", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "Hello there" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-welcome-start"));
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1"));
    expect(await screen.findByTestId("loop-probe-item")).toBeTruthy();
    expect(screen.queryByTestId("tutor-welcome")).toBeNull();
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s9");
  });

  it("asking from the welcome starts a guided session with the question as its topic (no chat turn, no grade)", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "Good question — first, a check-in." });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    const field = await screen.findByTestId("tutor-welcome-composer-input");
    fireEvent.change(field, { target: { value: "Why do loops end?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
    expect(api.startLoopSession.mock.calls[0].slice(0, 3)).toEqual(["u1", "c1", "Why do loops end?"]);
    expect(api.streamLoopChat).not.toHaveBeenCalled();
    expect(await screen.findByText("Good question — first, a check-in.")).toBeTruthy();
  });

  it("a failed discovery is a retry state, never the welcome", async () => {
    api.listLoopSessionsFor.mockRejectedValue(new ApiError("boom", 503));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-sessions-error")).toBeTruthy();
    expect(screen.queryByTestId("tutor-welcome")).toBeNull();
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });

  it("an open session resumes in the tutor: bar, phase strip, chips, goal line and actions over the composer", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ goal: { text: "Understand recursion", target_node_ids: ["n1"] } }));
    await resumedTeach();
    const root = screen.getByTestId("loop-phase");
    expect(root.getAttribute("data-view")).toBe("tutor");
    expect(root.getAttribute("data-session-id")).toBe("s2");
    expect(screen.getByTestId("tutor-bar").textContent).toContain("Clov tutor");
    expect(screen.getByRole("list", { name: "Learning progress" })).toBeTruthy();
    expect((await screen.findByTestId("tutor-goal-line")).textContent).toContain("Understand recursion");
    expect(screen.getByTestId("loop-check-me").textContent).toBe("Check my understanding");
    // the actions sit between the transcript and the composer, outside the scroll box
    expect(screen.getByTestId("tutor-messages").contains(screen.getByTestId("loop-check-me"))).toBe(false);
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });

  it("switching views keeps the same session and sends nothing", async () => {
    search.params = new URLSearchParams();
    await resumedTeach();
    const lists = api.listLoopSessionsFor.mock.calls.length;
    fireEvent.click(screen.getByTestId("loop-view-tutor"));
    expect(router.replace).toHaveBeenLastCalledWith("/learn?view=tutor", { scroll: false });
    expect(await screen.findByTestId("tutor-bar")).toBeTruthy();
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s2");
    expect(screen.getByText("welcome back")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-menu"));
    fireEvent.click(screen.getByTestId("tutor-menu-studio"));
    expect(await screen.findByTestId("loop-heading")).toBeTruthy();
    expect(router.replace).toHaveBeenLastCalledWith("/learn", { scroll: false });
    expect(api.listLoopSessionsFor.mock.calls.length).toBe(lists);
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.streamLoopChat).not.toHaveBeenCalled();
  });

  it("Goal & plan: read-only while teaching, with the plan's reasons and a confirmed new-session path", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ goal: { text: "Understand recursion", target_node_ids: ["n1"] } }));
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-context-goal"));
    const panel = await screen.findByRole("complementary", { name: "Your goal & plan" });
    expect(panel.textContent).toContain("Understand recursion");
    expect(panel.textContent).toContain("Your selected goal");
    expect(panel.textContent).toContain("To change the goal, start a new session.");
    expect(within(panel).queryByTestId("tutor-goal-edit")).toBeNull();
    expect(screen.getByTestId("tutor-context-goal").getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(within(panel).getByTestId("tutor-goal-new-session"));
    expect(await screen.findByRole("dialog", { name: "Start a new session?" })).toBeTruthy();
    expect(api.closeLoopSession).not.toHaveBeenCalled();
    expect(api.setLoopGoal).not.toHaveBeenCalled();
  });

  it("Materials lists this course's real Library documents; empty and failed loads say so", async () => {
    api.getDocuments
      .mockRejectedValueOnce(new ApiError("down", 503))
      .mockResolvedValueOnce({ documents: [
        { id: "d1", file_name: "Recursion notes.pdf", category: "lecture_notes", course_id: "c1" },
        { id: "d2", file_name: "Other course.pdf", category: "reading", course_id: "c9" },
      ] });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-context-materials"));
    expect(await screen.findByTestId("tutor-materials-error")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry materials" }));
    expect(await screen.findByText("Recursion notes.pdf")).toBeTruthy();
    expect(screen.queryByText("Other course.pdf")).toBeNull();
    expect(screen.getByTestId("tutor-materials-library").getAttribute("href")).toBe("/library?course=c1");
  });

  it("Materials with nothing uploaded offers Library, not an upload in chat", async () => {
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-materials-open")); // the composer's Materials control
    expect(await screen.findByTestId("tutor-materials-empty")).toBeTruthy();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("Map shows the real graph and the conversation focus; closing returns to the chip", async () => {
    api.getGraph.mockResolvedValue({ nodes: [{ id: "n1", name: "Recursion", course_id: "c1", mastery_score: 0.4, mastery_tier: "learning" }], edges: [], stats: {} });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-context-map"));
    const panel = await screen.findByRole("complementary", { name: "Knowledge map" });
    await waitFor(() => expect(within(panel).getByTestId("tutor-map-full").getAttribute("href")).toBe("/tree"));
    fireEvent.click(within(panel).getByTestId("tutor-context-close"));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Knowledge map" })).toBeNull());
  });

  it("on a phone the context is ONE labelled sheet; Back to conversation closes it", async () => {
    viewport.compact = true;
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-context-goal"));
    const sheet = await screen.findByRole("dialog", { name: "Your goal & plan" });
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(within(sheet).getByTestId("tutor-context-back"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("History: open sessions resume, past sessions open read-only, other courses are left out", async () => {
    api.getSessions.mockResolvedValue({ sessions: [
      { id: "s2", topic: "t s2", mode: "socratic", course_id: "c1", started_at: "", ended_at: null, message_count: 3, is_active: true },
      { id: "old-1", topic: "Literal meaning", mode: "socratic", course_id: "c1", started_at: "", ended_at: "2026-09-01", message_count: 4, is_active: false },
      { id: "elsewhere", topic: "Other course", mode: "socratic", course_id: "c9", started_at: "", ended_at: "2026-09-01", message_count: 2, is_active: false },
    ] });
    await resumedTeach([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "plan", "2026-09-20T10:00:00Z")]);
    fireEvent.click(screen.getByTestId("tutor-history-open"));
    const sheet = await screen.findByRole("dialog", { name: "Your conversations" });
    expect(within(sheet).getByTestId("tutor-history-open-s2").getAttribute("aria-current")).toBe("true");
    expect(within(sheet).getByTestId("tutor-history-open-s1")).toBeTruthy();
    expect(await within(sheet).findByTestId("tutor-history-past-old-1")).toBeTruthy();
    expect(within(sheet).queryByTestId("tutor-history-past-s2")).toBeNull(); // open, not past
    expect(within(sheet).queryByTestId("tutor-history-past-elsewhere")).toBeNull();
    fireEvent.change(within(sheet).getByTestId("tutor-history-search"), { target: { value: "literal" } });
    expect(within(sheet).queryByTestId("tutor-history-open-s1")).toBeNull();
    api.resumeSession.mockResolvedValue({ session: { id: "old-1", topic: "Literal meaning" }, messages: [{ id: "o1", role: "assistant", content: "an old reply", created_at: "" }] });
    fireEvent.click(within(sheet).getByTestId("tutor-history-past-old-1"));
    expect((await screen.findByTestId("loop-readonly-transcript")).textContent).toContain("an old reply");
    expect(screen.queryByTestId("tutor-input")).toBeNull(); // read-only: no composer
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.streamLoopChat).not.toHaveBeenCalled();
  });

  it("History resumes another open session at its own phase, reading status only", async () => {
    await resumedTeach([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "check", "2026-09-20T10:00:00Z")]);
    api.getLoopSessionStatus.mockResolvedValue(status({ session_id: "s1", phase: "check", check: pose }));
    fireEvent.click(screen.getByTestId("tutor-history-open"));
    fireEvent.click(await screen.findByTestId("tutor-history-open-s1"));
    expect((await screen.findByTestId("loop-check-prompt")).getAttribute("data-question-hash")).toBe("qh7");
    expect(api.nextLoopCheck).not.toHaveBeenCalled();
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s1");
  });

  it("a failed past-session read is visible with a retry; open sessions still list", async () => {
    api.getSessions.mockRejectedValueOnce(new ApiError("down", 503)).mockResolvedValueOnce({ sessions: [] });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-history-open"));
    const sheet = await screen.findByRole("dialog", { name: "Your conversations" });
    expect(await within(sheet).findByTestId("tutor-history-error")).toBeTruthy();
    expect(within(sheet).getByTestId("tutor-history-open-s2")).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Retry past sessions" }));
    expect(await within(sheet).findByText("No past sessions in this course yet.")).toBeTruthy();
  });

  it("keyboard: the session menu is a disclosure; Escape closes it and returns focus", async () => {
    await resumedTeach();
    const toggle = screen.getByTestId("tutor-menu");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    toggle.focus();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const item = screen.getByTestId("tutor-menu-goal");
    item.focus();
    fireEvent.keyDown(item, { key: "Escape" });
    expect(screen.queryByTestId("tutor-menu-goal")).toBeNull();
    expect(document.activeElement).toBe(toggle);
  });

  it("keyboard: Escape on the menu trigger itself closes the open menu (focus stays on the trigger after opening)", async () => {
    await resumedTeach();
    const toggle = screen.getByTestId("tutor-menu");
    toggle.focus();
    fireEvent.click(toggle);
    expect(screen.getByTestId("tutor-menu-goal")).toBeTruthy();
    fireEvent.keyDown(toggle, { key: "Escape" });
    expect(screen.queryByTestId("tutor-menu-goal")).toBeNull();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
  });

  it("'+ New session' in the bar confirms first; Cancel keeps the conversation", async () => {
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-new-session"));
    expect(await screen.findByRole("dialog", { name: "Start a new session?" })).toBeTruthy();
    fireEvent.click(screen.getByTestId("loop-new-session-cancel"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.closeLoopSession).not.toHaveBeenCalled();
    expect(screen.getByText("welcome back")).toBeTruthy();
  });

  it("budget pause in the tutor: chat pauses with a reason, the check stays answerable", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ phase: "check", check: pose }));
    api.streamLoopCheckAnswer.mockResolvedValue(turn({ reply: "Graded.", graded: true, phase: "feedback" }));
    api.nextLoopCheck.mockRejectedValue(new ApiError("x", 429, { body: { detail: { code: "budget_exceeded", reset_at: null, session_capped: true } } }));
    await resumedTeach([open("s2", "check", "2026-09-21T10:00:00Z")]);
    await screen.findByTestId("loop-check-prompt");
    api.streamLoopChat.mockImplementationOnce(async (_s: string, _u: string, _m: string, h: StreamChatHandlers) => {
      h.onBudget?.({ level: "hard", reset_at: null, scope: "daily_usd", session_capped: true });
      throw new Error("Chat stream ended without a done event.");
    });
    sendChat("help?");
    expect(await screen.findByTestId("loop-budget-paused")).toBeTruthy();
    expect((screen.getByTestId("tutor-input") as HTMLTextAreaElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await screen.findByText("Graded.");
    expect(api.streamLoopCheckAnswer).toHaveBeenCalledTimes(1);
  });
});

// ── #673 (ad1b1bd5) behaviours on the shared controller, in the tutor view ──

describe("the tutor view surfaces #673's recovery and readiness states", () => {
  beforeEach(() => {
    flags.map = { tutor_view: "on" };
    search.params = new URLSearchParams("view=tutor");
  });

  it("a saved check grade is recovered explicitly: no composer, no wrap-up or new session until it finishes", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "check", "2026-09-21T10:00:00Z")]));
    api.getLoopSessionStatus.mockResolvedValue(status({ phase: "check", pending_grade: { kind: "check", question_hash: "saved-q" } }));
    api.streamLoopCheckAnswer.mockResolvedValue(turn({ reply: "Saved feedback.", graded: true, phase: "feedback" }));
    render(<LoopLearn />);
    const recover = await screen.findByTestId("loop-recover-grade");
    await waitFor(() => expect((recover as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByTestId("loop-phase").getAttribute("data-view")).toBe("tutor");
    expect(screen.queryByTestId("tutor-input")).toBeNull();
    expect((screen.getByTestId("loop-new-session") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("tutor-menu"));
    expect((screen.getByTestId("tutor-menu-end") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("tutor-menu"));
    fireEvent.click(recover);
    expect(await screen.findByText("Saved feedback.")).toBeTruthy();
    expect(api.streamLoopCheckAnswer).toHaveBeenCalledExactlyOnceWith("s2", "u1", "saved-q", { idk: false }, expect.any(Object));
    expect(screen.queryByTestId("loop-pending-grade")).toBeNull();
    expect(api.closeLoopSession).not.toHaveBeenCalled();
  });

  it("pending feedback: Continue reads Retry feedback and no new check is offered until it is served", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ phase: "feedback", check: null }));
    api.streamLoopChat.mockResolvedValue(turn({ reply: "Here is your feedback.", phase: "teach" }));
    await resumedTeach([open("s2", "feedback", "2026-09-21T10:00:00Z")]);
    const continueButton = await screen.findByTestId("loop-continue");
    expect(continueButton.textContent).toBe("Retry feedback");
    expect((screen.getByTestId("loop-check-me") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(continueButton);
    expect(await screen.findByText("Here is your feedback.")).toBeTruthy();
    await waitFor(() => expect((screen.getByTestId("loop-check-me") as HTMLButtonElement).disabled).toBe(false));
    expect(api.nextLoopCheck).not.toHaveBeenCalled();
  });

  it("practice preflight: the no-fresh-practice notice and its source-review path show in the tutor too", async () => {
    const goal = { text: "Understand assignment", target_node_ids: ["target"] };
    api.getGraph.mockResolvedValue({ nodes: [{ id: "target", concept_name: "Variables and Assignment", course_id: "c1", mastery_score: 0.3 }], edges: [], stats: {} });
    api.getLoopSessionStatus.mockResolvedValue(status({ goal, practice_unavailable_node_ids: ["target"] }));
    await resumedTeach();
    const notice = await screen.findByTestId("loop-practice-unavailable");
    expect(notice.textContent).toContain("does not assess or complete your goal");
    await waitFor(() => expect(notice.textContent).toContain("Variables and Assignment"));
    expect(screen.getByTestId("loop-practice-sources").getAttribute("href")).toBe("/library");
    expect(screen.getByTestId("loop-practice-refresh")).toBeTruthy();
  });
});
