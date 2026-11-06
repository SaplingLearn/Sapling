// @vitest-environment jsdom
/**
 * Study — async races in the guide and flashcard panes (#769).
 *
 * Guide: loadGuide / regenerate / the exam list each carry a
 * latest-request-wins token (lib/useLatestRequest), so a slow OLDER reply
 * can't paint over a newer pick, and an older request's `finally` can't clear
 * a loading flag a newer one still owns.
 *
 * Flashcards: rate() is guarded against repeats, a failed rating doesn't
 * advance, the end of the deck is an explicit state, and generating cards
 * keeps the reviewer's place.
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
import {
  getCachedStudyGuides,
  getCourses,
  getStudyGuide,
  getStudyGuideExams,
  regenerateStudyGuide,
  getFlashcards,
  generateFlashcards,
  rateFlashcard,
  type EnrolledCourse,
} from "@/lib/api";

const mockedCached = vi.mocked(getCachedStudyGuides);
const mockedCourses = vi.mocked(getCourses);
const mockedExams = vi.mocked(getStudyGuideExams);
const mockedGuide = vi.mocked(getStudyGuide);
const mockedRegenerate = vi.mocked(regenerateStudyGuide);
const mockedCards = vi.mocked(getFlashcards);
const mockedGenerate = vi.mocked(generateFlashcards);
const mockedRate = vi.mocked(rateFlashcard);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const guideReply = (exam: string) => ({
  guide: { exam, due_date: "", overview: "", topics: [] },
  generated_at: "2026-04-01T00:00:00Z",
  cached: true,
});

function entry(id: string, examId: string, title: string) {
  return {
    id, course_id: "c1", exam_id: examId, course_name: "Intro to CS",
    exam_title: title, overview: "", generated_at: "2026-04-01T00:00:00Z",
  };
}

function course(id: string, code: string, name: string): EnrolledCourse {
  return {
    enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name,
    school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
    enrolled_at: "2025-09-01", term: "Fall 2025",
  };
}

function renderStudy() {
  return render(
    <ToastProvider>
      <Study />
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

describe("Study guide — latest pick wins (#769)", () => {
  beforeEach(() => {
    mockedCached.mockResolvedValue({
      guides: [entry("g1", "e1", "Midterm 1"), entry("g2", "e2", "Final")],
    });
  });

  it("a slow guide for the previous exam never paints over the newer pick", async () => {
    const a = deferred<ReturnType<typeof guideReply>>();
    const b = deferred<ReturnType<typeof guideReply>>();
    mockedGuide.mockImplementation(async (_u, _c, eid) => (eid === "e1" ? a.promise : b.promise));

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));
    await userEvent.click(screen.getByText("Final"));

    // The OLDER request settles first. Before #769 it painted GUIDE-A and its
    // `finally` cleared the spinner the newer request still owned.
    await act(async () => { a.resolve(guideReply("GUIDE-A")); });
    expect(screen.queryByText("GUIDE-A")).toBeNull();

    await act(async () => { b.resolve(guideReply("GUIDE-B")); });
    expect(await screen.findByText("GUIDE-B")).toBeTruthy();
    expect(screen.queryByText("GUIDE-A")).toBeNull();
  });

  it("a stale failure doesn't surface an error for the exam on screen", async () => {
    const a = deferred<ReturnType<typeof guideReply>>();
    mockedGuide.mockImplementation(async (_u, _c, eid) =>
      eid === "e1" ? a.promise : guideReply("GUIDE-B"),
    );

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));
    await userEvent.click(screen.getByText("Final"));
    expect(await screen.findByText("GUIDE-B")).toBeTruthy();

    await act(async () => { a.reject(new Error('{"detail":"Study guide generation failed."}')); });
    expect(screen.getByText("GUIDE-B")).toBeTruthy();
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });

  it("a regenerate superseded by another pick doesn't paint the old exam's guide", async () => {
    const regen = deferred<Awaited<ReturnType<typeof regenerateStudyGuide>>>();
    mockedRegenerate.mockReturnValue(regen.promise);
    mockedGuide.mockImplementation(async (_u, _c, eid) =>
      guideReply(eid === "e1" ? "GUIDE-A" : "GUIDE-B"),
    );

    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));
    await screen.findByText("GUIDE-A");
    // Regenerate needs the exam selected; the rail path keeps it (#476).
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }));
    await userEvent.click(screen.getByText("Final"));
    expect(await screen.findByText("GUIDE-B")).toBeTruthy();

    await act(async () => {
      regen.resolve({ success: true, guide: { exam: "GUIDE-A-REBUILT", due_date: "", overview: "", topics: [] }, generated_at: "x" });
    });
    expect(screen.queryByText("GUIDE-A-REBUILT")).toBeNull();
    expect(screen.getByText("GUIDE-B")).toBeTruthy();
    // Its flag still clears — Regenerate is usable again for the new exam.
    await waitFor(() => expect(screen.getByRole("button", { name: /regenerate/i })).toBeEnabled());
  });

  it("a course switch drops the previous course's late exam list", async () => {
    mockedCached.mockResolvedValue({ guides: [] });
    mockedCourses.mockResolvedValue({
      courses: [course("c1", "CS101", "Intro to CS"), course("c2", "CS201", "Data Structures")],
    });
    const c1Exams = deferred<{ exams: { id: string; title: string; due_date: string }[] }>();
    mockedExams.mockImplementation(async (_u, cid) =>
      cid === "c1" ? c1Exams.promise : { exams: [{ id: "x2", title: "C2 Final", due_date: "2026-05-01" }] },
    );

    renderStudy();
    await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));
    await userEvent.click(await screen.findByRole("option", { name: /CS101/ }));
    const triggers = () =>
      Array.from(document.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="listbox"]'));
    await userEvent.click(triggers()[0]);
    await userEvent.click(await screen.findByRole("option", { name: /CS201/ }));
    await waitFor(() => expect(triggers()[1]).toBeEnabled());

    await act(async () => {
      c1Exams.resolve({ exams: [{ id: "x1", title: "C1 Midterm", due_date: "2026-04-01" }] });
    });
    await userEvent.click(triggers()[1]);
    expect(await screen.findByRole("option", { name: /C2 Final/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /C1 Midterm/ })).toBeNull();
  });
});

// ── Flashcards ───────────────────────────────────────────────────────────────

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

describe("Study flashcards — review session state (#769)", () => {
  beforeEach(() => {
    search.qs = "mode=cards";
    mockedCards.mockResolvedValue({ flashcards: [card("a"), card("b")] });
  });

  it("rates a card ONCE however many times the key fires while saving", async () => {
    const pending = deferred<{ ok: boolean }>();
    mockedRate.mockReturnValue(pending.promise);
    renderStudy();
    await screen.findByText("Card 1 of 2");

    await flipCard();
    act(() => { press("3"); press("3"); press("3", true); });
    await act(async () => { pending.resolve({ ok: true }); });

    expect(mockedRate).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Card 2 of 2")).toBeTruthy();
  });

  it("a failed rating keeps the card up and tells the student", async () => {
    mockedRate.mockRejectedValueOnce(new Error("boom"));
    renderStudy();
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
    renderStudy();
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

  it("generating new cards keeps the current position", async () => {
    mockedRate.mockResolvedValue({ ok: true });
    renderStudy();
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
