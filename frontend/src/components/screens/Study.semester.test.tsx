// @vitest-environment jsdom
/**
 * Study screen semester scoping (#141) — the existing semester selector
 * (lib/useActiveSemester; "" = All semesters, the untouchable DEFAULT) must
 * scope the study-tool READS the same way it already scopes the graph.
 *
 * Pins, following Dashboard.test.tsx's call-count pattern:
 *   - the flashcards list fetch is gated on the hydrated flag and carries the
 *     stored term: exactly ONE fetch, never unscoped-then-scoped;
 *   - "" (All semesters) sends undefined — the default stays unscoped;
 *   - the guide path (exams list, guide fetch, regenerate) threads the term.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Study reads ?mode= at mount; per-describe control without remocking.
const search = { qs: "" };
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search.qs),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

// Pulls in the whole import-tab tree (and more @/lib/api names) — out of
// scope here.
vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: () => null,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getStudyGuideExams: vi.fn(async () => ({ exams: [] })),
  getStudyGuide: vi.fn(async () => ({
    guide: { exam: "Midterm 1", topics: [] },
    generated_at: "2026-04-01T00:00:00Z",
    cached: true,
  })),
  regenerateStudyGuide: vi.fn(async () => ({
    success: true,
    guide: { exam: "Midterm 1", topics: [] },
    generated_at: "2026-04-02T00:00:00Z",
  })),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
import {
  getCachedStudyGuides,
  getFlashcards,
  getStudyGuide,
  getStudyGuideExams,
  regenerateStudyGuide,
} from "@/lib/api";

const mockedFlashcards = vi.mocked(getFlashcards);
const mockedCached = vi.mocked(getCachedStudyGuides);
const mockedGuide = vi.mocked(getStudyGuide);
const mockedExams = vi.mocked(getStudyGuideExams);
const mockedRegenerate = vi.mocked(regenerateStudyGuide);

const RECENT = {
  id: "g1",
  course_id: "c1",
  exam_id: "e1",
  course_name: "Intro to CS",
  exam_title: "Midterm 1",
  overview: "",
  generated_at: "2026-04-01T00:00:00Z",
};

function renderStudy() {
  return render(
    <ToastProvider>
      <Study />
    </ToastProvider>,
  );
}

beforeEach(() => {
  search.qs = "";
});

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(ACTIVE_SEMESTER_STORAGE_KEY);
  vi.clearAllMocks();
});

describe("Study flashcards fetch respects the active semester", () => {
  beforeEach(() => {
    search.qs = "mode=cards";
  });

  it("fetches once, scoped to the stored term — no unscoped first pass", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");

    renderStudy();

    // The empty state renders only after the (resolved) fetch — a
    // deterministic settle point for the call-count assert.
    await screen.findByText("No cards here yet");
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, "Fall 2025");
    expect(mockedFlashcards).not.toHaveBeenCalledWith("u1", undefined, undefined);
  });

  it("All semesters (the default) fetches once, unscoped", async () => {
    renderStudy();

    await screen.findByText("No cards here yet");
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, undefined);
  });
});

describe("Study guide path threads the active semester", () => {
  // Regenerate isn't drivable from here: opening a recent guide deliberately
  // clears the exam selection (see GuideMode's openRecent), which leaves the
  // Regenerate button disabled — its one-line `semester || undefined`
  // threading matches the three read calls asserted below.
  it("passes the stored term to the exams and guide fetches", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    mockedCached.mockResolvedValue({ guides: [RECENT] });

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    await waitFor(() =>
      expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", "Fall 2025"),
    );
    expect(mockedExams).toHaveBeenCalledWith("u1", "c1", "Fall 2025");
    expect(mockedRegenerate).not.toHaveBeenCalled();
  });

  it("sends no semester while All semesters is active", async () => {
    mockedCached.mockResolvedValue({ guides: [RECENT] });

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    await waitFor(() =>
      expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", undefined),
    );
    expect(mockedExams).toHaveBeenCalledWith("u1", "c1", undefined);
  });
});
