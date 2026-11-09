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
 * These were `/study?mode=cards` specs; the pane is its own page now.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

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
}));

import { Flashcards } from "./Flashcards";
import { ToastProvider } from "../ToastProvider";
import { getFlashcards } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";

const mockedFlashcards = vi.mocked(getFlashcards);

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
  vi.clearAllMocks();
});

describe("Flashcards fetch respects the active semester", () => {
  it("fetches once, scoped to the stored term — no unscoped first pass", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");

    renderFlashcards();

    // The empty state renders only after the (resolved) fetch — a
    // deterministic settle point for the call-count assert.
    await screen.findByText("No cards here yet");
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, "Fall 2025");
    expect(mockedFlashcards).not.toHaveBeenCalledWith("u1", undefined, undefined);
  });

  it("All semesters (the default) fetches once, unscoped", async () => {
    renderFlashcards();

    await screen.findByText("No cards here yet");
    expect(mockedFlashcards).toHaveBeenCalledTimes(1);
    expect(mockedFlashcards).toHaveBeenCalledWith("u1", undefined, undefined);
  });
});
