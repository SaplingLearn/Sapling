// @vitest-environment jsdom
/**
 * Flashcards — async races in the review session (#769).
 *
 * rate() is guarded against repeats, a failed rating doesn't advance, the end
 * of the deck is an explicit state, and generating cards keeps the reviewer's
 * place.
 *
 * These were `/study?mode=cards` specs. The pane is its own page now
 * (screens/Flashcards.tsx), so they render that screen directly — the only
 * change to the assertions is what gets mounted.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
import {
  getCourses,
  getFlashcards,
  generateFlashcards,
  rateFlashcard,
  type EnrolledCourse,
} from "@/lib/api";

const mockedCourses = vi.mocked(getCourses);
const mockedCards = vi.mocked(getFlashcards);
const mockedGenerate = vi.mocked(generateFlashcards);
const mockedRate = vi.mocked(rateFlashcard);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function course(id: string, code: string, name: string): EnrolledCourse {
  return {
    enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name,
    school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
    enrolled_at: "2025-09-01", term: "Fall 2025",
  };
}

function renderFlashcards() {
  return render(
    <ToastProvider>
      <Flashcards />
    </ToastProvider>,
  );
}

beforeEach(() => {
  search.qs = "";
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

// ── helpers ───────────────────────────────────────────────────────────────

const card = (id: string) => ({ id, front: `Q-${id}`, back: `A-${id}`, topic: "Bio" });

const flip = () => fireEvent.keyDown(window, { code: "Space", key: " " });
const press = (key: string, repeat = false) => fireEvent.keyDown(window, { key, code: `Digit${key}`, repeat });
// Flip, then wait until the flip has rendered (the rating buttons enable only
// when the card is flipped). Pressing a rating key before that re-render lands
// on the unflipped handler and is ignored, which flaked these tests on slow CI.
const flipCard = async () => {
  act(() => { flip(); });
  await waitFor(() => expect(screen.getByTitle(/\(press 3\)/)).toBeEnabled());
};

describe("Flashcards — review session state (#769)", () => {
  beforeEach(() => {
    mockedCards.mockResolvedValue({ flashcards: [card("a"), card("b")] });
  });

  it("rates a card ONCE however many times the key fires while saving", async () => {
    const pending = deferred<{ ok: boolean }>();
    mockedRate.mockReturnValue(pending.promise);
    renderFlashcards();
    await screen.findByText("Card 1 of 2");

    await flipCard();
    act(() => { press("3"); press("3"); press("3", true); });
    await act(async () => { pending.resolve({ ok: true }); });

    expect(mockedRate).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Card 2 of 2")).toBeTruthy();
  });

  it("a failed rating keeps the card up and tells the student", async () => {
    mockedRate.mockRejectedValueOnce(new Error("boom"));
    renderFlashcards();
    await screen.findByText("Card 1 of 2");

    await flipCard();
    await act(async () => { press("2"); });

    expect(await screen.findByText(/Couldn't save that rating/i)).toBeTruthy();
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    // Still flipped, so the same key retries.
    mockedRate.mockResolvedValueOnce({ ok: true });
    await act(async () => { press("2"); });
    expect(mockedRate).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Card 2 of 2")).toBeTruthy();
  });

  it("rating the last card lands on an explicit end-of-deck state", async () => {
    mockedRate.mockResolvedValue({ ok: true });
    renderFlashcards();
    await screen.findByText("Card 1 of 2");

    await flipCard();
    await act(async () => { press("3"); });
    await screen.findByText("Card 2 of 2");
    await flipCard();
    await act(async () => { press("3"); });

    expect(await screen.findByText("Deck complete")).toBeTruthy();
    expect(screen.queryByText(/Card 1 of 2/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /review again/i }));
    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
  });

  it("generating for a selected course sends that course's id (#829)", async () => {
    mockedCourses.mockResolvedValue({ courses: [course("c1", "CS101", "Intro to CS")] });
    mockedGenerate.mockResolvedValue({ flashcards: [card("n")], context_used: { documents_found: 2, weak_concepts_found: 0 } });
    renderFlashcards();
    await screen.findByText("Card 1 of 2");
    await userEvent.click(await screen.findByRole("button", { name: /CS101/ }));
    await userEvent.click(screen.getByRole("button", { name: /generate cards/i }));
    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
    expect(mockedGenerate).toHaveBeenCalledWith("u1", "Intro to CS", 5, undefined, "c1");
  });

  it("a free-text topic sends no course id (#829)", async () => {
    mockedGenerate.mockResolvedValue({ flashcards: [card("n")], context_used: { documents_found: 0, weak_concepts_found: 0 } });
    renderFlashcards();
    await screen.findByText("Card 1 of 2");
    await userEvent.click(screen.getByRole("button", { name: /^Bio$/ }));
    await userEvent.click(screen.getByRole("button", { name: /generate cards/i }));
    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
    expect(mockedGenerate).toHaveBeenCalledWith("u1", "Bio", 5, undefined, undefined);
  });

  it("generating new cards keeps the current position", async () => {
    mockedRate.mockResolvedValue({ ok: true });
    renderFlashcards();
    await screen.findByText("Card 1 of 2");
    await flipCard();
    await act(async () => { press("3"); });
    await screen.findByText("Card 2 of 2");

    // The new card sorts FIRST — an index-preserving reload would land on "a".
    mockedGenerate.mockResolvedValue({ flashcards: [card("n")], context_used: { documents_found: 1, weak_concepts_found: 0 } });
    mockedCards.mockResolvedValue({ flashcards: [card("n"), card("a"), card("b")] });
    await userEvent.click(screen.getByRole("button", { name: /^Bio$/ }));
    await userEvent.click(screen.getByRole("button", { name: /generate cards/i }));

    expect(await screen.findByText("Card 3 of 3")).toBeTruthy();
    expect(screen.getAllByText("Q-b").length).toBeGreaterThan(0);
  });
});
