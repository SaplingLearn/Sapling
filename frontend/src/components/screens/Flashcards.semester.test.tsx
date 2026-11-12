// @vitest-environment jsdom
/**
 * Flashcards semester scoping (#141) — the semester selector
 * (lib/useActiveSemester; "" = All semesters, the untouchable DEFAULT) scopes
 * the card list READ the same way it scopes the graph.
 *
 * Pins, following Dashboard.test.tsx's call-count pattern: exactly ONE fetch,
 * carrying the stored term, never unscoped-then-scoped; and "" sends
 * undefined, so the default stays unscoped.
 *
 * These were `/study?mode=cards` specs; the pane is its own page now, and it
 * opens on a home (a prompt and decks, with the concept map a step behind it)
 * rather than on a card. The settle point is therefore the home's own
 * content, and the page's other term-scoped reads (the graph, the course
 * outline, generation) are pinned beside the card list.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
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
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
  getGraph: vi.fn(async () => ({ nodes: [], edges: [], stats: {} })),
  getAllAssignments: vi.fn(async () => ({ assignments: [] })),
}));

vi.mock("@/lib/topicChecklistApi", () => ({
  getTopicChecklist: vi.fn(async () => ({ topics: [] })),
}));

// The real module's constants (the description's length limits) with every
// call mocked.
vi.mock("@/lib/flashcardSetsApi", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/flashcardSetsApi")>()),
  listFlashcardSets: vi.fn(async () => ({ sets: [] })),
  createFlashcardSet: vi.fn(),
  updateFlashcardSet: vi.fn(),
  deleteFlashcardSet: vi.fn(),
  suggestFlashcardSet: vi.fn(),
}));

import { Flashcards } from "./Flashcards";
import { ToastProvider } from "../ToastProvider";
import { getCourses, getFlashcards, getGraph, generateFlashcards, type EnrolledCourse } from "@/lib/api";
import { getTopicChecklist } from "@/lib/topicChecklistApi";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";

const mockedCourses = vi.mocked(getCourses);
const mockedFlashcards = vi.mocked(getFlashcards);
const mockedGraph = vi.mocked(getGraph);
const mockedGenerate = vi.mocked(generateFlashcards);
const mockedChecklist = vi.mocked(getTopicChecklist);

function course(id: string, code: string, term: string): EnrolledCourse {
  return {
    enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: `${code} course`,
    school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
    enrolled_at: "2025-09-01", term,
  };
}

function renderFlashcards() {
  return render(
    <ToastProvider>
      <Flashcards />
    </ToastProvider>,
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(ACTIVE_SEMESTER_STORAGE_KEY);
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

describe("Flashcards fetch respects the active semester", () => {
  it("fetches once, scoped to the stored term — no unscoped first pass", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");

    renderFlashcards();

    // The home renders only after the (resolved) fetch — a deterministic
    // settle point for the call-count assert. (No courses here, so the home
    // says so.)
    await screen.findByText(/Add a course to make flashcards for it/);
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, "Fall 2025");
    expect(mockedFlashcards).not.toHaveBeenCalledWith("u1", undefined, undefined);
  });

  it("All semesters (the default) fetches once, unscoped", async () => {
    renderFlashcards();

    await screen.findByText(/Add a course to make flashcards for it/);
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, undefined);
  });

  it("the concept map and generation carry the stored term too, on a course of that term", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    // The spring course is listed first; the term scope leaves only the fall one.
    mockedCourses.mockResolvedValue({ courses: [course("c2", "MA210", "Spring 2026"), course("c1", "CS101", "Fall 2025")] });
    mockedGraph.mockResolvedValue({
      nodes: [{ id: "n1", course_id: "c1", concept_name: "Recursion", mastery_tier: "learning", mastery_score: 0.4 }],
      edges: [], stats: {},
    });
    const made = { id: "g1", topic: "Recursion", front: "Q", back: "A", course_id: "c1" };
    mockedGenerate.mockResolvedValue({ flashcards: [made] });

    renderFlashcards();
    await userEvent.click(await screen.findByRole("button", { name: /Build one by hand/ }));
    await userEvent.click(await screen.findByRole("checkbox", { name: /^Recursion/ }));

    expect(mockedGraph).toHaveBeenCalledTimes(1);
    expect(mockedGraph).toHaveBeenCalledWith("u1", "Fall 2025");
    expect(mockedChecklist).toHaveBeenCalledTimes(1);
    expect(mockedChecklist).toHaveBeenCalledWith("u1", "c1", "Fall 2025");
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);

    mockedFlashcards.mockResolvedValue({ flashcards: [made] });
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(mockedGenerate).toHaveBeenCalledWith("u1", "Recursion", 5, "Fall 2025", "c1"));
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    // The reload after generating is scoped like the first read.
    expect(mockedFlashcards).toHaveBeenLastCalledWith("u1", undefined, "Fall 2025");
  });

  it("a term switch never shows the old term's cards while the new term's load", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    // One course, taken in both terms: the page stays on it across the switch.
    mockedCourses.mockResolvedValue({ courses: [{ ...course("c1", "CS101", "Fall 2025"), terms: ["Fall 2025", "Spring 2026"] }] });
    mockedGraph.mockResolvedValue({
      nodes: [{ id: "n1", course_id: "c1", concept_name: "Recursion", mastery_tier: "learning", mastery_score: 0.4 }],
      edges: [], stats: {},
    });
    const fall = [1, 2].map(i => ({ id: `f${i}`, topic: "Recursion", front: "Q", back: "A", course_id: "c1" }));
    mockedFlashcards.mockResolvedValueOnce({ flashcards: fall });
    renderFlashcards();
    expect(await screen.findByText("1 concept · 2 cards")).toBeTruthy();

    let answer!: (r: { flashcards: unknown[] }) => void;
    mockedFlashcards.mockReturnValueOnce(new Promise(resolve => { answer = resolve; }) as ReturnType<typeof getFlashcards>);
    act(() => {
      window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Spring 2026");
      window.dispatchEvent(new Event("sapling-active-semester-change"));
    });

    // The new term's map is in; its cards are not. Fall's two are not shown as Spring's.
    await waitFor(() => expect(mockedGraph).toHaveBeenLastCalledWith("u1", "Spring 2026"));
    await act(async () => {});
    expect(mockedFlashcards).toHaveBeenLastCalledWith("u1", undefined, "Spring 2026");
    expect(screen.queryByText("1 concept · 2 cards")).toBeNull();
    expect(screen.getByTestId("flashcards-home-loading")).toBeTruthy();

    await act(async () => { answer({ flashcards: [] }); });
    expect(await screen.findByText("1 concept · 0 cards")).toBeTruthy();
  });
});
