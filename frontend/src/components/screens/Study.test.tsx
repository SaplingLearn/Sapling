// @vitest-environment jsdom
/**
 * Component tests for the Study screen's study-guide failure UX (#361):
 *   1. A guide whose exam is gone lands on inline guidance, with NO toast
 *   2. A genuine generation failure toasts a sentence (never the raw body)
 *      and leaves a working retry on screen
 *
 * The recent-guides rail is the entry point under test because it's the real
 * path to a stale exam id, and it needs no dropdown interaction to reach.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getStudyGuideExams: vi.fn(async () => ({ exams: [] })),
  getStudyGuide: vi.fn(),
  regenerateStudyGuide: vi.fn(),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { getCachedStudyGuides, getStudyGuide } from "@/lib/api";

const mockedCached = vi.mocked(getCachedStudyGuides);
const mockedGuide = vi.mocked(getStudyGuide);

const RECENT = {
  id: "g1",
  course_id: "c1",
  exam_id: "exam-deleted",
  course_name: "Intro to CS",
  exam_title: "Midterm 1",
  overview: "",
  generated_at: "2026-04-01T00:00:00Z",
};

/** Clicks the recent-guides entry, which sets the course + exam and kicks
 *  off the guide load the tests are about. */
async function openRecentGuide() {
  render(
    <ToastProvider>
      <Study />
    </ToastProvider>,
  );
  await userEvent.click(await screen.findByText("Midterm 1"));
}

beforeEach(() => {
  mockedCached.mockResolvedValue({ guides: [RECENT] });
  // The screen logs the real error for debuggability; keep it out of the
  // test output.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Study — study guide for an exam that no longer exists", () => {
  beforeEach(() => {
    mockedGuide.mockRejectedValue(
      new Error('{"detail":"Exam not found. It may have been deleted — pick another exam."}'),
    );
  });

  it("shows inline guidance instead of an error toast", async () => {
    await openRecentGuide();

    expect(await screen.findByText(/isn't around anymore/i)).toBeTruthy();
    expect(screen.getByText(/Calendar page/i)).toBeTruthy();
    // Toasts render with role="status"; a missing exam must produce none.
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });

  it("does not stack the generic no-exams hint on top of the guidance", async () => {
    await openRecentGuide();

    await screen.findByText(/isn't around anymore/i);
    expect(screen.queryByText(/No exams for this course yet/i)).toBeNull();
  });

  it("offers no retry — retrying a deleted exam can't succeed", async () => {
    await openRecentGuide();

    await screen.findByText(/isn't around anymore/i);
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });
});

describe("Study — study guide that genuinely fails to build", () => {
  beforeEach(() => {
    mockedGuide.mockRejectedValue(
      new Error('{"detail":"Study guide generation failed."}'),
    );
  });

  it("toasts the server sentence, not the raw response body", async () => {
    await openRecentGuide();

    const toasts = await screen.findAllByRole("status");
    const text = toasts.map(t => t.textContent).join(" ");
    expect(text).toContain("Study guide generation failed.");
    expect(text).not.toContain("{");
    expect(text).not.toContain("detail");
    expect(text).not.toContain("[object Object]");
  });

  it("keeps a working retry on screen", async () => {
    await openRecentGuide();

    const retry = await screen.findByRole("button", { name: /try again/i });
    expect(mockedGuide).toHaveBeenCalledTimes(1);

    await userEvent.click(retry);

    expect(mockedGuide).toHaveBeenCalledTimes(2);
    // Retries the exam that failed, not whatever the selects currently hold.
    // (4th arg: the active semester — undefined here, All semesters, #141.)
    expect(mockedGuide).toHaveBeenLastCalledWith("u1", "c1", "exam-deleted", undefined);
  });
});
