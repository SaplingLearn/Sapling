// @vitest-environment jsdom
/**
 * LoopLearn launch readiness (spec §11.3, §13 A26/A27/A39/A46/A60): resume
 * instead of a new probe, no model toggle, the budget banner from a 429 or a
 * hard `budget` event, the no-check-items state, the knowledge-map link,
 * explicit check submissions, retract, the close. Every loop client is
 * mocked; the assertions are on which routes were (not) called and on the
 * rendered testids.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => search.params,
  usePathname: () => "/learn",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn() }));
vi.mock("../ToastProvider", () => ({ useToast: () => toast })); // useToast throws outside a provider
// MarkdownChat is lazy (next/dynamic): render plain text so assertions see message content.
vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));
vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => <div data-testid="kg-stub" /> }));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

const api = vi.hoisted(() => ({
  getCourses: vi.fn(), listLoopSessions: vi.fn(), resumeSession: vi.fn(),
  startLoopSession: vi.fn(), nextLoopProbe: vi.fn(), answerLoopProbe: vi.fn(),
  getLoopPlan: vi.fn(), approveLoopPlan: vi.fn(), streamLoopChat: vi.fn(), streamLoopCheckAnswer: vi.fn(),
  postLoopAttempt: vi.fn(), requestLoopHint: vi.fn(), requestLoopHintTurn: vi.fn(), closeLoopSession: vi.fn(),
  getGraph: vi.fn(), nextLoopCheck: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { ApiError } from "@/lib/api";
import { LoopLearn } from "./LoopLearn";

const course = { course_id: "c1", course_name: "Intro CS", course_code: "CS 101" }; // the EnrolledCourse fields LoopLearn reads
const open = (id: string, phase: string, started: string) => ({ session_id: id, topic: `t ${id}`, started_at: started, phase });
const probeItem = { done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "What is a base case?", options: null };
const pose = { question_hash: "qh7", format: "free", difficulty: 2, prompt: "Why does it stop?", options: null };
const turn = (over: object = {}) => ({ reply: "ok", graph_update: {}, mastery_changes: [], leak_redacted: false, ...over });

beforeEach(() => {
  search.params = new URLSearchParams();
  Object.values(api).forEach((f) => f.mockReset());
  Object.values(toast).forEach((f) => f.mockReset());
  api.getCourses.mockResolvedValue({ courses: [course] });
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [{ id: "m1", role: "assistant", content: "welcome back", created_at: "" }] });
});
afterEach(cleanup);

/** Resume an open teach-phase session and wait until it is settled. */
async function resumedTeach() {
  api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z")]);
  render(<LoopLearn />);
  await screen.findByText("welcome back");
}

/** A teach session whose "Check me" posed `pose`. */
async function withCheckItem(item: object = pose) {
  api.nextLoopCheck.mockResolvedValue({ phase: "check", check: item });
  await resumedTeach();
  fireEvent.click(await screen.findByTestId("loop-check-me"));
  await screen.findByTestId("loop-check-prompt");
}

describe("LoopLearn — resume (spec §11.3)", () => {
  it("resumes the newest open session and calls no probe route and no start-session", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "check", "2026-09-20T10:00:00Z")]);
    render(<LoopLearn />);
    const root = await screen.findByTestId("loop-phase");
    await waitFor(() => expect(root.getAttribute("data-session-id")).toBe("s2"));
    expect(root.getAttribute("data-phase")).toBe("teach");
    expect(api.listLoopSessions).toHaveBeenCalledWith("u1", "c1");
    expect(api.resumeSession).toHaveBeenCalledWith("s2");
    expect(await screen.findByText("welcome back")).toBeTruthy();
    expect(screen.getByTestId("loop-session-s1")).toBeTruthy(); // the picker lists every open session
    expect(screen.getByTestId("loop-session-s2").getAttribute("aria-current")).toBe("true");
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    expect(api.answerLoopProbe).not.toHaveBeenCalled();
    expect(api.streamLoopChat).not.toHaveBeenCalled(); // no turn is sent on resume
  });

  it("a session resumed in the probe continues it with the same session id", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s2", "u1"));
    expect((await screen.findByTestId("loop-probe-item")).getAttribute("data-question-hash")).toBe("qh");
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });

  it("a session resumed in the plan reads the plan", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "plan", "2026-09-21T10:00:00Z")]);
    api.getLoopPlan.mockResolvedValue({ concepts: [{ node_id: "n1", concept_name: "Recursion", kind: "new", p_known: 0.35 }], order: [] });
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-plan-concept-n1")).toBeTruthy();
    expect(api.getLoopPlan).toHaveBeenCalledWith("s2", "u1");
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });

  it("a session resumed in check restores its pose through the idempotent /check/next", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "check", "2026-09-21T10:00:00Z")]);
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
    render(<LoopLearn />);
    expect((await screen.findByTestId("loop-check-prompt")).getAttribute("data-question-hash")).toBe("qh7");
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    expect(api.streamLoopChat).not.toHaveBeenCalled();
  });

  it("?resume= names an open loop session: that one is resumed, not the newest", async () => {
    search.params = new URLSearchParams("resume=s1");
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "teach", "2026-09-20T10:00:00Z")]);
    render(<LoopLearn />);
    const root = await screen.findByTestId("loop-phase");
    await waitFor(() => expect(root.getAttribute("data-session-id")).toBe("s1"));
    expect(api.resumeSession).toHaveBeenCalledWith("s1");
  });

  it("clicking another session in the picker resumes it", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z"), open("s1", "teach", "2026-09-20T10:00:00Z")]);
    render(<LoopLearn />);
    await screen.findByText("welcome back");
    fireEvent.click(screen.getByTestId("loop-session-s1"));
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s1"));
    expect(api.resumeSession).toHaveBeenLastCalledWith("s1");
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });

  it("starts a session and the probe only when none is open", async () => {
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "Hello there" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1"));
    expect(api.startLoopSession).toHaveBeenCalledTimes(1);
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Intro CS");
    expect(await screen.findByText("Hello there")).toBeTruthy();
  });

  it("'New session' starts one even when a session is open", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z")]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-new-session"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1"));
  });

  it("a ?resume= id that is not an open loop session opens read-only and never starts a probe", async () => {
    // spec §11.3: Dashboard/Tree resume links carry pre-launch LEGACY session ids.
    search.params = new URLSearchParams("resume=legacy-1");
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z")]);
    api.resumeSession.mockResolvedValue({ session: { id: "legacy-1", topic: "Old topic" }, messages: [{ id: "m1", role: "assistant", content: "old legacy chat", created_at: "" }] });
    render(<LoopLearn />);
    const transcript = await screen.findByTestId("loop-readonly-transcript");
    expect(transcript.textContent).toContain("old legacy chat");
    expect(api.resumeSession).toHaveBeenCalledWith("legacy-1");
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    fireEvent.click(screen.getByTestId("loop-readonly-new-session"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
  });

  it("a failed read-only resume shows the retry state, never a probe", async () => {
    search.params = new URLSearchParams("resume=legacy-1");
    api.listLoopSessions.mockResolvedValue([]);
    api.resumeSession.mockRejectedValue(new ApiError("gone", 404));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-sessions-retry")).toBeTruthy();
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });

  it("a failed /sessions shows a retry and never starts a probe; Retry re-reads", async () => {
    api.listLoopSessions.mockRejectedValue(new ApiError("boom", 503));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-sessions-error")).toBeTruthy();
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    api.listLoopSessions.mockResolvedValue([open("s2", "teach", "2026-09-21T10:00:00Z")]);
    fireEvent.click(screen.getByTestId("loop-sessions-retry"));
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s2"));
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });
});

describe("LoopLearn — probe and plan", () => {
  it("a wrong probe answer shows the reference before the next item", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue(probeItem);
    api.answerLoopProbe.mockResolvedValue({ graded: true, correct: false, p_known: 0.2, probe_done: false, novice_floor: false, reference_answer: "The case that stops recursion." });
    render(<LoopLearn />);
    fireEvent.change(await screen.findByTestId("loop-probe-input"), { target: { value: "a loop" } });
    fireEvent.click(screen.getByTestId("loop-probe-submit"));
    expect((await screen.findByTestId("loop-probe-reference")).textContent).toContain("The case that stops recursion.");
    expect(api.answerLoopProbe).toHaveBeenCalledWith("s2", "u1", "qh", { answer: "a loop", idk: false });
    expect(api.nextLoopProbe).toHaveBeenCalledTimes(1); // waits for the student
    fireEvent.click(screen.getByTestId("loop-probe-next"));
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledTimes(2));
  });

  it("'I don't know' submits idk with no answer text", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue(probeItem);
    api.answerLoopProbe.mockResolvedValue({ graded: true, correct: false, p_known: 0.2, probe_done: false, novice_floor: false, reference_answer: "ref" });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-probe-idk"));
    await waitFor(() => expect(api.answerLoopProbe).toHaveBeenCalledWith("s2", "u1", "qh", { idk: true }));
  });

  it("mc_reason probe items post option + reason", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue({ ...probeItem, format: "mc_reason", options: [{ letter: "A", text: "x" }, { letter: "B", text: "y" }] });
    api.answerLoopProbe.mockResolvedValue({ graded: true, correct: true, p_known: 0.6, probe_done: false, novice_floor: false });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-probe-option-B"));
    fireEvent.change(screen.getByTestId("loop-probe-reason"), { target: { value: "because" } });
    fireEvent.click(screen.getByTestId("loop-probe-submit"));
    await waitFor(() => expect(api.answerLoopProbe).toHaveBeenCalledWith("s2", "u1", "qh", { option: "B", reason: "because", idk: false }));
  });

  it("an ungradable probe answer is a muted line and the next item follows", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue(probeItem);
    api.answerLoopProbe.mockResolvedValue({ graded: false, unavailable: true });
    render(<LoopLearn />);
    fireEvent.change(await screen.findByTestId("loop-probe-input"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("loop-probe-submit"));
    expect(await screen.findByText(/Couldn't grade that one/)).toBeTruthy();
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledTimes(2));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("the last probe answer moves to the plan without another /probe/next; approve enters teach", async () => {
    api.listLoopSessions.mockResolvedValue([open("s2", "probe", "2026-09-21T10:00:00Z")]);
    api.nextLoopProbe.mockResolvedValue(probeItem);
    api.answerLoopProbe.mockResolvedValue({ graded: true, correct: true, p_known: 0.7, probe_done: true, novice_floor: false });
    api.getLoopPlan.mockResolvedValue({
      concepts: [
        { node_id: "n2", concept_name: "Stacks", kind: "review", p_known: 0.5 },
        { node_id: "n1", concept_name: "Recursion", kind: "new", p_known: 0.35 },
      ],
      order: ["due_reviews", "new_material"],
    });
    api.approveLoopPlan.mockResolvedValue({ phase: "teach", concept_ids: ["n2", "n1"] });
    render(<LoopLearn />);
    fireEvent.change(await screen.findByTestId("loop-probe-input"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("loop-probe-submit"));
    const row = await screen.findByTestId("loop-plan-concept-n2");
    expect(row.textContent).toContain("Review");
    expect(api.nextLoopProbe).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("plan");
    fireEvent.click(screen.getByTestId("loop-plan-approve"));
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach"));
    expect(api.approveLoopPlan).toHaveBeenCalledWith("s2", "u1", ["n2", "n1"]);
  });
});

describe("LoopLearn — A26", () => {
  it("shows no model toggle", async () => {
    await resumedTeach();
    expect(screen.queryByRole("radiogroup", { name: "Tutor model" })).toBeNull();
  });

  it("a capped student still gets a session and the probe; the opener's budget notice shows the banner", async () => {
    // spec §13 A27: at the hard level the opener is a template carrying `budget`, never a 429.
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "template", budget: { level: "hard", reset_at: "2026-09-27T00:00:00Z", scope: "daily_usd", session_capped: false } });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(banner.getAttribute("data-session-capped")).toBe("false");
    expect(banner.textContent).toContain("Tutor chat paused until");
    expect(banner.textContent).toContain("Practice and review keep working");
    expect(screen.getByTestId("loop-budget-study-link").getAttribute("href")).toBe("/study?mode=cards");
    await waitFor(() => expect(api.nextLoopProbe).toHaveBeenCalledWith("s9", "u1"));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("renders the budget pause banner from a 429 body (Check me on a paused novice concept)", async () => {
    api.nextLoopCheck.mockRejectedValue(
      new ApiError("ai budget reached", 429, { body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z" } }),
    );
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach"); // phase unchanged
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("A39: a session-capped 429 renders the session copy with no reset time", async () => {
    api.nextLoopCheck.mockRejectedValue(
      new ApiError("x", 429, { body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z", scope: "session_requests", session_capped: true } }),
    );
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-session-capped")).toBe("true");
    expect(banner.textContent).toContain("Tutor chat paused for this session. Practice and review keep working.");
    expect(banner.textContent).not.toContain("until");
  });

  it("'Check me' renders the returned check object as the pose (A27)", async () => {
    await withCheckItem();
    const prompt = screen.getByTestId("loop-check-prompt");
    expect(prompt.getAttribute("data-question-hash")).toBe("qh7");
    expect(prompt.getAttribute("data-format")).toBe("free");
    expect(prompt.textContent).toContain("Why does it stop?");
    expect(api.nextLoopCheck).toHaveBeenCalledWith("s2", "u1");
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("check");
    expect(screen.queryByTestId("loop-check-me")).toBeNull(); // an item is current
  });

  it("'Check me' with the plan done shows the muted plan-done line", async () => {
    api.nextLoopCheck.mockResolvedValue({ phase: "teach", check: null, plan_done: true });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect(await screen.findByText(/every concept in today's plan/)).toBeTruthy();
  });

  it("renders the budget pause banner from a hard `budget` stream event; the chat input is disabled", async () => {
    // PKG-07 at the hard level: `phase`, then `budget`, then the stream ends with no `done`.
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onBudget?: (b: object) => void }) => {
      h.onBudget?.({ level: "hard", reset_at: "2026-09-27T00:00:00Z", scope: "daily_usd", session_capped: false });
      throw new Error("Chat stream ended without a done event.");
    });
    await resumedTeach();
    // ChatPanel's own testids — LoopLearn does not rename them.
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(api.streamLoopChat).toHaveBeenCalledWith("s2", "u1", "why?", expect.any(Object));
    expect(toast.error).not.toHaveBeenCalled(); // the pause is not an error
    expect((screen.getByTestId("tutor-input") as HTMLTextAreaElement).disabled).toBe(true);
  });

  it("a soft `budget` event renders nothing", async () => {
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onBudget?: (b: object) => void }) => {
      h.onBudget?.({ level: "soft", reset_at: null, scope: null, session_capped: false });
      return turn({ reply: "fine" });
    });
    await resumedTeach();
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByText("fine");
    expect(screen.queryByTestId("loop-budget-paused")).toBeNull();
  });

  it("renders the empty state from no_check_items", async () => {
    api.listLoopSessions.mockResolvedValue([]);
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "" });
    api.nextLoopProbe.mockResolvedValue({ done: true, phase: "plan", no_check_items: true });
    api.getLoopPlan.mockResolvedValue({ concepts: [], order: [], empty: true, phase: "teach" });
    render(<LoopLearn />);
    expect((await screen.findByTestId("loop-no-check-items")).textContent).toContain("No check items for this course yet");
  });

  it("keeps the knowledge map reachable", async () => {
    await resumedTeach();
    const link = await screen.findByTestId("loop-tree-link");
    expect(link.getAttribute("href")).toMatch(/^\/tree/);
  });
});

describe("LoopLearn — teach / check / feedback (A16, A46)", () => {
  it("the attempt box posts to /check/answer/stream, never as a chat turn", async () => {
    api.streamLoopCheckAnswer.mockResolvedValue(turn({ reply: "The answer: 0. Nice work.", phase: "feedback", graded: true, verdict: "correct" }));
    await withCheckItem();
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await screen.findByText("The answer: 0. Nice work.");
    expect(api.streamLoopCheckAnswer).toHaveBeenCalledWith("s2", "u1", "qh7", { answer: "n == 0", idk: false }, expect.any(Object));
    expect(api.streamLoopChat).not.toHaveBeenCalled();
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("feedback");
    expect(screen.queryByTestId("loop-check-prompt")).toBeNull(); // graded: the item closed
    expect(screen.getByTestId("loop-continue")).toBeTruthy();
  });

  it("'I don't know' in the attempt box posts idk: true", async () => {
    api.streamLoopCheckAnswer.mockResolvedValue(turn({ reply: "No problem.", graded: true, verdict: "idk" }));
    await withCheckItem();
    fireEvent.click(screen.getByTestId("loop-attempt-idk"));
    await waitFor(() => expect(api.streamLoopCheckAnswer).toHaveBeenCalledWith("s2", "u1", "qh7", { idk: true }, expect.any(Object)));
  });

  it("mc_reason attempts post option + reason", async () => {
    api.streamLoopCheckAnswer.mockResolvedValue(turn({ graded: true }));
    await withCheckItem({ ...pose, format: "mc_reason", options: [{ letter: "A", text: "x" }, { letter: "B", text: "y" }] });
    fireEvent.click(screen.getByTestId("loop-attempt-option-A"));
    fireEvent.change(screen.getByTestId("loop-attempt-reason"), { target: { value: "since x" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await waitFor(() => expect(api.streamLoopCheckAnswer).toHaveBeenCalledWith("s2", "u1", "qh7", { option: "A", reason: "since x", idk: false }, expect.any(Object)));
  });

  it.each(["retry", "transform"])("A46: retract (%s) discards every streamed token; done.reply is final", async (reason) => {
    let finish: (v: unknown) => void = () => {};
    api.streamLoopChat.mockImplementation((_s: string, _u: string, _m: string, h: { onToken?: (d: string) => void; onRetract?: (r: string) => void }) => {
      h.onToken?.("The answer is 42");
      h.onRetract?.(reason);
      h.onToken?.("Think about ");
      h.onToken?.("the base case.");
      return new Promise((resolve) => { finish = resolve; });
    });
    await resumedTeach();
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByText("Think about the base case.");
    expect(screen.queryByText(/The answer is 42/)).toBeNull();
    await act(async () => { finish(turn({ reply: "Think about the base case. What stops it?" })); });
    expect(await screen.findByText("Think about the base case. What stops it?")).toBeTruthy();
    expect(screen.queryByText(/The answer is 42/)).toBeNull();
  });

  it("leak_redacted: the settled bubble is done.reply, never the streamed tokens", async () => {
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onToken?: (d: string) => void }) => {
      h.onToken?.("raw streamed text");
      return turn({ reply: "clean [withheld] text", leak_redacted: true });
    });
    await resumedTeach();
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect(await screen.findByText("clean [withheld] text")).toBeTruthy();
    expect(screen.queryByText("raw streamed text")).toBeNull();
  });

  it("a teach turn that activates an item renders its pose (done.check)", async () => {
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onPhase?: (p: string) => void; onCheck?: (c: object) => void }) => {
      h.onCheck?.({ question_hash: "qh7", format: "free", difficulty: 2 });
      return turn({ reply: "Teach reply.", phase: "teach", check: pose });
    });
    await resumedTeach();
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "go on" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect((await screen.findByTestId("loop-check-prompt")).textContent).toContain("Why does it stop?");
  });

  it("a denied hint names its reason", async () => {
    api.requestLoopHint.mockResolvedValue({ denied: "no_genuine_attempt" });
    await withCheckItem();
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    const denied = await screen.findByTestId("loop-hint-denied");
    expect(denied.getAttribute("data-reason")).toBe("no_genuine_attempt");
    expect(api.requestLoopHintTurn).not.toHaveBeenCalled();
  });

  it("an allowed hint records the draft as an attempt, moves the rung, and shows the hint turn's text", async () => {
    api.postLoopAttempt.mockResolvedValue({ genuine: true, counted: true, attempts: 1, independent_s: 60 });
    api.requestLoopHint.mockResolvedValue({ rung: 1, intent: "Orient." });
    api.requestLoopHintTurn.mockResolvedValue(turn({ reply: "Look at when n reaches zero.", phase: "hint" }));
    await withCheckItem();
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "it keeps calling itself" } });
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    expect((await screen.findByTestId("loop-hint-reply")).textContent).toContain("Look at when n reaches zero.");
    expect(api.postLoopAttempt).toHaveBeenCalledWith("s2", "u1", "qh7", "it keeps calling itself");
    expect(api.requestLoopHint).toHaveBeenCalledWith("s2", "u1", "qh7");
    expect(api.requestLoopHintTurn).toHaveBeenCalledWith("s2", "u1");
  });

  it("a learner_state event fills loop-learner-state", async () => {
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onLearnerState?: (s: object) => void }) => {
      h.onLearnerState?.({ node_id: "n1", p_known: 0.42, band: "develop" });
      return turn();
    });
    await resumedTeach();
    const el = screen.getByTestId("loop-learner-state");
    expect(el.getAttribute("data-node-id")).toBe("");
    fireEvent.change(await screen.findByTestId("tutor-input"), { target: { value: "hi" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await waitFor(() => expect(screen.getByTestId("loop-learner-state").getAttribute("data-node-id")).toBe("n1"));
    expect(screen.getByTestId("loop-learner-state").getAttribute("data-p-known")).toBe("0.42");
    expect(screen.getByTestId("loop-learner-state").getAttribute("data-band")).toBe("develop");
    expect(screen.getByTestId("loop-tree-link").getAttribute("href")).toBe("/tree?node=n1");
  });
});

describe("LoopLearn — close (A60)", () => {
  const close = {
    summary: "You worked on recursion.",
    self_eval: "What would you explain differently next time?",
    if_then: "If I get stuck on a base case, then I trace n = 0 by hand.",
    concepts: [{ node_id: "n1", p_before: 0.35, p_after: 0.6 }],
    misconceptions: [],
    model_written: true,
  };

  it("renders the summary, the self-evaluation as a reflection prompt (no input), and the plan", async () => {
    api.closeLoopSession.mockResolvedValue({ close, model_written: true, close_phase: "teach" });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    expect((await screen.findByTestId("loop-close-summary")).textContent).toContain("You worked on recursion.");
    const selfEval = screen.getByTestId("loop-close-self-eval");
    expect(selfEval.textContent).toContain("What would you explain differently next time?");
    expect(selfEval.querySelector("input, textarea")).toBeNull(); // nothing is saved (A60)
    expect(screen.getByTestId("loop-close-if-then").textContent).toContain("If I get stuck");
    expect(screen.getByTestId("loop-close-done")).toBeTruthy();
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("close");
    expect(api.closeLoopSession).toHaveBeenCalledWith("s2", "u1");
  });

  it("a 409 while a check is being graded asks to retry, not an error toast", async () => {
    api.closeLoopSession.mockRejectedValue(
      new ApiError("x", 409, { body: { detail: "a check is being graded; close again in a moment" } }),
    );
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    expect(await screen.findByText(/close again in a moment/i)).toBeTruthy();
    expect(toast.error).not.toHaveBeenCalled();
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach");
  });
});
