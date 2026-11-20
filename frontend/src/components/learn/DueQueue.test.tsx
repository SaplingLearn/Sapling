// @vitest-environment jsdom
/**
 * DueQueue — the learning loop's "Due today" review queue (PKG-12).
 *   1. Empty queue → "All caught up", budget chip in minutes
 *   2. A free check: typed answer → answerReview({answer}) → corrective hint + Next
 *   3. An mc_reason check: the stored options as radios (no correctness marked),
 *      submitted as selected_option + reason
 *   4. A flashcard: flip, then a 1/2/3 self-rating
 *   5. A refused answer (A33) asks for the student's own words and stays answerable
 *   6. A 409 (already graded / new day) re-polls the queue
 *   7. A 404 (the item is gone: withdrawn, held or deleted) skips it with a note
 *   8. A queue that failed to load says why and offers Retry
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockNext, mockAnswer, mockSummary, mockReport, flags } = vi.hoisted(() => ({
  mockNext: vi.fn(),
  mockAnswer: vi.fn(),
  mockSummary: vi.fn(),
  mockReport: vi.fn(),
  flags: {} as Record<string, string>,
}));

// The real module for everything else (budgetPauseOf, ApiError); the review
// clients (and spec §13 A113's report client) are mocked.
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getReviewNext: mockNext,
  answerReview: mockAnswer,
  getReviewSummary: mockSummary,
  reportCheckItem: mockReport,
}));
// Every flag "off" unless a test turns it on (the provider's own default).
vi.mock("@/context/FlagsContext", () => ({ useFlag: (key: string) => flags[key] ?? "off" }));

import { ApiError } from "@/lib/api";
import { __resetFeedbackPacingForTests, feedbackHeld } from "@/lib/feedbackPacing";
import { DueQueue } from "./DueQueue";
import crisisFixture from "@/test-utils/crisisSupport.json";

const SR = { stage: "acquire", correct: 0, target: 3 } as const;
const next = (item: unknown, remaining = 600, due = item ? 1 : 0) => ({
  item,
  remaining_budget_s: remaining,
  session_id: "sess-1",
  retention_target: 0.9,
  due_total: due,
  in_budget: item ? 1 : 0,
});
const conflict = (detail: string) =>
  Object.assign(new Error(JSON.stringify({ detail })), { status: 409, body: { detail } });
const notFound = (detail: string) =>
  Object.assign(new Error(JSON.stringify({ detail })), { status: 404, body: { detail } });
const FREE = {
  kind: "check", id: "ci-1", node_id: "n1", concept_name: "Recursion", format: "free",
  difficulty: 3, cost_s: 45, sr: SR, prompt: "What stops factorial(0)?",
};
const MC = {
  ...FREE, id: "ci-2", format: "mc_reason", prompt: "Which one?",
  options: [{ letter: "A", text: "base case" }, { letter: "B", text: "a loop" }],
};
const CARD = { kind: "flashcard", id: "f1", topic: "T", cost_s: 15, sr: SR, front: "Q?", back: "A!" };
const graded = (over: object = {}) => ({
  correct: true, hint: "Nice.", next_due_at: "2026-10-01T00:00:00Z", rating: 3,
  remaining_budget_s: 555, sr: SR, unavailable: false, refused: false, ...over,
});

const summary = (over: object = {}) => ({
  due: { flashcard: 0, check: 0 }, in_budget: 0, unservable: 0, paused: 0, budget_min: 12,
  remaining_budget_s: 720, retention_target: 0.9, ...over,
});

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  mockSummary.mockResolvedValue(summary());
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  for (const key of Object.keys(flags)) delete flags[key];
});

describe("DueQueue — no feedback survey over a review item (lib/feedbackPacing.ts)", () => {
  it("holds the shell's feedback prompts while an item is on screen, answered or not, and releases them when the queue is done", async () => {
    __resetFeedbackPacingForTests();
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(null));
    mockAnswer.mockResolvedValue(graded());
    // A findBy can resolve on the commit, before its passive effects run.
    const effectsFlushed = () => act(async () => {});
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await effectsFlushed();
    expect(feedbackHeld()).toBe(true);
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await screen.findByTestId("review-hint");
    await effectsFlushed();
    expect(feedbackHeld()).toBe(true);
    await userEvent.click(screen.getByTestId("review-next"));
    await screen.findByTestId("review-empty");
    await effectsFlushed();
    expect(feedbackHeld()).toBe(false);
  });
});

describe("DueQueue — Report this question (spec §13 A113)", () => {
  it("offers no report control while the item_reports flag is off", async () => {
    mockNext.mockResolvedValue(next(FREE));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    expect(screen.queryByTestId("review-report")).toBeNull();
  });

  it("reports the served check with a reason, then moves to the next item", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockReport.mockResolvedValue({ reported: true, first: true, quarantined: false });
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    // a short list of reasons — never a text box
    expect(screen.getByTestId("review-report-reasons").querySelector("textarea, input")).toBeNull();
    await userEvent.click(screen.getByTestId("review-report-reason-wrong_answer"));
    expect(mockReport).toHaveBeenCalledWith({
      surface: "review", user_id: "u1", session_id: "sess-1", item_id: "ci-1", course_id: "c1",
      reason: "wrong_answer",
    });
    expect(await screen.findByTestId("review-reported")).toBeTruthy();
    expect(screen.getByTestId("review-item").textContent).toContain("Which one?");
    expect(mockNext).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("review-report-reasons")).toBeNull(); // the next item starts closed
  });

  it("can report an item after answering it (the corrective hint shows the key)", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(null));
    mockAnswer.mockResolvedValue(graded({ correct: false, hint: "Answer: a loop" }));
    mockReport.mockResolvedValue({ reported: true, first: true, quarantined: false });
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await screen.findByTestId("review-hint");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-wrong_answer"));
    expect(await screen.findByTestId("review-reported")).toBeTruthy();
    expect(screen.getByTestId("review-empty")).toBeTruthy();
  });

  it("keeps the reasons open when the report fails, and cancel closes them", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValue(next(FREE));
    mockReport.mockRejectedValue(new Error("down"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-unclear"));
    expect(await screen.findByText("Couldn't report that question.")).toBeTruthy();
    expect(screen.getByTestId("review-report-reasons")).toBeTruthy();
    expect(screen.queryByTestId("review-reported")).toBeNull();
    await userEvent.click(screen.getByTestId("review-report-cancel"));
    expect(screen.queryByTestId("review-report-reasons")).toBeNull();
    expect(mockNext).toHaveBeenCalledTimes(1);
  });

  it("re-polls when the report finds the queue moved on (409)", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(null));
    mockReport.mockRejectedValue(conflict("review session expired"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-not_from_my_course"));
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
    expect(screen.queryByTestId("review-reported")).toBeNull();
  });

  it("offers no report on a flashcard", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValue(next(CARD));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    expect(screen.queryByTestId("review-report")).toBeNull();
  });
});

describe("DueQueue", () => {
  it("shows all caught up and the budget in minutes when nothing is due", async () => {
    mockNext.mockResolvedValue(next(null, 720));
    render(<DueQueue userId="u1" courseId="c1" />);
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
    expect(screen.getByTestId("review-budget").textContent).toContain("12 min left");
    expect(mockNext).toHaveBeenCalledWith("u1", "c1");
  });

  it("submits a free answer and shows the corrective hint, then moves on", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(null));
    mockAnswer.mockResolvedValue(graded({ correct: false, hint: "Close.\n\nAnswer: the base case" }));
    render(<DueQueue userId="u1" courseId="c1" />);
    expect((await screen.findByTestId("review-item")).textContent).toContain("What stops factorial(0)?");
    await userEvent.type(screen.getByTestId("review-answer-input"), "a loop");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(mockAnswer).toHaveBeenCalledWith({
      user_id: "u1", session_id: "sess-1", course_id: "c1", kind: "check", item_id: "ci-1",
      answer: "a loop",
    });
    const hint = await screen.findByTestId("review-hint");
    expect(hint.textContent).toContain("Not yet.");
    expect(hint.textContent).toContain("Answer: the base case");
    expect(screen.getByTestId("review-budget").textContent).toContain("9 min left");
    await userEvent.click(screen.getByTestId("review-next"));
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
  });

  it("serves the stored mc_reason options and sends the choice with a reason", async () => {
    mockNext.mockResolvedValue(next(MC));
    mockAnswer.mockResolvedValue(graded());
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    expect(screen.getByText("A. base case")).toBeTruthy();
    expect(screen.getByText("B. a loop")).toBeTruthy();
    expect((screen.getByTestId("review-submit") as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByTestId("review-option-A"));
    await userEvent.type(screen.getByTestId("review-reason-input"), "it stops the recursion");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(mockAnswer).toHaveBeenCalledWith({
      user_id: "u1", session_id: "sess-1", course_id: undefined, kind: "check", item_id: "ci-2",
      selected_option: "A", reason: "it stops the recursion",
    });
    expect((await screen.findByTestId("review-hint")).textContent).toContain("Correct.");
  });

  it("flips a flashcard and sends the self-rating", async () => {
    mockNext.mockResolvedValue(next(CARD));
    mockAnswer.mockResolvedValue(graded({ hint: null }));
    render(<DueQueue userId="u1" />);
    await screen.findByText("Q?");
    expect(screen.queryByText("A!")).toBeNull();
    expect(screen.queryByTestId("review-rate-2")).toBeNull();
    await userEvent.click(screen.getByTestId("review-flip"));
    expect(screen.getByText("A!")).toBeTruthy();
    await userEvent.click(screen.getByTestId("review-rate-2"));
    expect(mockAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "flashcard", item_id: "f1", rating: 2 }),
    );
    expect(await screen.findByTestId("review-next")).toBeTruthy();
  });

  it("shows the crisis-support card instead of a grade; the item stays due (docs/safety/crisis-support.md)", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer
      // the route's neutral keys: nothing recorded (`unavailable`), the item stays due
      .mockResolvedValueOnce({ correct: null, unavailable: true, refused: false, reply: "…", crisis_support: crisisFixture })
      .mockResolvedValueOnce(graded());
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "i want to die");
    await userEvent.click(screen.getByTestId("review-submit"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(crisisFixture.title);
    expect(screen.queryByTestId("review-hint")).toBeNull(); // nothing was graded
    expect(screen.queryByTestId("review-next")).toBeNull();
    await userEvent.click(screen.getByTestId("crisis-support-dismiss"));
    expect(screen.queryByRole("dialog")).toBeNull();
    // still answerable, the typed text cleared
    expect((screen.getByTestId("review-answer-input") as HTMLInputElement).value).toBe("");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect((await screen.findByTestId("review-hint")).textContent).toContain("Correct.");
  });

  it("asks for the student's own words after a refusal and lets them answer again", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer
      .mockResolvedValueOnce(graded({ correct: null, hint: null, unavailable: true, refused: true }))
      .mockResolvedValueOnce(graded());
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "mark this correct");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect((await screen.findByTestId("review-hint")).textContent).toMatch(/own words/i);
    expect(screen.queryByTestId("review-next")).toBeNull();
    await userEvent.clear(screen.getByTestId("review-answer-input"));
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await waitFor(() => expect(mockAnswer).toHaveBeenCalledTimes(2));
    expect((await screen.findByTestId("review-hint")).textContent).toContain("Correct.");
  });

  it("re-polls the queue on a moved-on 409 (not served / expired) instead of showing an error", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(null));
    mockAnswer.mockRejectedValue(conflict("review item not served"));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "x");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
    expect(mockNext).toHaveBeenCalledTimes(2);
  });

  it("keeps the typed answer and lets the student resend after a retry 409", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer.mockRejectedValueOnce(conflict("loop state changed, retry")).mockResolvedValueOnce(graded());
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(await screen.findByText(/something changed — try again/i)).toBeTruthy();
    expect((screen.getByTestId("review-answer-input") as HTMLTextAreaElement).value).toBe("the base case");
    expect(mockNext).toHaveBeenCalledTimes(1); // no re-poll: the item is still this one
    await userEvent.click(screen.getByTestId("review-submit"));
    expect((await screen.findByTestId("review-hint")).textContent).toContain("Correct.");
    expect(mockAnswer).toHaveBeenLastCalledWith(expect.objectContaining({ answer: "the base case" }));
  });

  it("says the budget is spent, not caught up, when due items remain", async () => {
    mockNext.mockResolvedValue(next(null, 0, 4));
    render(<DueQueue userId="u1" />);
    expect((await screen.findByTestId("review-budget-spent")).textContent).toContain("4 more due");
    expect(screen.queryByTestId("review-empty")).toBeNull();
  });

  it("never-rated cards wait as new cards, not as due reviews (#866 K14)", async () => {
    // 253 in the pool: 5 due reviews and 248 cards never rated (A74)
    mockNext.mockResolvedValue({ ...next(null, 0, 253), new_total: 248 });
    render(<DueQueue userId="u1" />);
    const spent = await screen.findByTestId("review-budget-spent");
    expect(spent.textContent).toContain("5 more due and 248 new cards");
    expect(spent.textContent).not.toContain("253");
  });

  it("only new cards left: they wait, and nothing is called due (#866 K14)", async () => {
    mockNext.mockResolvedValue({ ...next(null, 0, 1), new_total: 1 });
    render(<DueQueue userId="u1" />);
    const spent = await screen.findByTestId("review-budget-spent");
    expect(spent.textContent).toContain("1 new card will wait for tomorrow");
    expect(spent.textContent).not.toMatch(/due/);
  });

  it("a never-rated card is marked as a new card (#866 K14)", async () => {
    mockNext.mockResolvedValue(next({ ...CARD, new: true }));
    render(<DueQueue userId="u1" />);
    expect((await screen.findByTestId("review-new-card")).textContent).toBe("New card");
  });

  it("a card due for review carries no new-card mark", async () => {
    mockNext.mockResolvedValue(next(CARD));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-flip");
    expect(screen.queryByTestId("review-new-card")).toBeNull();
  });

  it("never attaches a late answer to a newer item", async () => {
    let resolveAnswer: (v: unknown) => void = () => {};
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD));
    mockAnswer.mockReturnValueOnce(new Promise((res) => { resolveAnswer = res; }));
    const { rerender } = render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "x");
    await userEvent.click(screen.getByTestId("review-submit"));
    rerender(<DueQueue userId="u1" courseId="c2" />); // a course switch reloads the queue
    await screen.findByText("Q?");
    resolveAnswer(graded({ hint: "LATE" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/LATE/)).toBeNull();
    expect(screen.queryByTestId("review-hint")).toBeNull();
  });

  it("drops a stale queue response that lands after a newer one", async () => {
    let resolveOld: (v: unknown) => void = () => {};
    mockNext
      .mockReturnValueOnce(new Promise((res) => { resolveOld = res; }))
      .mockResolvedValueOnce(next(CARD));
    const { rerender } = render(<DueQueue userId="u1" courseId="c1" />);
    rerender(<DueQueue userId="u1" courseId="c2" />);
    await screen.findByText("Q?");
    resolveOld(next(FREE));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText("Q?")).toBeTruthy();
    expect(screen.queryByText("What stops factorial(0)?")).toBeNull();
  });

  it("shows the answer as recorded when a resend after a retry 409 is already graded", async () => {
    // the retry 409 can follow the evidence write (the record lost its CAS): the
    // resend then meets "already graded" — the answer counted, so it is no error
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer
      .mockRejectedValueOnce(conflict("loop state changed, retry"))
      .mockRejectedValueOnce(conflict("already graded"));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await screen.findByText(/something changed — try again/i);
    await userEvent.click(screen.getByTestId("review-submit"));
    expect((await screen.findByTestId("review-graded")).textContent).toMatch(/already recorded/i);
    expect(screen.queryByText(/something changed/i)).toBeNull();
    expect(screen.queryByTestId("review-submit")).toBeNull();
    expect(screen.getByTestId("review-next")).toBeTruthy();
    expect(mockNext).toHaveBeenCalledTimes(1);
  });
});

describe("DueQueue launch polish (PKG-13; spec §11.3, §3.5)", () => {
  it("shows 'All caught up' when nothing is due", async () => {
    mockNext.mockResolvedValue(next(null, 600, 0));
    render(<DueQueue userId="u1" courseId="c1" />);
    expect((await screen.findByTestId("review-empty")).textContent).toContain("All caught up");
    expect(screen.queryByTestId("review-item")).toBeNull();
    expect(screen.queryByTestId("review-budget-paused")).toBeNull();
  });

  it("a 429 'ai budget reached' shows the pause banner and review keeps working", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD));
    mockAnswer.mockRejectedValue(
      new ApiError("ai budget reached", 429, { body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z" } }),
    );
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "x");
    await userEvent.click(screen.getByTestId("review-submit"));
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.textContent).toContain("Flashcards and review keep working");
    expect(screen.queryByText(/Couldn't send that answer/)).toBeNull(); // not an error
    await userEvent.click(screen.getByTestId("review-next"));
    await waitFor(() => expect(mockNext).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Q?")).toBeTruthy();
  });

  it("paused novice concepts show the banner with the count", async () => {
    mockNext.mockResolvedValue(next(CARD));
    mockSummary.mockResolvedValue(summary({ paused: 2 }));
    render(<DueQueue userId="u1" courseId="c1" />);
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.textContent).toContain("2 concepts paused until your daily AI budget resets");
    expect(banner.textContent).toContain("Flashcards and other reviews keep working");
    expect(mockSummary).toHaveBeenCalledWith("u1", "c1");
  });

  it("one paused concept reads in the singular", async () => {
    mockNext.mockResolvedValue(next(null));
    mockSummary.mockResolvedValue(summary({ paused: 1 }));
    render(<DueQueue userId="u1" />);
    expect((await screen.findByTestId("review-budget-paused")).textContent).toContain("1 concept paused");
  });

  it("concepts held by the monthly cap say so, with the reset's date — never 'daily' (#866 K18)", async () => {
    const until = "2026-12-01T00:00:00+00:00";
    mockNext.mockResolvedValue(next(CARD));
    mockSummary.mockResolvedValue(summary({ paused: 2, paused_scope: "monthly_usd", paused_until: until }));
    render(<DueQueue userId="u1" courseId="c1" />);
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.textContent).toContain("2 concepts paused until");
    expect(banner.textContent).toContain(new Date(until).toLocaleString(undefined, { month: "short", day: "numeric" }));
    expect(banner.textContent).toContain("when your monthly AI budget resets");
    expect(banner.textContent).not.toMatch(/daily/i);
    expect(banner.getAttribute("data-reset-at")).toBe(until);
  });

  it("an answer's rate-limit 429 says to send it again shortly — not that the tutor is paused (#866 K18)", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer.mockRejectedValue(new ApiError("ai budget reached", 429, {
      body: { detail: "ai budget reached", reset_at: "2026-09-27T00:01:00Z", scope: "rate_limit", session_capped: false },
    }));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.textContent).toContain("Too many AI requests in the last minute");
    expect(banner.textContent).not.toContain("AI tutor paused");
    expect((screen.getByTestId("review-answer-input") as HTMLTextAreaElement).value).toBe("the base case");
  });

  it("a failed summary is ignored (it only feeds the banner)", async () => {
    mockNext.mockResolvedValue(next(null));
    mockSummary.mockRejectedValue(new Error("boom"));
    render(<DueQueue userId="u1" />);
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
    expect(screen.queryByTestId("review-budget-paused")).toBeNull();
  });

  it("a flashcard is served, flipped and rated", async () => {
    mockNext.mockResolvedValue(next(CARD));
    mockAnswer.mockResolvedValue(graded({ hint: null }));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-3"));
    expect(mockAnswer).toHaveBeenCalledTimes(1);
    expect(mockAnswer).toHaveBeenCalledWith(expect.objectContaining({ kind: "flashcard", rating: 3 }));
  });

  it("the summary is re-read with every load, so the pause count is never stale", async () => {
    mockNext.mockResolvedValueOnce(next(CARD)).mockResolvedValueOnce(next(null, 600, 0));
    mockAnswer.mockResolvedValue(graded({ hint: null }));
    mockSummary.mockResolvedValueOnce(summary({ paused: 2 })).mockResolvedValue(summary({ paused: 0 }));
    render(<DueQueue userId="u1" courseId="c1" />);
    expect((await screen.findByTestId("review-budget-paused")).textContent).toContain("2 concepts");
    await userEvent.click(screen.getByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-3"));
    await userEvent.click(await screen.findByTestId("review-next"));
    await screen.findByTestId("review-empty");
    await waitFor(() => expect(mockSummary).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("review-budget-paused")).toBeNull());
  });

  it("'All caught up' makes no 'more due later' claim from a mount-time count", async () => {
    // summary.due counts what is due TODAY (as of that read) — never "later";
    // with nothing served and due_total 0 there is nothing more due today.
    mockNext.mockResolvedValue(next(null, 600, 0));
    mockSummary.mockResolvedValue(summary({ due: { flashcard: 3, check: 2 } }));
    render(<DueQueue userId="u1" />);
    const empty = await screen.findByTestId("review-empty");
    await waitFor(() => expect(mockSummary).toHaveBeenCalled());
    expect(empty.textContent).not.toMatch(/due later/i);
    expect(empty.textContent).toContain("All caught up — nothing is due right now.");
  });

  it("a failed reload never leaves the previous item on screen", async () => {
    mockNext.mockResolvedValueOnce(next(CARD)).mockRejectedValueOnce(new Error("down"));
    mockAnswer.mockResolvedValue(graded({ hint: null }));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-3"));
    await userEvent.click(await screen.findByTestId("review-next"));
    expect(await screen.findByText(/Couldn't load your review queue/)).toBeTruthy();
    expect(screen.queryByTestId("review-item")).toBeNull();
  });
});

describe("DueQueue — stated confidence (spec §13 A127)", () => {
  const sent = () => mockAnswer.mock.calls.at(-1)?.[0] as Record<string, unknown>;

  it("a check offers the optional control; a skip sends no confidence and never blocks Check", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer.mockResolvedValue(graded());
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    const group = screen.getByTestId("review-confidence");
    expect(group.getAttribute("role")).toBe("radiogroup");
    expect(group.querySelectorAll('[aria-checked="true"]').length).toBe(0);
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    expect((screen.getByTestId("review-submit") as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByTestId("review-submit"));
    expect("confidence" in sent()).toBe(false); // absent, never a default
    // answered: the control goes with the Check button
    await screen.findByTestId("review-hint");
    expect(screen.queryByTestId("review-confidence")).toBeNull();
  });

  it("a chosen confidence rides a free answer and an mc_reason answer", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockAnswer.mockResolvedValue(graded());
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-confidence-sure"));
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(sent()).toEqual({
      user_id: "u1", session_id: "sess-1", course_id: "c1", kind: "check", item_id: "ci-1",
      answer: "the base case", confidence: "sure",
    });
    await userEvent.click(await screen.findByTestId("review-next"));
    await screen.findByText("A. base case");
    // the next item starts with none chosen
    expect(screen.getByTestId("review-confidence-sure").getAttribute("aria-checked")).toBe("false");
    await userEvent.click(screen.getByTestId("review-option-B"));
    await userEvent.click(screen.getByTestId("review-confidence-guessing"));
    // K02: the grader judges the reason, so an option alone is not an answer
    expect(screen.getByTestId("review-submit")).toBeDisabled();
    await userEvent.type(screen.getByTestId("review-reason-input"), "it is the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect(sent()).toMatchObject({ selected_option: "B", reason: "it is the base case", confidence: "guessing" });
  });

  it("a flashcard has no confidence control (its self-rating says how it went)", async () => {
    mockNext.mockResolvedValue(next(CARD));
    mockAnswer.mockResolvedValue(graded({ hint: null }));
    render(<DueQueue userId="u1" />);
    await screen.findByText("Q?");
    await userEvent.click(screen.getByTestId("review-flip"));
    expect(screen.queryByTestId("review-confidence")).toBeNull();
    await userEvent.click(screen.getByTestId("review-rate-3"));
    expect("confidence" in sent()).toBe(false);
  });
});

describe("DueQueue — a check that cannot be graded never pins the queue (#866 K16)", () => {
  const unavailable = () => graded({ correct: null, hint: null, unavailable: true, refused: false });

  it("an ungraded answer says the question comes back later, and Next moves on", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD));
    mockAnswer.mockResolvedValueOnce(unavailable());
    render(<DueQueue userId="u1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    const hint = await screen.findByTestId("review-hint");
    expect(hint.textContent).toContain("Nothing was recorded");
    expect(hint.textContent).toContain("comes back after the rest of today's review");
    expect(hint.textContent).not.toMatch(/try again later/i);
    expect(screen.getByTestId("review-submit").textContent).toBe("Try again");
    await userEvent.click(screen.getByTestId("review-next"));
    expect(await screen.findByTestId("review-flip")).toBeTruthy();
  });

  it("the question comes back with what the student had typed", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD)).mockResolvedValueOnce(next(FREE));
    mockAnswer.mockResolvedValueOnce(unavailable()).mockResolvedValueOnce(graded({ hint: null }));
    render(<DueQueue userId="u1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await userEvent.click(await screen.findByTestId("review-next"));
    await userEvent.click(await screen.findByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-3"));
    await userEvent.click(await screen.findByTestId("review-next"));
    const box = (await screen.findByTestId("review-answer-input")) as HTMLTextAreaElement;
    expect(box.value).toBe("the base case");
  });

  it("at the grader cap the answer's 429 says checks wait, and Next goes on to the flashcards", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD));
    mockAnswer.mockRejectedValue(new ApiError("ai budget reached", 429, {
      body: { detail: "ai budget reached", reset_at: "2026-09-27T00:00:00Z", scope: "daily_grades", session_capped: false },
    }));
    render(<DueQueue userId="u1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.textContent).toContain("Today's grading limit is reached");
    expect(banner.textContent).toContain("Flashcards keep working");
    expect(banner.textContent).not.toContain("AI tutor paused");
    await userEvent.click(screen.getByTestId("review-next"));
    expect(await screen.findByTestId("review-flip")).toBeTruthy();
  });

  it("checks held at the grader cap are named, with when grading reopens", async () => {
    mockNext.mockResolvedValue(next(null, 600, 0));
    mockSummary.mockResolvedValue(summary({ grading_paused: 2, grading_paused_until: "2026-09-27T00:00:00Z" }));
    render(<DueQueue userId="u1" />);
    const banner = await screen.findByTestId("review-budget-paused");
    expect(banner.textContent).toContain("Checks on 2 concepts wait until");
    expect(banner.textContent).toContain("when today's grading limit resets");
    expect(banner.getAttribute("data-reset-at")).toBe("2026-09-27T00:00:00Z");
    // nothing else is due, but the checks are not "all caught up"
    await waitFor(() => expect(screen.getByTestId("review-empty").textContent).toContain("Nothing else is due right now"));
  });

  it("Next after a rate-limit pause brings the same check back with the answer kept", async () => {
    mockNext.mockResolvedValue(next(FREE));
    mockAnswer.mockRejectedValue(new ApiError("ai budget reached", 429, {
      body: { detail: "ai budget reached", reset_at: "2026-09-27T00:01:00Z", scope: "rate_limit", session_capped: false },
    }));
    render(<DueQueue userId="u1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await userEvent.click(await screen.findByTestId("review-next"));
    await waitFor(() => expect(mockNext).toHaveBeenCalledTimes(2));
    expect((screen.getByTestId("review-answer-input") as HTMLTextAreaElement).value).toBe("the base case");
  });
});

describe("DueQueue — the student's review day ends mid-answer (#866 K17)", () => {
  const nextDay = (item: unknown) => ({ ...next(item), session_id: "sess-2" });

  it("an answer sent after the day ended reloads today's queue, keeping what was typed", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(nextDay(FREE));
    mockAnswer.mockRejectedValueOnce(conflict("review session expired")).mockResolvedValueOnce(graded());
    render(<DueQueue userId="u1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    expect((await screen.findByTestId("review-new-day")).textContent).toContain("A new review day began");
    expect((screen.getByTestId("review-answer-input") as HTMLTextAreaElement).value).toBe("the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await waitFor(() => expect(mockAnswer).toHaveBeenLastCalledWith(expect.objectContaining({ session_id: "sess-2" })));
  });

  it("a report sent after the day ended goes to today's session when the question is served again", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(nextDay(FREE)).mockResolvedValueOnce(nextDay(MC));
    mockReport.mockRejectedValueOnce(conflict("review session expired"))
      .mockResolvedValueOnce({ reported: true, first: true, quarantined: false });
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-unclear"));
    expect(await screen.findByTestId("review-reported")).toBeTruthy();
    expect(mockReport.mock.calls.map(([body]) => body.session_id)).toEqual(["sess-1", "sess-2"]);
    expect(await screen.findByTestId("review-option-A")).toBeTruthy();
  });

  it("a report the new day cannot take says it was not sent — never silently dropped", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(nextDay(CARD));
    mockReport.mockRejectedValueOnce(conflict("review session expired"));
    render(<DueQueue userId="u1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-unclear"));
    expect((await screen.findByTestId("review-not-reported")).textContent).toContain("wasn't sent");
    expect(mockReport).toHaveBeenCalledTimes(1);
  });
});

describe("DueQueue — the answer boxes are visible fields (#866 Z29)", () => {
  // Tailwind's preflight strips every textarea's border, padding and fill: a box
  // with no style of its own is invisible, so each one carries the loop's field
  // style (FIELD_STYLE, as the loop's check card does) and a visible label.
  const looksLikeAField = (box: HTMLElement) => {
    expect(box.style.border).toBe("1px solid var(--border)");
    expect(box.style.background).toBe("var(--bg-input)");
    expect(box.style.padding).toBe("10px 12px");
  };

  it("a free check's answer box is styled and has a visible label", async () => {
    mockNext.mockResolvedValue(next(FREE));
    render(<DueQueue userId="u1" courseId="c1" />);
    const box = await screen.findByLabelText("Your answer");
    expect(box).toBe(screen.getByTestId("review-answer-input"));
    expect(screen.getByText("Your answer").tagName).toBe("LABEL");
    looksLikeAField(box);
  });

  it("an mc_reason check's reason box is styled and has a visible label", async () => {
    mockNext.mockResolvedValue(next(MC));
    render(<DueQueue userId="u1" courseId="c1" />);
    const box = await screen.findByLabelText("Your reasoning");
    expect(box).toBe(screen.getByTestId("review-reason-input"));
    expect(screen.getByText("Your reasoning").tagName).toBe("LABEL");
    looksLikeAField(box);
  });
});

describe("DueQueue — keyboard and screen reader (spec §13 A135)", () => {
  it("the first load moves no focus: Study owns it when the page opens", async () => {
    mockNext.mockResolvedValue(next(FREE));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await act(async () => {});
    expect(document.body).toHaveFocus();
  });

  it("names the answer box and the options by the question", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockAnswer.mockResolvedValue(graded());
    render(<DueQueue userId="u1" courseId="c1" />);
    expect(await screen.findByRole("textbox", { name: "Your answer" })).toHaveAccessibleDescription("What stops factorial(0)?");
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    await userEvent.click(await screen.findByTestId("review-next"));
    const group = await screen.findByRole("radiogroup", { name: "Which one?" });
    expect(group).toContainElement(screen.getByTestId("review-option-A"));
  });

  it("Check moves focus to the result, Next to the next item's answer", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockAnswer.mockResolvedValue(graded({ correct: false, hint: "Look at n == 0." }));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "a loop");
    await userEvent.click(screen.getByTestId("review-submit"));
    await waitFor(() => expect(screen.getByTestId("review-hint")).toHaveFocus());
    expect(screen.getByTestId("review-hint").textContent).toContain("Look at n == 0.");
    await userEvent.click(screen.getByTestId("review-next"));
    await waitFor(() => expect(screen.getByTestId("review-option-A")).toHaveFocus());
  });

  it("a flashcard: Show answer moves focus to the back, a rating to the result, Next to the empty line", async () => {
    mockNext.mockResolvedValueOnce(next(CARD)).mockResolvedValueOnce(next(null));
    mockAnswer.mockResolvedValue(graded({ hint: "" }));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.click(await screen.findByTestId("review-flip"));
    await waitFor(() => expect(screen.getByText("A!")).toHaveFocus());
    await userEvent.click(screen.getByTestId("review-rate-3"));
    await waitFor(() => expect(screen.getByTestId("review-hint")).toHaveFocus());
    await userEvent.click(screen.getByTestId("review-next"));
    await waitFor(() => expect(screen.getByTestId("review-empty")).toHaveFocus());
  });

  it("a report's confirmation is announced from a live region already on the page", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockReport.mockResolvedValue({ reported: true, first: true, quarantined: false });
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    const region = screen.getByTestId("review-due-panel").querySelector('[aria-live="polite"]');
    expect(region).toBeEmptyDOMElement();
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-unclear"));
    expect(region).toContainElement(await screen.findByTestId("review-reported"));
    await waitFor(() => expect(screen.getByTestId("review-option-A")).toHaveFocus());
  });
});

describe("DueQueue — an item that is gone (404) is skipped, never a dead end", () => {
  it("an answer 404 ('review item not found') moves to the next item with a note, announced and focused", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockAnswer.mockRejectedValue(notFound("review item not found"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    const region = screen.getByTestId("review-due-panel").querySelector('[aria-live="polite"]');
    expect(region).toBeEmptyDOMElement();
    await userEvent.type(screen.getByTestId("review-answer-input"), "the base case");
    await userEvent.click(screen.getByTestId("review-submit"));
    const note = await screen.findByTestId("review-skipped");
    expect(note.textContent).toContain("no longer available");
    expect(region).toContainElement(note);
    expect(await screen.findByText("Which one?")).toBeTruthy();
    expect(mockNext).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Couldn't send that answer/)).toBeNull();
    await waitFor(() => expect(screen.getByTestId("review-option-A")).toHaveFocus());
  });

  it("a flashcard's 404 skips it too", async () => {
    mockNext.mockResolvedValueOnce(next(CARD)).mockResolvedValueOnce(next(null));
    mockAnswer.mockRejectedValue(notFound("review item not found"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.click(await screen.findByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-2"));
    expect(await screen.findByTestId("review-skipped")).toBeTruthy();
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("review-empty")).toHaveFocus());
  });

  it("the note goes with the next item: moving on again clears it", async () => {
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(CARD)).mockResolvedValueOnce(next(null));
    mockAnswer.mockRejectedValueOnce(notFound("review item not found")).mockResolvedValue(graded({ hint: null }));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.type(await screen.findByTestId("review-answer-input"), "x");
    await userEvent.click(screen.getByTestId("review-submit"));
    await screen.findByTestId("review-skipped");
    await userEvent.click(await screen.findByTestId("review-flip"));
    await userEvent.click(screen.getByTestId("review-rate-3"));
    await userEvent.click(await screen.findByTestId("review-next"));
    await screen.findByTestId("review-empty");
    expect(screen.queryByTestId("review-skipped")).toBeNull();
  });

  it("a report 404 ('review item not served') moves on with the note, not an error", async () => {
    flags.item_reports = "on";
    mockNext.mockResolvedValueOnce(next(FREE)).mockResolvedValueOnce(next(MC));
    mockReport.mockRejectedValue(notFound("review item not served"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-item");
    await userEvent.click(screen.getByTestId("review-report"));
    await userEvent.click(screen.getByTestId("review-report-reason-unclear"));
    expect(await screen.findByTestId("review-skipped")).toBeTruthy();
    expect(await screen.findByText("Which one?")).toBeTruthy();
    expect(screen.queryByText("Couldn't report that question.")).toBeNull();
    expect(screen.queryByTestId("review-reported")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("review-option-A")).toHaveFocus());
  });
});

describe("DueQueue — a queue that failed to load can be retried", () => {
  it("shows why with a Retry that loads the queue again", async () => {
    mockNext.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(next(FREE));
    render(<DueQueue userId="u1" courseId="c1" />);
    const error = await screen.findByTestId("review-load-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toContain("Couldn't load your review queue");
    await userEvent.click(screen.getByTestId("review-load-retry"));
    expect(await screen.findByTestId("review-item")).toBeTruthy();
    expect(screen.queryByTestId("review-load-error")).toBeNull();
    expect(screen.queryByTestId("review-load-retry")).toBeNull();
    expect(mockNext).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId("review-answer-input")).toHaveFocus());
  });

  it("a Retry that fails again keeps the Retry and focuses the error", async () => {
    mockNext.mockRejectedValue(new Error("down"));
    render(<DueQueue userId="u1" courseId="c1" />);
    await userEvent.click(await screen.findByTestId("review-load-retry"));
    await waitFor(() => expect(mockNext).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId("review-load-error")).toHaveFocus());
    expect(screen.getByTestId("review-load-retry")).toBeTruthy();
  });

  it("a 429 'ai budget reached' at load says the queue did not load — never 'review keeps working'", async () => {
    mockNext
      .mockRejectedValueOnce(
        new ApiError("ai budget reached", 429, { body: { detail: "ai budget reached", reset_at: null } }),
      )
      .mockResolvedValueOnce(next(null, 600, 0));
    render(<DueQueue userId="u1" courseId="c1" />);
    const error = await screen.findByTestId("review-load-error");
    expect(error.textContent).toContain("Couldn't load your review queue: your AI budget is paused for now.");
    expect(screen.queryByTestId("review-budget-paused")).toBeNull();
    expect(screen.getByTestId("review-due-panel").textContent).not.toMatch(/keep working/);
    await userEvent.click(screen.getByTestId("review-load-retry"));
    expect(await screen.findByTestId("review-empty")).toBeTruthy();
  });

  it("another 429 at load asks the student to wait a moment", async () => {
    mockNext.mockRejectedValueOnce(new ApiError("rate limited", 429, { body: { detail: "Too many requests" } }));
    render(<DueQueue userId="u1" courseId="c1" />);
    expect((await screen.findByTestId("review-load-error")).textContent).toContain("too many requests just now");
  });

  it("hides the paused-concepts banner while the queue failed to load", async () => {
    mockNext.mockRejectedValueOnce(new Error("down"));
    mockSummary.mockResolvedValue(summary({ paused: 2 }));
    render(<DueQueue userId="u1" courseId="c1" />);
    await screen.findByTestId("review-load-error");
    await waitFor(() => expect(mockSummary).toHaveBeenCalled());
    expect(screen.queryByTestId("review-budget-paused")).toBeNull();
  });
});
