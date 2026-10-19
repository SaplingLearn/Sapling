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
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockNext, mockAnswer, mockSummary } = vi.hoisted(() => ({
  mockNext: vi.fn(),
  mockAnswer: vi.fn(),
  mockSummary: vi.fn(),
}));

// The real module for everything else (budgetPauseOf, ApiError); the three
// review clients are mocked.
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getReviewNext: mockNext,
  answerReview: mockAnswer,
  getReviewSummary: mockSummary,
}));

import { ApiError } from "@/lib/api";
import { DueQueue } from "./DueQueue";

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
