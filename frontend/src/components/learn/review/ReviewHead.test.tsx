// @vitest-environment jsdom
/**
 * Review in Study, rebuilt (Tutor redesign phase 4, `review_v2`) against its
 * design board, `../__fixtures__/review.design.html`, kept verbatim: the
 * title, one chip per course and "All courses", "3 of 9", and a retention
 * check that names the course it is ready for (words and structure, not
 * pixels).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockNext, mockAnswer, mockSummary, flags } = vi.hoisted(() => ({
  mockNext: vi.fn(), mockAnswer: vi.fn(), mockSummary: vi.fn(), flags: {} as Record<string, string>,
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getReviewNext: mockNext, answerReview: mockAnswer, getReviewSummary: mockSummary,
}));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (key: string) => flags[key] ?? "off", useFlagMap: () => ({ flags, ready: true }) }));
vi.mock("@/context/RetentionDueContext", async (orig) => ({
  ...(await orig<typeof import("@/context/RetentionDueContext")>()),
  useRetentionDue: () => ({ courseIds: ["c2"], refresh: () => {} }),
}));

import type { EnrolledCourse } from "@/lib/api";
import { REVIEW_COPY, reviewProgress } from "./ReviewHead";
import { ReviewSlot } from "./ReviewSlot";
import { RetentionCheck } from "../RetentionCheck";

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/review.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const SR = { stage: "acquire", correct: 0, target: 3 } as const;
const FREE = (id: string) => ({ kind: "check", id, node_id: "n1", concept_name: "Stacks", format: "free", difficulty: 2, cost_s: 45, sr: SR, prompt: `What is on top? (${id})` });
const next = (item: unknown, inBudget: number) => ({ item, remaining_budget_s: 600, session_id: "s", retention_target: 0.9, due_total: inBudget, in_budget: inBudget });
const COURSES = [
  { course_id: "c1", course_code: "CS 112", course_name: "Introduction to Computer Science II" },
  { course_id: "c2", course_code: "MA 242", course_name: "Linear Algebra" },
] as EnrolledCourse[];

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  mockSummary.mockResolvedValue({ due: { flashcard: 0, check: 0 }, in_budget: 0, unservable: 0, paused: 0, budget_min: 12, remaining_budget_s: 720, retention_target: 0.9 });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  for (const k of Object.keys(flags)) delete flags[k];
});

describe("where the student is", () => {
  it("the item on screen among those answered this visit and what today's budget still covers", () => {
    expect(reviewProgress(2, 7, true)).toBe("3 of 9");
    expect(reviewProgress(0, 1, true)).toBe("1 of 1");
    expect(reviewProgress(3, 0, false)).toBeNull(); // nothing on screen
    expect(reviewProgress(0, null, true)).toBeNull();
  });
});

describe("parity with the design board", () => {
  it.each([REVIEW_COPY.title, REVIEW_COPY.allCourses, "3 of 9", "Retention check ready for MA 242", "I don't know"])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("review_v2 on: Review, a chip per course and All courses, the queue over every course first; a pick serves that course", async () => {
    flags.review_v2 = "on";
    mockNext.mockImplementation(async (_u: string, courseId?: string) => next(FREE(courseId ?? "all"), 3));
    render(<ReviewSlot userId="u1" courses={COURSES} />);
    expect(screen.getByRole("heading", { name: "Review" })).toBeTruthy();
    expect(screen.queryByTestId("review-budget")).toBeNull(); // the minutes chip is gone
    const chips = screen.getByRole("radiogroup", { name: REVIEW_COPY.scope });
    expect(Array.from(chips.querySelectorAll("label")).map((l) => l.textContent)).toEqual(["CS 112", "MA 242", "All courses"]);
    expect(screen.getByRole("radio", { name: "All courses" })).toBeChecked();
    await screen.findByText("What is on top? (all)");
    expect(mockNext).toHaveBeenLastCalledWith("u1", undefined);
    expect(screen.getByTestId("review-progress").textContent).toBe("1 of 3");
    fireEvent.click(screen.getByRole("radio", { name: "MA 242" }));
    await screen.findByText("What is on top? (c2)");
    expect(mockNext).toHaveBeenLastCalledWith("u1", "c2");
  });

  it("an answer recorded moves the count on with the next item", async () => {
    flags.review_v2 = "on";
    mockNext.mockResolvedValueOnce(next(FREE("a"), 3)).mockResolvedValueOnce(next(FREE("b"), 2));
    mockAnswer.mockResolvedValue({ correct: true, hint: "Nice.", next_due_at: null, rating: 3, remaining_budget_s: 500, sr: SR, unavailable: false, refused: false });
    render(<ReviewSlot userId="u1" courses={COURSES} />);
    await screen.findByText("What is on top? (a)");
    await userEvent.type(screen.getByRole("textbox"), "7");
    await userEvent.click(screen.getByTestId("review-submit"));
    await screen.findByTestId("review-hint");
    expect(screen.getByTestId("review-progress").textContent).toBe("1 of 3"); // still this item
    await userEvent.click(screen.getByTestId("review-next"));
    await screen.findByText("What is on top? (b)");
    await waitFor(() => expect(screen.getByTestId("review-progress").textContent).toBe("2 of 3"));
  });

  it("review_v2 off: Due today, as before, over every course", async () => {
    mockNext.mockResolvedValue(next(null, 0));
    render(<ReviewSlot userId="u1" courses={COURSES} />);
    expect(screen.getByRole("heading", { name: "Due today" })).toBeTruthy();
    expect(screen.queryByTestId("review-scope")).toBeNull();
    await waitFor(() => expect(mockNext).toHaveBeenCalledWith("u1", undefined));
  });
});

describe("the retention check beside the queue", () => {
  it("review_v2 on: a check due for the course on screen names it; another course's says only Retention check", () => {
    flags.review_v2 = "on";
    render(<RetentionCheck userId="u1" courses={COURSES} initialCourseId="c2" />);
    expect(screen.getByTestId("retention-title").textContent).toBe("Retention check ready for MA 242");
    fireEvent.change(screen.getByTestId("retention-course"), { target: { value: "c1" } });
    expect(screen.getByTestId("retention-title").textContent).toBe("Retention check");
  });

  it("review_v2 off: Retention check, as before", () => {
    render(<RetentionCheck userId="u1" courses={COURSES} initialCourseId="c2" />);
    expect(screen.getByTestId("retention-title").textContent).toBe("Retention check");
  });
});
