// @vitest-environment jsdom
/**
 * Tutor V2 behaviour (PR #866 review): the ?topic= offer, the hide_* nav flags,
 * the phone drawer as a modal, a hint that is loading, the check-in's reason
 * label, a failed chat turn's Retry, the due-review count, failed list reads,
 * Send to tutor's note, the plan in the history, the layout at ~950px, the
 * wrap-up's caption and the "no check question yet" note. Every loop client
 * is mocked, as in LoopLearn.test.tsx.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }));
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => viewport.mobile }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => search.params,
  usePathname: () => "/learn",
  useRouter: () => router,
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true, isAuthenticated: true }) }));
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
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

const api = vi.hoisted(() => ({
  getCourses: vi.fn(), listLoopSessionsFor: vi.fn(), resumeSession: vi.fn(), getLoopSessionStatus: vi.fn(),
  startLoopSession: vi.fn(), setLoopGoal: vi.fn(), nextLoopProbe: vi.fn(), answerLoopProbe: vi.fn(),
  getLoopPlan: vi.fn(), approveLoopPlan: vi.fn(), streamLoopChat: vi.fn(), streamLoopCheckAnswer: vi.fn(),
  postLoopAttempt: vi.fn(), requestLoopHint: vi.fn(), requestLoopHintTurn: vi.fn(), closeLoopSession: vi.fn(),
  getGraph: vi.fn(), nextLoopCheck: vi.fn(), submitLoopRating: vi.fn(), reportCheckItem: vi.fn(),
  streamLoopPrequestionAnswer: vi.fn(), postLoopSelfExplain: vi.fn(), getSessions: vi.fn(), getDocuments: vi.fn(),
  getReviewSummary: vi.fn(), submitFeedback: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));
const flags = vi.hoisted(() => ({}) as Record<string, string>);
vi.mock("@/context/FlagsContext", () => ({ useFlag: (key: string) => flags[key] ?? "off" }));
const retention = vi.hoisted(() => ({ courseIds: [] as string[] }));
vi.mock("@/context/RetentionDueContext", async (orig) => ({
  ...(await orig<typeof import("@/context/RetentionDueContext")>()),
  useRetentionDue: () => ({ due: retention.courseIds.length > 0, courseIds: retention.courseIds, refresh: () => {} }),
}));

import { ApiError } from "@/lib/api";
import { __resetFeedbackPacingForTests } from "@/lib/feedbackPacing";
import { markNoteCardShown } from "@/lib/crisisSupport";
import { LoopLearn } from "./LoopLearn";
import { PROBE_PHASE_OPENERS } from "./loopHistory";
import crisisFixture from "@/test-utils/crisisSupport.json";

const course = { course_id: "c1", course_name: "Intro CS", course_code: "CS 101" };
const open = (id: string, phase: string, topic = `t ${id}`) => ({ session_id: id, topic, started_at: "2026-09-21T10:00:00Z", phase });
const listed = (sessions: object[], resume: object | null = null) => ({ sessions, resume });
const probeItem = { done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1, prompt: "What is a base case?", options: null };
const pose = { question_hash: "qh7", format: "free", difficulty: 2, prompt: "Why does it stop?", options: null };
const status = (over: object = {}) => ({ active: true, session_id: "s2", loop_phase: "teach", phase: "teach", check: null, goal: null, diagnosis: null, ...over });
const turn = (over: object = {}) => ({ reply: "ok", graph_update: {}, mastery_changes: [], leak_redacted: false, ...over });
const closeRecord = { summary: "Wrapped up.", self_eval: "What next?", if_then: "", concepts: [], misconceptions: [], model_written: false };
const summary = (flashcard: number, check: number) => ({
  due: { flashcard, check }, in_budget: 0, unservable: 0, paused: 0, budget_min: 20, remaining_budget_s: 1200, retention_target: 0.9,
});
const OPENER = PROBE_PHASE_OPENERS[0];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  viewport.mobile = false;
  retention.courseIds = [];
  for (const key of Object.keys(flags)) delete flags[key];
  search.params = new URLSearchParams();
  Object.values(api).forEach((f) => f.mockReset());
  Object.values(toast).forEach((f) => f.mockReset());
  __resetFeedbackPacingForTests();
  localStorage.clear();
  sessionStorage.clear();
  api.getCourses.mockResolvedValue({ courses: [course] });
  api.getLoopSessionStatus.mockImplementation(async (id: string) => status({ session_id: id }));
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.getSessions.mockResolvedValue({ sessions: [] });
  api.getDocuments.mockResolvedValue({ documents: [] });
  api.getReviewSummary.mockResolvedValue(summary(0, 0));
  api.submitFeedback.mockResolvedValue({ ok: true });
  api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [{ id: "m1", role: "assistant", content: "welcome back", created_at: "" }] });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function resumedTeach(topic?: string) {
  api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "teach", topic)]));
  render(<LoopLearn />);
  await screen.findByText("welcome back");
}

async function withCheckItem() {
  api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
  await resumedTeach();
  fireEvent.click(await screen.findByTestId("loop-check-me"));
  await screen.findByTestId("loop-check-prompt");
}

describe("F3 — a ?topic= link never offers to restart the session already on it", () => {
  it("no offer when the open session is on the link's topic", async () => {
    search.params = new URLSearchParams("topic=Recursion");
    await resumedTeach("Recursion");
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s2"));
    expect(screen.queryByTestId("loop-topic-offer")).toBeNull();
  });

  it("the session the link itself started is not offered again once it teaches", async () => {
    search.params = new URLSearchParams("topic=Recursion");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER });
    api.nextLoopProbe.mockResolvedValue({ done: true, phase: "plan" });
    api.getLoopPlan.mockResolvedValue({ concepts: [{ node_id: "n1", concept_name: "Recursion", kind: "new", p_known: 0.3 }], order: [] });
    api.approveLoopPlan.mockResolvedValue({ phase: "teach", concept_ids: ["n1"] });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-plan-approve"));
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach"));
    expect(screen.queryByTestId("loop-topic-offer")).toBeNull();
  });

  it("still offers it while another topic's session is open", async () => {
    search.params = new URLSearchParams("topic=Recursion");
    await resumedTeach("Sorting");
    expect(await screen.findByTestId("loop-topic-offer")).toBeTruthy();
  });
});

describe("F5 — the hide_study and hide_library nav flags", () => {
  it("hide_study: no link to Study anywhere — budget banner, panel, home, wrap-up — and no due read", async () => {
    flags.hide_study = "on";
    retention.courseIds = ["c1"];
    api.streamLoopChat.mockImplementation(async (_s: string, _u: string, _m: string, h: { onBudget?: (b: object) => void }) => {
      h.onBudget?.({ level: "hard", reset_at: new Date(Date.now() + 3_600_000).toISOString(), scope: "daily_usd", session_capped: false });
      throw new Error("Chat stream ended without a done event.");
    });
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    await resumedTeach();
    expect(screen.queryByTestId("tutor-panel-review")).toBeNull();
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect(await screen.findByTestId("loop-budget-paused")).toBeTruthy();
    expect(screen.queryByTestId("loop-budget-study-link")).toBeNull();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    await screen.findByTestId("loop-close-done");
    expect(screen.queryByTestId("loop-close-study-link")).toBeNull();
    expect(screen.queryByTestId("loop-close-retention-link")).toBeNull();
    fireEvent.click(screen.getByTestId("loop-new-session"));
    await screen.findByTestId("tutor-home");
    expect(screen.queryByTestId("tutor-home-due")).toBeNull();
    expect(screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/study"))).toEqual([]);
    expect(api.getReviewSummary).not.toHaveBeenCalled();
  });

  it("hide_library: no attach button, no source-material link, no Add material", async () => {
    flags.hide_library = "on";
    api.getLoopSessionStatus.mockResolvedValue(status({ goal: { text: "", target_node_ids: ["n1"] }, practice_unavailable_node_ids: ["n1"] }));
    await resumedTeach();
    expect(await screen.findByTestId("loop-practice-unavailable")).toBeTruthy();
    expect(screen.queryByTestId("loop-practice-sources")).toBeNull();
    expect(screen.queryByTestId("tutor-attach")).toBeNull();
    fireEvent.click(screen.getByTestId("tutor-course-c1"));
    const page = await screen.findByTestId("tutor-course-page");
    await waitFor(() => expect(page.textContent).toContain("0 files"));
    expect(within(page).queryAllByRole("link").filter((a) => a.getAttribute("href") === "/library")).toEqual([]);
  });

  it("both visible (the default): the links are there", async () => {
    flags.hide_library = "off";
    await resumedTeach();
    expect(screen.getByTestId("tutor-attach").getAttribute("href")).toBe("/library");
    expect(screen.getByTestId("tutor-panel-review").getAttribute("href")).toBe("/study");
  });
});

describe("F6 — the phone's drawer is a modal dialog; Hide hands focus back", () => {
  it("is a dialog that makes the page inert, keeps Tab inside, and returns focus on Hide, Escape or the scrim", async () => {
    viewport.mobile = true;
    await resumedTeach();
    const toggle = screen.getByTestId("tutor-sidebar-show");
    for (const close of ["hide", "escape", "scrim"] as const) {
      fireEvent.click(toggle);
      const drawer = await screen.findByRole("dialog", { name: "Tutor sessions" });
      expect(drawer.getAttribute("aria-modal")).toBe("true");
      expect(screen.getByTestId("tutor-sidebar-hide")).toHaveFocus(); // the drawer takes focus
      const page = screen.getByTestId("loop-phase").closest("body > *");
      expect(page?.hasAttribute("inert")).toBe(true);
      // Tab past the last control comes back to the first, Shift+Tab the other way
      const controls = Array.from(drawer.querySelectorAll<HTMLElement>("button:not([disabled]), input, a[href]"));
      controls.at(-1)!.focus();
      fireEvent.keyDown(controls.at(-1)!, { key: "Tab" });
      expect(controls[0]).toHaveFocus();
      fireEvent.keyDown(controls[0], { key: "Tab", shiftKey: true });
      expect(controls.at(-1)).toHaveFocus();
      if (close === "hide") fireEvent.click(screen.getByTestId("tutor-sidebar-hide"));
      else if (close === "escape") fireEvent.keyDown(controls[0], { key: "Escape" });
      else fireEvent.click(screen.getByTestId("tutor-drawer-scrim"));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(page?.hasAttribute("inert")).toBe(false);
      expect(screen.getByTestId("tutor-sidebar-show")).toHaveFocus();
    }
  });

  it("while the drawer is open, nothing behind it takes focus (modalOpen sees it)", async () => {
    viewport.mobile = true;
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-sidebar-show"));
    await screen.findByRole("dialog");
    expect(document.querySelector('[aria-modal="true"]')).toBe(screen.getByTestId("tutor-drawer"));
  });

  it("the session panel's Hide moves focus to its Show button, and Show to its Hide", async () => {
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-panel-hide"));
    expect(screen.queryByTestId("loop-rail")).toBeNull();
    expect(screen.getByTestId("tutor-panel-toggle")).toHaveFocus();
    fireEvent.click(screen.getByTestId("tutor-panel-toggle"));
    expect(screen.getByTestId("tutor-panel-hide")).toHaveFocus();
    fireEvent.click(screen.getByTestId("tutor-sidebar-hide"));
    expect(screen.getByTestId("tutor-sidebar-show")).toHaveFocus();
  });
});

describe("F7 — a chat message never costs the student a hint", () => {
  it("the composer is held while a hint loads, and the hint lands", async () => {
    const hintTurn = deferred<ReturnType<typeof turn>>();
    api.requestLoopHint.mockResolvedValue({ rung: 1 });
    api.requestLoopHintTurn.mockReturnValue(hintTurn.promise);
    await withCheckItem();
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    await waitFor(() => expect(api.requestLoopHintTurn).toHaveBeenCalled());
    const input = screen.getByTestId("tutor-input") as HTMLTextAreaElement;
    expect(input.disabled).toBe(true);
    await act(async () => { hintTurn.resolve(turn({ reply: "Look at when n reaches zero.", phase: "check" })); });
    expect((await screen.findByTestId("loop-hint-reply")).textContent).toContain("Look at when n reaches zero.");
    await waitFor(() => expect(input.disabled).toBe(false));
    expect(api.streamLoopChat).not.toHaveBeenCalled();
  });

  it("an earned hint whose text failed survives a chat turn: Retry earned hint asks for the text only", async () => {
    api.requestLoopHint.mockResolvedValue({ rung: 2 });
    api.requestLoopHintTurn.mockRejectedValueOnce(new ApiError("unavailable", 503))
      .mockResolvedValueOnce(turn({ phase: "hint", reply: "The hint you earned." }));
    api.streamLoopChat.mockResolvedValue(turn({ reply: "Think about the smallest input.", phase: "check" }));
    await withCheckItem();
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    await screen.findByRole("button", { name: "Retry earned hint" });
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "what is n here?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByText("Think about the smallest input.");
    fireEvent.click(screen.getByRole("button", { name: "Retry earned hint" }));
    expect((await screen.findByTestId("loop-hint-reply")).textContent).toContain("The hint you earned.");
    expect(api.requestLoopHint).toHaveBeenCalledTimes(1); // the rung was not asked for (or charged) again
  });
});

describe("F9 — the check-in's reason field is named by its visible label", () => {
  it("'In one sentence: why?' is the input's accessible name", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "probe")]));
    api.getLoopSessionStatus.mockResolvedValue(status({ loop_phase: "probe", phase: "probe" }));
    api.nextLoopProbe.mockResolvedValue({ ...probeItem, format: "mc_reason", options: [{ letter: "A", text: "x" }, { letter: "B", text: "y" }] });
    render(<LoopLearn />);
    expect(await screen.findByRole("textbox", { name: "In one sentence: why?" })).toBe(screen.getByTestId("loop-probe-reason"));
  });

  it("the check card's fields are named by their visible labels too", async () => {
    await withCheckItem();
    expect(screen.getByRole("textbox", { name: "Your answer — this is what gets checked" })).toBe(screen.getByTestId("loop-attempt-input"));
  });
});

describe("F11a — a failed chat turn offers Retry and gives the message back", () => {
  it("shows an interrupted turn with Retry, restores the composer, and Retry sends it once", async () => {
    api.streamLoopChat
      .mockRejectedValueOnce(new ApiError("upstream unavailable", 503))
      .mockResolvedValueOnce(turn({ reply: "Here is why." }));
    await resumedTeach();
    const input = screen.getByTestId("tutor-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "why does it stop?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    const retry = await screen.findByTestId("tutor-retry");
    expect(screen.getByTestId("tutor-interrupted")).toBeTruthy();
    await waitFor(() => expect(input.value).toBe("why does it stop?"));
    fireEvent.click(retry);
    await screen.findByText("Here is why.");
    expect(api.streamLoopChat).toHaveBeenCalledTimes(2);
    expect(api.streamLoopChat).toHaveBeenLastCalledWith("s2", "u1", "why does it stop?", expect.any(Object));
    expect(screen.getAllByText("why does it stop?").filter((el) => el.tagName !== "TEXTAREA")).toHaveLength(1);
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
    await waitFor(() => expect(input.value).toBe("")); // not sent a second time from the composer
  });

  it("a budget pause gives the message back without a Retry", async () => {
    api.streamLoopChat.mockRejectedValueOnce(Object.assign(new Error(JSON.stringify({ detail: "ai budget reached", reset_at: null })), { status: 429 }));
    await resumedTeach();
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect(await screen.findByTestId("loop-budget-paused")).toBeTruthy();
    expect(screen.queryByTestId("tutor-retry")).toBeNull();
  });
});

describe("F11b — the due line counts the reviews that are due", () => {
  it("home and panel show the review queue's count, with the retention flag off", async () => {
    api.getReviewSummary.mockResolvedValue(summary(2, 1));
    await resumedTeach();
    await waitFor(() => expect(screen.getByTestId("tutor-panel-due-count").textContent).toBe("3 reviews due"));
    expect(api.getReviewSummary).toHaveBeenCalledWith("u1");
    fireEvent.click(screen.getByTestId("loop-new-session"));
    expect((await screen.findByTestId("tutor-home-due")).textContent).toBe("Review what's due · 3");
  });

  it("nothing due: the panel says so and the home offers no review pill", async () => {
    retention.courseIds = ["c1"]; // a retention check is not a review
    await resumedTeach();
    await waitFor(() => expect(screen.getByTestId("tutor-panel-due-count").textContent).toBe("Nothing due right now"));
    fireEvent.click(screen.getByTestId("loop-new-session"));
    await screen.findByTestId("tutor-home");
    expect(screen.queryByTestId("tutor-home-due")).toBeNull();
  });
});

describe("F11c — a failed read is an error with a retry, never an empty state", () => {
  it("sessions and material that did not load say so, and Try again reads them again", async () => {
    api.getSessions.mockRejectedValue(new Error("down"));
    api.getDocuments.mockRejectedValueOnce(new Error("down"));
    await resumedTeach();
    expect(await screen.findByTestId("tutor-recents-error")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-course-c1"));
    const page = await screen.findByTestId("tutor-course-page");
    expect(await within(page).findByTestId("tutor-course-materials-error")).toBeTruthy();
    expect(page.textContent).not.toContain("No material yet");
    expect(page.textContent).not.toContain("No sessions yet");
    api.getDocuments.mockResolvedValue({ documents: [{ id: "d1", file_name: "Week 3 slides.pptx", course_id: "c1" }] });
    fireEvent.click(within(screen.getByTestId("tutor-course-materials-error")).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(page.textContent).toContain("Week 3 slides.pptx"));
    api.getSessions.mockResolvedValue({ sessions: [] });
    const sessionsError = within(page).getByTestId("tutor-course-sessions-error");
    fireEvent.click(within(sessionsError).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(page).queryByTestId("tutor-course-sessions-error")).toBeNull());
    expect(screen.queryByTestId("tutor-recents-error")).toBeNull();
  });
});

describe("G1 — Send to tutor names its note", () => {
  it("a start on the note's title sends from_note_id; the card beside the session shows over it", async () => {
    search.params = new URLSearchParams("topic=Week%203%20notes&note=note-1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER, crisis_support: crisisFixture, crisis_support_alongside: true });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Week 3 notes", "", undefined, "note-1"));
    expect(await screen.findByTestId("crisis-support-card")).toBeTruthy();
    expect(await screen.findByTestId("loop-probe-item")).toBeTruthy(); // the session opened
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("s9");
  });

  it("the card the notetaker just showed does not pop up again", async () => {
    search.params = new URLSearchParams("topic=Week%203%20notes&note=note-1");
    markNoteCardShown("note-1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER, crisis_support: crisisFixture, crisis_support_alongside: true });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-probe-item")).toBeTruthy();
    expect(screen.queryByTestId("crisis-support-card")).toBeNull();
  });

  it("a start on any other topic does not name the note", async () => {
    search.params = new URLSearchParams("topic=Week%203%20notes&note=note-1");
    await resumedTeach("Sorting");
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    fireEvent.click(screen.getByTestId("loop-new-session"));
    fireEvent.click(await screen.findByTestId("loop-start-guided"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalled());
    expect(api.startLoopSession.mock.calls[0][5]).toBeNull();
  });
});

describe("U2 — the history stays true after the plan is approved", () => {
  const plan = [
    { node_id: "n2", concept_name: "Stacks", kind: "review", p_known: 0.5 },
    { node_id: "n1", concept_name: "Recursion", kind: "new", p_known: 0.3 },
  ];

  it("the opener's row shows the approved plan, not the check-in it promised", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER });
    api.nextLoopProbe.mockResolvedValue({ done: true, phase: "plan" });
    api.getLoopPlan.mockResolvedValue({ concepts: plan, order: [] });
    api.approveLoopPlan.mockResolvedValue({ phase: "teach", concept_ids: ["n2", "n1"] });
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("loop-start-guided"));
    fireEvent.click(await screen.findByTestId("loop-plan-approve"));
    const log = await screen.findByTestId("tutor-messages");
    expect(log.textContent).toContain("Here's today's plan.");
    expect(log.textContent).toContain("1. Stacks — Due for review");
    expect(log.textContent).toContain("2. Recursion — New");
    expect(log.textContent).not.toContain("Welcome!");
  });

  it("a resumed session shows the plan /status reports", async () => {
    api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [
      { id: "m0", role: "assistant", content: OPENER, created_at: "" },
      { id: "m1", role: "assistant", content: "welcome back", created_at: "" },
    ] });
    api.getLoopSessionStatus.mockResolvedValue(status({ approved_plan: { concepts: [{ node_id: "n1", concept_name: "Recursion", kind: "new" }], cursor: 0 } }));
    await resumedTeach();
    await waitFor(() => expect(screen.getByTestId("tutor-messages").textContent).toContain("1. Recursion — New"));
    expect(screen.getByTestId("tutor-messages").textContent).not.toContain("Welcome!");
  });

  it("an unknown plan drops the opener rather than describe finished steps", async () => {
    api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [
      { id: "m0", role: "assistant", content: OPENER, created_at: "" },
      { id: "m1", role: "assistant", content: "welcome back", created_at: "" },
    ] });
    await resumedTeach();
    expect(screen.getByTestId("tutor-messages").textContent).not.toContain("Welcome!");
    expect(screen.getByTestId("tutor-messages").textContent).not.toContain("Here's today's plan");
  });
});

describe("U5 — the conversation keeps a readable width", () => {
  function stubShellWidth(width: number) {
    vi.stubGlobal("ResizeObserver", class {
      constructor(private cb: (entries: { contentRect: { width: number } }[]) => void) {}
      observe() { this.cb([{ contentRect: { width } }]); }
      disconnect() {}
    });
  }

  it("about 950px wide: the session panel gives way; the student can still open it", async () => {
    stubShellWidth(900);
    await resumedTeach();
    await waitFor(() => expect(screen.queryByTestId("loop-rail")).toBeNull());
    expect(screen.getByTestId("tutor-sidebar")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-panel-toggle"));
    expect(screen.getByTestId("loop-rail")).toBeTruthy(); // their choice stands
    expect(screen.queryByTestId("tutor-sidebar")).toBeNull(); // the sidebar gives way to it
  });

  it("wide: both columns stay open", async () => {
    stubShellWidth(1400);
    await resumedTeach();
    expect(screen.getByTestId("loop-rail")).toBeTruthy();
    expect(screen.getByTestId("tutor-sidebar")).toBeTruthy();
  });
});

describe("U8 — the wrap-up's caption explains only a list that is there", () => {
  it.each([
    ["nothing measured: no caption", [], false],
    ["concepts measured: the caption", [{ node_id: "n1", p_before: 0.3, p_after: 0.6 }], true],
  ] as const)("%s", async (_, concepts, shown) => {
    api.closeLoopSession.mockResolvedValue({ close: { ...closeRecord, concepts }, model_written: false, close_phase: "teach" });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    await screen.findByTestId("loop-close-done");
    expect(!!screen.queryByTestId("loop-close-moved-caption")).toBe(shown);
  });
});

describe("U9 — How was that session? is asked on the wrap-up, with its ends labelled", () => {
  it("asks once per session (paced), never after the student has left", async () => {
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    const rating = await screen.findByTestId("loop-close-rating");
    expect(within(rating).getByRole("heading", { name: "How was that session?" })).toBeTruthy();
    expect(within(rating).getByText("1 = Frustrating")).toBeTruthy();
    expect(within(rating).getByText("4 = Great session")).toBeTruthy();
    expect(sessionStorage.getItem("sapling_last_session_context")).toBeNull();
  });

  it("a session already asked about is not asked again", async () => {
    localStorage.setItem("sapling_feedback_sessions", JSON.stringify(["s2"]));
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("loop-close-button"));
    await screen.findByTestId("loop-close-done");
    expect(screen.queryByTestId("loop-close-rating")).toBeNull();
  });
});

describe("NC — Check me on concepts with no check question", () => {
  it("names them instead of claiming the plan is done", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ approved_plan: { concepts: [
      { node_id: "n1", concept_name: "Recursion", kind: "new" }, { node_id: "n2", concept_name: "Stacks", kind: "new" },
    ], cursor: 0 } }));
    api.nextLoopCheck.mockResolvedValue({ phase: "teach", check: null, plan_done: true, checks_unavailable_node_ids: ["n1", "n2"] });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    const note = await screen.findByText(/No check questions are ready yet/);
    expect(note.textContent).toBe(
      "No check questions are ready yet for Recursion and Stacks. You can keep learning with the tutor, or wrap up the session when you're ready.",
    );
    expect(screen.queryByText(/every concept in today's plan/)).toBeNull();
  });

  it("an empty list keeps the plan-done note, and preparing keeps its own", async () => {
    api.nextLoopCheck.mockResolvedValueOnce({ phase: "teach", check: null, plan_done: true, checks_unavailable_node_ids: [] })
      .mockResolvedValueOnce({ phase: "teach", check: null, plan_done: true, preparing: true, checks_unavailable_node_ids: ["n1"] });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect(await screen.findByText(/every concept in today's plan/)).toBeTruthy();
    await waitFor(() => expect((screen.getByTestId("loop-check-me") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("loop-check-me"));
    expect(await screen.findByText("Preparing practice questions from your upload…", { selector: "[role=status]" })).toBeTruthy();
  });
});

describe("A1/A2 — an answer whose check the server closed selects another check", () => {
  const closedDetails = [
    ["moved past", "This check was closed while your answer was graded. Select another check to continue.", /nothing was recorded/],
    ["refused for good", "This answer could not be recorded. Select another check to continue.", /couldn't be recorded/],
  ] as const;
  it.each(closedDetails)("a 409 (%s) frees the box, says why and asks /check/next — no error toast", async (_why, detail, copy) => {
    const next = { ...pose, question_hash: "qh8", prompt: "What does the stack hold?" };
    api.nextLoopCheck.mockResolvedValueOnce({ phase: "check", check: pose }).mockResolvedValueOnce({ phase: "check", check: next });
    api.streamLoopCheckAnswer.mockRejectedValue(new ApiError(JSON.stringify({ detail }), 409));
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    await screen.findByTestId("loop-check-prompt");
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await waitFor(() => expect(api.nextLoopCheck).toHaveBeenCalledTimes(2));
    expect((await screen.findByTestId("loop-check-prompt")).textContent).toContain("What does the stack hold?");
    expect(toast.info).toHaveBeenCalledWith(expect.stringMatching(copy));
    expect(toast.error).not.toHaveBeenCalled();
    expect(api.getLoopSessionStatus).toHaveBeenCalledTimes(1); // the resume read only: no reconcile
  });

  it("any other 409 on a submission still goes the old way", async () => {
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
    api.streamLoopCheckAnswer.mockRejectedValue(new ApiError(JSON.stringify({ detail: "already graded" }), 409));
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    await screen.findByTestId("loop-check-prompt");
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    await waitFor(() => expect(api.getLoopSessionStatus).toHaveBeenCalledTimes(2)); // reconcile
    expect(api.nextLoopCheck).toHaveBeenCalledTimes(1);
    expect(toast.info).not.toHaveBeenCalled();
  });
});
