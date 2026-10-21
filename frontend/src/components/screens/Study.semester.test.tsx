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
 * Unified assessment-guide scoping is covered in StudyPlanPanel.test.tsx and
 * Study.recentGuides.test.tsx.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

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
  // PKG-12: the learning loop is off (the review probe 404s) — the legacy UI.
  getLoopStatus: vi.fn(async () => ({ active: false })),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
import {
  getFlashcards,
} from "@/lib/api";

const mockedFlashcards = vi.mocked(getFlashcards);
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
  vi.restoreAllMocks(); // the console.error spy in the 404 test
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
