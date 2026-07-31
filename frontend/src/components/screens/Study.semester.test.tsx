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
  getCourses,
  getFlashcards,
  getStudyGuide,
  getStudyGuideExams,
  regenerateStudyGuide,
  type EnrolledCourse,
} from "@/lib/api";

const mockedFlashcards = vi.mocked(getFlashcards);
const mockedCached = vi.mocked(getCachedStudyGuides);
const mockedGuide = vi.mocked(getStudyGuide);
const mockedExams = vi.mocked(getStudyGuideExams);
const mockedRegenerate = vi.mocked(regenerateStudyGuide);
const mockedCourses = vi.mocked(getCourses);

const RECENT = {
  id: "g1",
  course_id: "c1",
  exam_id: "e1",
  course_name: "Intro to CS",
  exam_title: "Midterm 1",
  overview: "",
  generated_at: "2026-04-01T00:00:00Z",
};

// Must survive the Fall 2025 scopedCourses filter (courseInTerm) so it shows
// in the course picker.
const COURSE_C1: EnrolledCourse = {
  enrollment_id: "enr-1",
  course_id: "c1",
  course_code: "CS101",
  course_name: "Intro to CS",
  school: "BU",
  department: "CS",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2025-09-01",
  term: "Fall 2025",
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

describe("Study guide path threads the right term", () => {
  // Regenerate is driven from the rail in Study.recentGuides.test.tsx — it
  // became reachable there once #476 stopped the courseId-keyed effect from
  // clearing the exam openRecent had set. These cases stay on the READ path;
  // regenerate's own term threading is asserted with that fix.
  it("opens a recent guide AS ITS OWN TERM, not the active selector's (#475 F1)", async () => {
    // Active selector says Fall 2025; the rail entry is a Spring 2026 guide.
    // Loading it under the active term would cache-miss on the (offering,
    // exam) key and silently generate-and-persist a mismatched row.
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    mockedCached.mockResolvedValue({
      guides: [{ ...RECENT, semester: "Spring 2026" }],
    });

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    await waitFor(() =>
      expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", "Spring 2026"),
    );
    expect(mockedGuide).not.toHaveBeenCalledWith("u1", "c1", "e1", "Fall 2025");
    // The exams picker still follows the ACTIVE selector — only the recent
    // open itself is pinned to the entry's term.
    expect(mockedExams).toHaveBeenCalledWith("u1", "c1", "Fall 2025");
    expect(mockedRegenerate).not.toHaveBeenCalled();
  });

  it("opens a term-less recent entry unscoped, even with an active term", async () => {
    // Legacy cached shape (no semester field): the entry's own term is
    // unknown, so the open falls back to unscoped current-term resolution —
    // NOT the active selector's term, which the entry need not belong to.
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    mockedCached.mockResolvedValue({ guides: [RECENT] });

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    await waitFor(() =>
      expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", undefined),
    );
  });

  it("picker-driven loads use the active semester", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    mockedCourses.mockResolvedValue({ courses: [COURSE_C1] });
    mockedExams.mockResolvedValue({
      exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-04-01" }],
    });

    renderStudy();
    await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));
    await userEvent.click(await screen.findByRole("option", { name: /CS101/ }));
    await userEvent.click(await screen.findByRole("button", { name: /pick an exam/i }));
    await userEvent.click(await screen.findByRole("option", { name: /Midterm 1/ }));

    await waitFor(() =>
      expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", "Fall 2025"),
    );
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

describe("Study guide 404 copy (#475 F4)", () => {
  it("shows the backend sentence for a no-offering 404, not the deleted-exam copy", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockedCached.mockResolvedValue({
      guides: [{ ...RECENT, semester: "Fall 2025" }],
    });
    // Like the real ApiError: body text as message + the HTTP status attached
    // (the detail has no "not found" wording, so isNotFound needs the status).
    mockedGuide.mockRejectedValue(
      Object.assign(
        new Error('{"detail":"No offering of this course in that semester."}'),
        { status: 404 },
      ),
    );

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    expect(
      await screen.findByText("No offering of this course in that semester."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/isn't around anymore/i)).toBeNull();
    // 404s stay guidance, never a red toast (role="status").
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });
});
