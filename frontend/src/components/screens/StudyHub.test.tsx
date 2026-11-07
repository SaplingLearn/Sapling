// @vitest-environment jsdom
/**
 * The Study landing page: one card per tool, each linking into it with a live
 * status line; the Quiz card obeys `hide_quiz`; and no AI call is made (the
 * quiz card reuses quiz home's pure ranking, never `useQuizHome`).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/study",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useActiveSemester", () => ({
  useActiveSemester: () => ["", () => {}, true],
  courseInTerm: () => true,
}));

const flagState = { flags: {} as Record<string, string>, ready: true };
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => flagState,
}));

vi.mock("@/lib/api", () => ({
  getCachedStudyGuides: vi.fn(async () => ({
    guides: [{
      id: "g1", course_id: "c1", exam_id: "e1", course_name: "Intro to CS",
      exam_title: "Midterm Exam", overview: "", generated_at: "2026-03-01T00:00:00Z",
    }],
  })),
  getFlashcards: vi.fn(async () => ({
    flashcards: [{ topic: "CS Basics" }, { topic: "CS Basics" }, { topic: "Linear Algebra" }],
  })),
  getCourses: vi.fn(async () => ({
    courses: [{ course_id: "c1", course_code: "CS101", course_name: "Intro to CS", color: "#36c" }],
  })),
  getGraph: vi.fn(async () => ({
    nodes: [
      { id: "n1", concept_name: "Recursion", mastery_score: 0.25, mastery_tier: "struggling", times_studied: 2, last_studied_at: null, subject: "CS", course_id: "c1" },
      { id: "n2", concept_name: "Loops", mastery_score: 0.6, mastery_tier: "learning", times_studied: 0, last_studied_at: null, subject: "CS", course_id: "c1" },
      { id: "n3", concept_name: "Variables", mastery_score: 0.95, mastery_tier: "mastered", times_studied: 4, last_studied_at: null, subject: "CS", course_id: "c1" },
    ],
    edges: [],
    stats: {},
  })),
}));

const describeConcept = vi.fn();
vi.mock("@/lib/quiz/api", () => ({
  listAttempts: vi.fn(async () => ({ attempts: [] })),
  describeConcept: (...a: unknown[]) => describeConcept(...a),
}));

import { StudyHub } from "./StudyHub";

beforeEach(() => {
  flagState.flags = {};
  describeConcept.mockReset();
});
afterEach(cleanup);

describe("StudyHub", () => {
  it("links each tool card into its tool", () => {
    render(<StudyHub />);
    expect(screen.getByTestId("study-hub-card-guide").getAttribute("href")).toBe("/study?mode=guide");
    expect(screen.getByTestId("study-hub-card-cards").getAttribute("href")).toBe("/study?mode=cards");
    expect(screen.getByTestId("study-hub-card-quiz").getAttribute("href")).toBe("/quiz");
  });

  it("shows each tool's live status", async () => {
    render(<StudyHub />);
    const guide = screen.getByTestId("study-hub-card-guide");
    expect(await within(guide).findByText("Midterm Exam")).toBeTruthy();

    const cards = screen.getByTestId("study-hub-card-cards");
    expect(await within(cards).findByText("3 cards")).toBeTruthy();
    expect(within(cards).getByText(/2 topics/)).toBeTruthy();

    // The weakest concept the student has opened (quiz home's primary), and
    // the due count over the non-mastered tiers.
    const quiz = screen.getByTestId("study-hub-card-quiz");
    expect(await within(quiz).findByText("Recursion")).toBeTruthy();
    expect(within(quiz).getByText(/2 concepts to review across 1 course\b/)).toBeTruthy();
    expect(describeConcept).not.toHaveBeenCalled();
  });

  it("drops the Quiz card when hide_quiz is on", () => {
    flagState.flags = { hide_quiz: "on" };
    render(<StudyHub />);
    expect(screen.queryByTestId("study-hub-card-quiz")).toBeNull();
    expect(screen.getByTestId("study-hub-card-guide")).toBeTruthy();
  });
});
