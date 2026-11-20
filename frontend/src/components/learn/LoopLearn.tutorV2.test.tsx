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
  getReviewSummary: vi.fn(), submitFeedback: vi.fn(), renameSession: vi.fn(), deleteSession: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));
const flags = vi.hoisted(() => ({}) as Record<string, string>);
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (key: string) => flags[key] ?? "off",
  useFlagMap: () => ({ flags, ready: true }),
}));
const retention = vi.hoisted(() => ({ courseIds: [] as string[] }));
vi.mock("@/context/RetentionDueContext", async (orig) => ({
  ...(await orig<typeof import("@/context/RetentionDueContext")>()),
  useRetentionDue: () => ({ due: retention.courseIds.length > 0, courseIds: retention.courseIds, refresh: () => {} }),
}));

import { ApiError, ChatStreamError } from "@/lib/api";
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

describe("F5 — the hide_study, hide_library and hide_tree nav flags", () => {
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

  it("hide_tree: no map link in the session panel, on a phone, or on the no-course card", async () => {
    flags.hide_tree = "on";
    await resumedTeach();
    expect(screen.getByTestId("tutor-map-key")).toBeTruthy(); // the panel's own map section stays
    expect(screen.queryByTestId("loop-tree-link")).toBeNull();
    cleanup();
    viewport.mobile = true;
    await resumedTeach();
    expect(screen.queryByTestId("loop-tree-link")).toBeNull();
    expect(screen.getAllByTestId("loop-new-session").length).toBeGreaterThan(0);
    cleanup();
    viewport.mobile = false;
    api.getCourses.mockResolvedValue({ courses: [] });
    render(<LoopLearn />);
    await screen.findByTestId("loop-no-course");
    expect(screen.getByTestId("loop-no-course-link").getAttribute("href")).toBe("/dashboard"); // Z61: courses are added there
    expect(screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/tree"))).toEqual([]);
  });

  it("the tree visible (the default): Open map and the phone's Map point at /tree", async () => {
    await resumedTeach();
    expect(screen.getByTestId("loop-tree-link").getAttribute("href")).toMatch(/^\/tree/);
    cleanup();
    viewport.mobile = true;
    await resumedTeach();
    expect(screen.getByTestId("loop-tree-link").getAttribute("href")).toMatch(/^\/tree/);
    cleanup();
    viewport.mobile = false;
    api.getCourses.mockResolvedValue({ courses: [] });
    render(<LoopLearn />);
    expect((await screen.findByTestId("loop-no-course-link")).getAttribute("href")).toBe("/dashboard");
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
    expect(input.disabled).toBe(true); // K06: the check is still open, and a chat would only re-pose it
    expect(api.streamLoopChat).not.toHaveBeenCalled();
  });

  it("an earned hint whose text failed: Retry earned hint asks for the text only (no chat meanwhile, K06)", async () => {
    api.requestLoopHint.mockResolvedValue({ rung: 2 });
    api.requestLoopHintTurn.mockRejectedValueOnce(new ApiError("unavailable", 503))
      .mockResolvedValueOnce(turn({ phase: "hint", reply: "The hint you earned." }));
    await withCheckItem();
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    await screen.findByRole("button", { name: "Retry earned hint" });
    expect(screen.getByTestId("tutor-input")).toBeDisabled();
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
    // the heading counts only what loaded as "at least" (the loop's open session), never "0 sessions"
    expect(within(page).getByTestId("tutor-course-sessions-count").textContent).toBe("At least 1 session");
    api.getDocuments.mockResolvedValue({ documents: [{ id: "d1", file_name: "Week 3 slides.pptx", course_id: "c1" }] });
    fireEvent.click(within(screen.getByTestId("tutor-course-materials-error")).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(page.textContent).toContain("Week 3 slides.pptx"));
    api.getSessions.mockResolvedValue({ sessions: [] });
    const sessionsError = within(page).getByTestId("tutor-course-sessions-error");
    fireEvent.click(within(sessionsError).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(page).queryByTestId("tutor-course-sessions-error")).toBeNull());
    expect(within(page).getByTestId("tutor-course-sessions-count").textContent).toBe("1 session");
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

  it("a refused start that carries the card shows it beside the error (crisis-support.md)", async () => {
    search.params = new URLSearchParams("topic=Week%203%20notes&note=note-1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockRejectedValue(new ApiError("Too many requests", 429, { body: { detail: "Too many requests", crisis_support: crisisFixture, crisis_support_alongside: true } }));
    render(<LoopLearn />);
    expect(await screen.findByTestId("crisis-support-card")).toBeTruthy();
    expect(await screen.findByTestId("loop-start-error")).toBeTruthy(); // and the start offers its retry
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });

  it("a refused start whose card the notetaker just showed does not pop it up again", async () => {
    search.params = new URLSearchParams("topic=Week%203%20notes&note=note-1");
    markNoteCardShown("note-1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.startLoopSession.mockRejectedValue(new ApiError("Too many requests", 429, { body: { detail: "Too many requests", crisis_support: crisisFixture, crisis_support_alongside: true } }));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-start-error")).toBeTruthy();
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

  it("K28: a goal session's plan keeps its reasons after a reload (/status sends them)", async () => {
    api.resumeSession.mockResolvedValue({ session: { id: "s2" }, messages: [
      { id: "m0", role: "assistant", content: OPENER, created_at: "" },
      { id: "m1", role: "assistant", content: "welcome back", created_at: "" },
    ] });
    api.getLoopSessionStatus.mockResolvedValue(status({
      goal: { text: "", target_node_ids: ["n2"] },
      approved_plan: { concepts: [
        { node_id: "n1", concept_name: "Binary", kind: "new", reason: "prerequisite" },
        { node_id: "n2", concept_name: "Bitwise", kind: "new", reason: "goal" },
      ], cursor: 0 },
    }));
    await resumedTeach();
    await waitFor(() => expect(screen.getByTestId("tutor-messages").textContent).toContain("1. Binary — Prerequisite for your goal"));
    expect(screen.getByTestId("tutor-messages").textContent).toContain("2. Bitwise — Your selected goal");
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

describe("B4 — a replayed turn changes no state", () => {
  it("shows the replayed reply and leaves the note, phase and check as they were", async () => {
    api.nextLoopCheck.mockResolvedValue({ phase: "teach", check: null, plan_done: true, checks_unavailable_node_ids: [] });
    api.streamLoopChat.mockResolvedValueOnce({ reply: "The reply you already got.", graph_update: {}, mastery_changes: [], replayed: true })
      .mockResolvedValueOnce(turn({ reply: "A fresh turn.", phase: "teach" }));
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect(await screen.findByText(/every concept in today's plan/)).toBeTruthy();
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "and then?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByText("The reply you already got.");
    expect(screen.getByText(/every concept in today's plan/)).toBeTruthy(); // a replay is not a served turn
    expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("teach");
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "one more" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByText("A fresh turn.");
    await waitFor(() => expect(screen.queryByText(/every concept in today's plan/)).toBeNull()); // a served turn clears it
  });
});

describe("Z58 — Try again after a failed start repeats that start", () => {
  const node = { id: "n1", concept_name: "Recursion", mastery_tier: "struggling", mastery_score: 0.2, is_subject_root: false, subject: "Intro CS", course_id: "c1" };
  beforeEach(() => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.getGraph.mockResolvedValue({ nodes: [node], edges: [], stats: {} });
    api.startLoopSession.mockRejectedValueOnce(new ApiError("boom", 503)).mockResolvedValue({ session_id: "s9", initial_message: "" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
  });

  it("'Start with X' retries on X", async () => {
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-home-start-with"));
    fireEvent.click(await screen.findByTestId("loop-start-retry"));
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession.mock.calls.map((c) => c[2])).toEqual(["Recursion", "Recursion"]);
  });

  it("'Set a goal' retries the start on that goal (K30: the goal is set before the start)", async () => {
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-home-goal"));
    fireEvent.click(await screen.findByTestId("loop-goal-target-n1"));
    fireEvent.click(screen.getByTestId("loop-goal-save"));
    fireEvent.click(await screen.findByTestId("loop-start-retry"));
    await screen.findByTestId("loop-probe-item");
    const goal = { text: "", target_node_ids: ["n1"] };
    expect(api.startLoopSession.mock.calls.map((c) => c[4])).toEqual([goal, goal]);
  });
});

describe("Z64 — one open session per course, from the read-only view too", () => {
  it("'Start a new session' on a read-only transcript wraps up the course's open session first", async () => {
    const today = new Date().toISOString();
    api.getSessions.mockResolvedValue({ sessions: [
      { id: "old", topic: "Big-O practice", mode: "socratic", course_id: "c1", started_at: today, ended_at: null, message_count: 3, is_active: true, loop_open: false },
    ] });
    api.resumeSession.mockImplementation(async (id: string) => ({ session: { id, topic: "x" }, messages: [{ id: `m-${id}`, role: "assistant", content: id === "s2" ? "welcome back" : `chat ${id}`, created_at: "" }] }));
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: "" });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("tutor-recent-old"));
    await screen.findByTestId("loop-readonly-transcript");
    fireEvent.click(screen.getByTestId("loop-readonly-new-session"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledTimes(1));
    expect(api.closeLoopSession).toHaveBeenCalledWith("s2", "u1");
    expect(api.closeLoopSession.mock.invocationCallOrder[0]).toBeLessThan(api.startLoopSession.mock.invocationCallOrder[0]);
  });

  it("the Tutor home reached from a read-only transcript says which open session a start wraps up", async () => {
    const today = new Date().toISOString();
    api.getSessions.mockResolvedValue({ sessions: [
      { id: "old", topic: "Big-O practice", mode: "socratic", course_id: "c1", started_at: today, ended_at: null, message_count: 3, is_active: true, loop_open: false },
    ] });
    api.resumeSession.mockImplementation(async (id: string) => ({ session: { id, topic: "x" }, messages: [{ id: `m-${id}`, role: "assistant", content: id === "s2" ? "welcome back" : `chat ${id}`, created_at: "" }] }));
    await resumedTeach("Sorting");
    fireEvent.click(await screen.findByTestId("tutor-recent-old"));
    await screen.findByTestId("loop-readonly-transcript");
    fireEvent.click(screen.getAllByTestId("loop-new-session")[0]);
    expect((await screen.findByTestId("tutor-home")).textContent).toContain("Starting wraps up “Sorting” first.");
  });
});

describe("Z63 — a failed map read says so, with a retry, never an empty map", () => {
  it("the panel's map and the course page show the failure; Try again reads the map again", async () => {
    api.getGraph.mockRejectedValueOnce(new ApiError("boom", 503))
      .mockResolvedValue({ nodes: [{ id: "n1", concept_name: "Recursion", mastery_tier: "learning", mastery_score: 0.4, is_subject_root: false, subject: "Intro CS", course_id: "c1" }], edges: [], stats: {} });
    await resumedTeach();
    await screen.findByTestId("tutor-map-error"); // the session panel's map
    expect(screen.queryByText("Concepts appear here as you learn.")).toBeNull();
    fireEvent.click(screen.getByTestId("tutor-course-c1"));
    const page = await screen.findByTestId("tutor-course-page");
    const failed = within(page).getByTestId("tutor-course-concepts-error");
    expect(page.textContent).not.toContain("0 concepts");
    expect(page.textContent).not.toContain("Concepts appear here as you learn.");
    fireEvent.click(within(failed).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(page).queryByTestId("tutor-course-concepts-error")).toBeNull());
    expect(api.getGraph).toHaveBeenCalledTimes(2);
    expect(page.textContent).toContain("1 concept");
  });
});

describe("K08 — the current concept follows the plan cursor the server moved", () => {
  const plan2 = (cursor: number) => ({ concepts: [
    { node_id: "n1", concept_name: "Recursion", kind: "new" },
    { node_id: "n2", concept_name: "Stacks", kind: "new" },
  ], cursor });

  it("after a graded check moves the cursor, the next check, the phase line and the panel name the next concept", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ approved_plan: plan2(0) }));
    const next = { ...pose, question_hash: "qh8", prompt: "What does the stack hold?" };
    api.nextLoopCheck.mockResolvedValueOnce({ phase: "check", check: pose }).mockResolvedValueOnce({ phase: "check", check: next });
    api.streamLoopCheckAnswer.mockResolvedValue(turn({
      reply: "Not quite.", phase: "feedback", graded: true, verdict: "not_yet",
      learner_state: [{ node_id: "n1", p_known: 0.4, band: "develop" }], approved_plan: plan2(1),
    }));
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect((await screen.findByTestId("loop-check-prompt")).textContent).toContain("Recursion");
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    const banner = await screen.findByTestId("loop-verdict");
    expect(banner.textContent).toContain("Recursion · check"); // the graded concept
    expect(banner.textContent).toContain("Next up: Stacks.");
    expect(banner.textContent).not.toContain("same idea");
    expect(screen.getByTestId("tutor-phase-line").textContent).toBe("Stacks · concept 2 of 2");
    const current = screen.getByTestId("loop-rail").querySelector('li[aria-current="step"]');
    expect(current?.textContent).toContain("Stacks");
    await waitFor(() => expect((screen.getByTestId("loop-check-me") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("loop-check-me"));
    await waitFor(() => expect(screen.getByTestId("loop-check-prompt").getAttribute("data-question-hash")).toBe("qh8"));
    expect(screen.getByTestId("loop-check-prompt").textContent).toContain("Stacks");
    expect(screen.getByTestId("loop-check-prompt").textContent).not.toContain("Recursion");
  });

  it("Check me that moved past a concept with no check names the concept it posed on", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ approved_plan: plan2(0) }));
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose, approved_plan: plan2(1) });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect((await screen.findByTestId("loop-check-prompt")).textContent).toContain("Stacks");
    expect(screen.getByTestId("tutor-phase-line").textContent).toBe("Stacks · concept 2 of 2");
  });

  it("a not-yet that stays on the concept still says to try another on the same idea", async () => {
    api.getLoopSessionStatus.mockResolvedValue(status({ approved_plan: plan2(0) }));
    api.nextLoopCheck.mockResolvedValue({ phase: "check", check: pose });
    api.streamLoopCheckAnswer.mockResolvedValue(turn({
      reply: "Not quite.", phase: "feedback", graded: true, verdict: "not_yet",
      learner_state: [{ node_id: "n1", p_known: 0.4, band: "develop" }],
    }));
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    await screen.findByTestId("loop-check-prompt");
    fireEvent.change(screen.getByTestId("loop-attempt-input"), { target: { value: "n == 0" } });
    fireEvent.click(screen.getByTestId("loop-attempt-submit"));
    expect((await screen.findByTestId("loop-verdict")).textContent).toContain("Try another one on the same idea.");
    expect(screen.getByTestId("tutor-phase-line").textContent).toBe("Recursion · concept 1 of 2");
  });
});

describe("K26 — a request the session's phase refuses re-reads where the session is", () => {
  const phaseMoved = (detail: string) => new ApiError(JSON.stringify({ detail }), 409, { body: { detail } });

  it("the plan of a session wrapped up in another tab shows its wrap-up, never 'phase is close'", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "plan")]));
    api.getLoopSessionStatus.mockResolvedValueOnce(status({ loop_phase: "plan", phase: "plan" }))
      .mockResolvedValue(status({ loop_phase: "close", phase: "teach" }));
    api.getLoopPlan.mockRejectedValue(phaseMoved("phase is close"));
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "plan" });
    render(<LoopLearn />);
    await waitFor(() => expect(screen.getByTestId("loop-phase").getAttribute("data-phase")).toBe("close"));
    expect(api.closeLoopSession).toHaveBeenCalledWith("s2", "u1");
    expect(toast.error).not.toHaveBeenCalled();
    expect(api.getLoopPlan).toHaveBeenCalledTimes(1);
  });

  it("a check-in another tab finished goes to its plan instead of a retry that always fails", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "probe")]));
    api.getLoopSessionStatus.mockResolvedValueOnce(status({ loop_phase: "probe", phase: "probe" }))
      .mockResolvedValue(status({ loop_phase: "plan", phase: "plan" }));
    api.nextLoopProbe.mockRejectedValue(phaseMoved("phase is plan"));
    api.getLoopPlan.mockResolvedValue({ concepts: [{ node_id: "n1", concept_name: "Recursion", kind: "new", p_known: 0.3 }], order: [] });
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-plan-concept-n1")).toBeTruthy();
    expect(screen.queryByTestId("loop-probe-retry")).toBeNull();
    expect(toast.error).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).toHaveBeenCalledTimes(1);
  });

  it("Check me on a session another device moved back to planning shows that plan", async () => {
    api.getLoopSessionStatus.mockResolvedValueOnce(status())
      .mockResolvedValue(status({ loop_phase: "plan", phase: "plan" }));
    api.nextLoopCheck.mockRejectedValue(phaseMoved("finish the plan first"));
    api.getLoopPlan.mockResolvedValue({ concepts: [{ node_id: "n3", concept_name: "Queues", kind: "new", p_known: 0.3 }], order: [] });
    await resumedTeach();
    fireEvent.click(await screen.findByTestId("loop-check-me"));
    expect(await screen.findByTestId("loop-plan-concept-n3")).toBeTruthy();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("a start that wraps up a session the server no longer has goes ahead", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([open("s2", "teach")]));
    api.closeLoopSession.mockRejectedValue(new ApiError(JSON.stringify({ detail: "Session not found" }), 404, { body: { detail: "Session not found" } }));
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER });
    api.nextLoopProbe.mockResolvedValue(probeItem);
    render(<LoopLearn />);
    await screen.findByText("welcome back");
    fireEvent.click(screen.getByTestId("loop-new-session"));
    fireEvent.click(await screen.findByTestId("loop-start-guided"));
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledTimes(1);
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("K29 — an open session past the open list's cap is in progress and resumes in its own course", () => {
  it("lists it as in progress and resumes it, never read-only", async () => {
    const today = new Date().toISOString();
    const old = new Date(Date.now() - 9 * 86_400_000).toISOString();
    api.getSessions.mockResolvedValue({ sessions: [
      { id: "s2", topic: "t s2", mode: "socratic", course_id: "c1", started_at: today, ended_at: null, message_count: 3, is_active: true, loop_open: true },
      { id: "old", topic: "Quiz ask", mode: "socratic", course_id: "c1", started_at: old, ended_at: null, message_count: 2, is_active: true, loop_open: true },
    ] });
    const resumeOld = { session_id: "old", topic: "Quiz ask", started_at: old, phase: "teach", course_id: "c1" };
    api.listLoopSessionsFor.mockImplementation(async (_u: string, _c: string, wanted: string | null) => ({
      sessions: [{ ...open("s2", "teach"), started_at: today }], resume: wanted === "old" ? resumeOld : null, complete: false,
    }));
    api.resumeSession.mockImplementation(async (id: string) => ({ session: { id }, messages: [{ id: `m-${id}`, role: "assistant", content: id === "old" ? "about the quiz" : "welcome back", created_at: "" }] }));
    render(<LoopLearn />);
    await screen.findByText("welcome back");
    const row = await screen.findByTestId("loop-session-old");
    expect(row.textContent).toContain("in progress");
    fireEvent.click(row);
    await screen.findByText("about the quiz");
    expect(api.listLoopSessionsFor).toHaveBeenLastCalledWith("u1", "c1", "old");
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("old");
    expect(screen.queryByTestId("loop-readonly-transcript")).toBeNull();
    expect(screen.getByTestId("loop-close-button")).toBeTruthy(); // it can be wrapped up from its own course
  });
});

describe("K05 — a link or button about one concept starts a session on that concept", () => {
  const node = { id: "n1", concept_name: "Recursion", mastery_tier: "struggling", mastery_score: 0.2, is_subject_root: false, subject: "Intro CS", course_id: "c1" };
  const onRecursion = { text: "", target_node_ids: ["n1"] };
  beforeEach(() => {
    api.getGraph.mockResolvedValue({ nodes: [node], edges: [], stats: {} });
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER, goal: onRecursion });
    api.nextLoopProbe.mockResolvedValue(probeItem);
  });

  it("'Start with X' on the Tutor home starts a session whose goal is X", async () => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-home-start-with"));
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Recursion", "", onRecursion, null);
    expect(screen.getByTestId("loop-goal-summary").textContent).toContain("Recursion");
  });

  it("a map or quiz link (?concept= with its course) starts a session on its concept", async () => {
    search.params = new URLSearchParams("topic=Recursion&concept=n1&course=c1&mode=socratic");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    render(<LoopLearn />);
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Recursion", "socratic", onRecursion, null);
  });

  it("Send to tutor's link (its note's linked concepts) starts a session on all of them", async () => {
    search.params = new URLSearchParams("topic=Week%203&course=c1&note=note1&concept=n1%2Cn2");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    render(<LoopLearn />);
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Week 3", "", { text: "", target_node_ids: ["n1", "n2"] }, "note1");
  });

  it("a link with no course to scope the concept to still starts on the whole course", async () => {
    search.params = new URLSearchParams("topic=Recursion&concept=n1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    render(<LoopLearn />);
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Recursion", "", undefined, null);
  });

  it("'Start a session on X' while another session is open starts on X", async () => {
    search.params = new URLSearchParams("topic=Recursion&concept=n1&course=c1");
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: "teach" });
    await resumedTeach("Sorting");
    fireEvent.click(await screen.findByTestId("loop-topic-start"));
    await waitFor(() => expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Recursion", "", onRecursion, null));
  });

  it("a concept the course no longer has opens the goal editor with the reason, not a retry that fails again", async () => {
    search.params = new URLSearchParams("topic=Recursion&concept=gone&course=c1");
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    const refused = "Choose target concepts from this course";
    api.startLoopSession.mockRejectedValue(new ApiError(JSON.stringify({ detail: refused }), 422, { body: { detail: refused } }));
    render(<LoopLearn />);
    expect(await screen.findByTestId("loop-goal-save")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(refused);
    expect(screen.queryByTestId("loop-start-error")).toBeNull();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
  });
});

describe("K30 — 'Set a goal' sets it before the session starts", () => {
  const node = { id: "n1", concept_name: "Recursion", mastery_tier: "struggling", mastery_score: 0.2, is_subject_root: false, subject: "Intro CS", course_id: "c1" };
  beforeEach(() => {
    api.listLoopSessionsFor.mockResolvedValue(listed([]));
    api.getGraph.mockResolvedValue({ nodes: [node], edges: [], stats: {} });
    api.startLoopSession.mockResolvedValue({ session_id: "s9", initial_message: OPENER, goal: { text: "", target_node_ids: ["n1"] } });
    api.nextLoopProbe.mockResolvedValue(probeItem);
  });

  it("opens the goal editor with nothing started or posed; saving starts the session on the goal", async () => {
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-home-goal"));
    await screen.findByTestId("loop-goal-save");
    expect(api.startLoopSession).not.toHaveBeenCalled();
    expect(api.nextLoopProbe).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("loop-goal-target-n1"));
    fireEvent.click(screen.getByTestId("loop-goal-save"));
    await screen.findByTestId("loop-probe-item");
    expect(api.startLoopSession).toHaveBeenCalledWith("u1", "c1", "Intro CS", "", { text: "", target_node_ids: ["n1"] }, null);
    expect(api.setLoopGoal).not.toHaveBeenCalled(); // no posed item is burnt by a later goal write
  });

  it("Cancel goes back to the home and starts nothing", async () => {
    render(<LoopLearn />);
    fireEvent.click(await screen.findByTestId("tutor-home-goal"));
    fireEvent.click(await screen.findByTestId("loop-goal-cancel"));
    expect(await screen.findByTestId("tutor-home")).toBeTruthy();
    expect(api.startLoopSession).not.toHaveBeenCalled();
  });
});

describe("K31 — Tutor V2 renames and deletes sessions, as the legacy Learn screen does", () => {
  const today = new Date().toISOString();
  const recent = (id: string, topic: string, loopOpen: boolean) => (
    { id, topic, mode: "socratic", course_id: "c1", started_at: today, ended_at: null, message_count: 2, is_active: true, loop_open: loopOpen }
  );

  async function allSessions() {
    api.getSessions.mockResolvedValue({ sessions: [recent("s2", "t s2", true), recent("old", "Big-O practice", false)] });
    await resumedTeach();
    fireEvent.click(screen.getByTestId("tutor-view-all"));
    return screen.findByTestId("tutor-all-sessions");
  }

  it("renames a session from every session's list", async () => {
    api.renameSession.mockResolvedValue({ updated: true, session: { id: "old", topic: "Big-O review" } });
    const page = await allSessions();
    fireEvent.click(within(page).getByTestId("tutor-session-rename-old"));
    const input = within(page).getByTestId("tutor-session-name-old");
    fireEvent.change(input, { target: { value: "Big-O review" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(api.renameSession).toHaveBeenCalledWith("old", "u1", "Big-O review"));
    expect(await within(page).findByText("Big-O review")).toBeTruthy();
    expect(within(page).queryByText("Big-O practice")).toBeNull();
  });

  it("Escape leaves the name as it was", async () => {
    const page = await allSessions();
    fireEvent.click(within(page).getByTestId("tutor-session-rename-old"));
    const input = within(page).getByTestId("tutor-session-name-old");
    fireEvent.change(input, { target: { value: "Nope" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(within(page).getByText("Big-O practice")).toBeTruthy();
    expect(api.renameSession).not.toHaveBeenCalled();
  });

  it("deletes a session after a confirm; deleting the open one leaves nothing of it on screen", async () => {
    api.deleteSession.mockResolvedValue({ deleted: true });
    const page = await allSessions();
    fireEvent.click(within(page).getByTestId("tutor-session-delete-s2"));
    expect(api.deleteSession).not.toHaveBeenCalled(); // the first click only arms it
    fireEvent.click(within(page).getByTestId("tutor-session-delete-s2"));
    await waitFor(() => expect(api.deleteSession).toHaveBeenCalledWith("s2", "u1"));
    await waitFor(() => expect(within(page).queryByTestId("tutor-session-row-s2")).toBeNull());
    expect(screen.getByTestId("loop-phase").getAttribute("data-session-id")).toBe("");
    expect(toast.success).toHaveBeenCalledWith("Session deleted.");
  });
});

describe("K11 — a refusal mid-stream is read as the refusal it is", () => {
  it("the daily AI limit is the pause banner with its reset time, not 'try again', and no Retry", async () => {
    const reset = "2026-11-21T00:00:00+00:00";
    api.streamLoopChat.mockRejectedValueOnce(Object.assign(
      new ChatStreamError("You've reached today's limit for AI features.", "r1", false),
      { code: "LLM_BUDGET_EXCEEDED", resetAt: reset },
    ));
    await resumedTeach();
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    const banner = await screen.findByTestId("loop-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe(reset);
    expect(banner.textContent).toContain("today's limit for AI features");
    expect(banner.textContent).not.toContain("Practice and review keep working");
    expect(toast.error).not.toHaveBeenCalled();
    expect(screen.queryByTestId("tutor-retry")).toBeNull();
    await waitFor(() => expect((screen.getByTestId("tutor-input") as HTMLTextAreaElement).value).toBe("why?"));
  });

  it("a session closed in another tab mid-stream shows the close, not 'couldn't answer'", async () => {
    api.closeLoopSession.mockResolvedValue({ close: closeRecord, model_written: false, close_phase: null });
    api.streamLoopChat.mockRejectedValueOnce(Object.assign(
      new ChatStreamError("this session is closed", "r1", false),
      { status: 409, body: { detail: "this session is closed" } },
    ));
    await resumedTeach();
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "why?" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    await screen.findByTestId("loop-close-done");
    expect(api.closeLoopSession).toHaveBeenCalledWith("s2", "u1");
    expect(toast.error).not.toHaveBeenCalled();
  });
});
