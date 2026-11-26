// @vitest-environment jsdom
/**
 * `review_v2`: the learning loop's Review queue and retention check as two
 * compact rows in Study's rail, under Quick Reviews, each opening its own
 * component in the hub's modal, so the hub keeps its layout.
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockNext, mockSummary, loop, retention } = vi.hoisted(() => ({
  mockNext: vi.fn(), mockSummary: vi.fn(),
  loop: { status: true as boolean | "error" | null, retry: vi.fn() },
  retention: { courseIds: [] as string[] },
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getReviewNext: mockNext, getReviewSummary: mockSummary,
}));
vi.mock("@/context/FlagsContext", () => ({ useFlag: () => "off", useFlagMap: () => ({ flags: {}, ready: true }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/context/RetentionDueContext", async (orig) => ({
  ...(await orig<typeof import("@/context/RetentionDueContext")>()),
  useRetentionDue: () => ({ courseIds: retention.courseIds, due: retention.courseIds.length > 0, refresh: () => {} }),
}));
vi.mock("../useLoopStatus", () => ({ useLoopStatus: () => loop }));

import type { EnrolledCourse } from "@/lib/api";
import { RAIL_COPY, RailReviews } from "./RailReviews";

const COURSES = [{ course_id: "c1", course_code: "CS101", course_name: "Introduction to Computer Science" }] as EnrolledCourse[];
const summary = (flashcard: number, check: number, fresh = 0) => ({
  due: { flashcard, check }, new: fresh, in_budget: flashcard + check, unservable: 0, paused: 0, budget_min: 12, remaining_budget_s: 720, retention_target: 0.9,
});

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  loop.status = true;
  retention.courseIds = [];
  mockSummary.mockResolvedValue(summary(5, 3, 1));
  mockNext.mockResolvedValue({ item: null, remaining_budget_s: 600, session_id: "s", retention_target: 0.9, due_total: 0, in_budget: 0 });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Study's rail rows", () => {
  it("Review with the Tutor's count (due cards and checks, new cards aside) and the retention check, nothing open yet", async () => {
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    expect((await screen.findByTestId("study-rail-review-count")).textContent?.trim()).toBe("7 due");
    expect(screen.getByTestId("study-rail-retention").textContent?.trim()).toBe(RAIL_COPY.retention);
    expect(screen.queryByRole("dialog")).toBeNull(); // the hub keeps its layout: nothing inline
    expect(screen.queryByTestId("review-due-panel")).toBeNull();
  });

  it("Review opens the queue in a modal; closing it reads the count again", async () => {
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    await screen.findByTestId("study-rail-review-count");
    fireEvent.click(screen.getByTestId("study-rail-review"));
    const dialog = await screen.findByRole("dialog", { name: "Review" });
    expect(within(dialog).getByTestId("review-due-panel")).toBeTruthy();
    await waitFor(() => expect(mockNext).toHaveBeenCalled());
    await waitFor(() => expect(mockSummary.mock.calls.length).toBeGreaterThanOrEqual(2)); // the queue's own read
    const before = mockSummary.mock.calls.length;
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(mockSummary.mock.calls.length).toBe(before + 1)); // the row's count, read again
  });

  it("the retention check says Ready when one is due, and opens in a modal on the due course", async () => {
    retention.courseIds = ["c1"];
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    expect(screen.getByTestId("study-rail-retention-ready").textContent?.trim()).toBe(RAIL_COPY.ready);
    fireEvent.click(screen.getByTestId("study-rail-retention"));
    const dialog = await screen.findByRole("dialog", { name: RAIL_COPY.retention });
    expect((within(dialog).getByTestId("retention-course") as HTMLSelectElement).value).toBe("c1");
  });

  it("the Study deep link (?retention-course=) opens the retention check at once", async () => {
    render(<RailReviews courses={COURSES} retentionCourse="c1" />);
    expect(await screen.findByRole("dialog", { name: RAIL_COPY.retention })).toBeTruthy();
  });

  it("nothing due: Review without a count; the loop off: no rows; a failed status read: a retry", async () => {
    mockSummary.mockResolvedValue(summary(0, 0));
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    await waitFor(() => expect(mockSummary).toHaveBeenCalled());
    expect(screen.getByTestId("study-rail-review")).toBeTruthy();
    expect(screen.queryByTestId("study-rail-review-count")).toBeNull();
    cleanup();
    loop.status = false;
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    expect(screen.queryByTestId("study-reviews")).toBeNull();
    cleanup();
    loop.status = "error";
    render(<RailReviews courses={COURSES} retentionCourse="" />);
    fireEvent.click(screen.getByTestId("review-status-retry"));
    expect(loop.retry).toHaveBeenCalled();
  });
});
