// @vitest-environment jsdom
/**
 * Flashcards — async races in the review session (#769).
 *
 * rate() is guarded against repeats, a failed rating doesn't advance, the end
 * of the deck is an explicit state, and generation is scoped to the selected
 * course by id (#829).
 *
 * These were `/study?mode=cards` specs, then specs of a page that opened
 * straight on a card. The page now opens on a home (a prompt and decks) with
 * a builder behind it (pick concepts, then Start), so every spec here ENTERS
 * the review the way a student does: the Study hub's `start=1` deep link, or
 * the builder's Start button. What they pin about the review itself is
 * unchanged.
 *
 * One spec was retired on purpose: "generating new cards keeps the current
 * position". Generation now happens before a review starts (Start makes the
 * missing cards first), so there is no mid-review generate to keep a place
 * through. Its replacement pins the new order of events.
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
import {
  getCourses,
  getFlashcards,
  getGraph,
  generateFlashcards,
  rateFlashcard,
  deleteFlashcard,
  type EnrolledCourse,
} from "@/lib/api";

const mockedCourses = vi.mocked(getCourses);
const mockedCards = vi.mocked(getFlashcards);
const mockedGraph = vi.mocked(getGraph);
const mockedGenerate = vi.mocked(generateFlashcards);
const mockedRate = vi.mocked(rateFlashcard);
const mockedDelete = vi.mocked(deleteFlashcard);

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

/** Arrive as the Study hub sends a student: the URL the page reads on mount,
 *  and the live one `start` is consumed from. */
function arriveAt(qs: string) {
  search.qs = qs;
  window.history.replaceState(null, "", qs ? `/flashcards?${qs}` : "/flashcards");
}

function renderFlashcards() {
  return render(
    // The decks are shuffled (the default); these specs only count cards.
    <ToastProvider>
      <Flashcards />
    </ToastProvider>,
  );
}

const node = (id: string, name: string) =>
  ({ id, course_id: "c1", concept_name: name, mastery_tier: "learning", mastery_score: 0.5 });

beforeEach(() => {
  arriveAt("");
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  arriveAt("");
  vi.restoreAllMocks();
  // Back to each mock's default (the factory's), so nothing a spec set up
  // leaks into the next.
  vi.resetAllMocks();
});

// ── helpers ───────────────────────────────────────────────────────────────

/** From the home into the builder, with nothing ticked. */
const openBuilder = async () => userEvent.click(await screen.findByRole("button", { name: /Build one by hand/ }));

const card = (id: string, topic = "Bio") => ({ id, front: `Q-${id}`, back: `A-${id}`, topic, course_id: "c1" });

const flip = () => fireEvent.keyDown(window, { code: "Space", key: " " });
const press = (key: string, repeat = false) => fireEvent.keyDown(window, { key, code: `Digit${key}`, repeat });
// Flip, then wait until the flip has rendered (the rating buttons enable only
// when the card is flipped). Pressing a rating key before that re-render lands
// on the unflipped handler and is ignored, which flaked these tests on slow CI.
const flipCard = async () => {
  // The review mounts when its deck is ready, and listens for keys from an
  // effect: let that settle before pressing one. ("Card 1 of 2" can be on
  // screen a tick before the listener is, and a key pressed then is lost.)
  await act(async () => {});
  act(() => { flip(); });
  await waitFor(() => expect(screen.getByTitle(/\(press 3\)/)).toBeEnabled());
};

describe("Flashcards — review session state (#769)", () => {
  beforeEach(() => {
    mockedCourses.mockResolvedValue({ courses: [course("c1", "CS101", "Intro to CS")] });
    mockedGraph.mockResolvedValue({ nodes: [node("n1", "Bio"), node("n2", "Chem")], edges: [], stats: {} });
    mockedCards.mockResolvedValue({ flashcards: [card("a"), card("b")] });
    // The hub's "Flashcards" on a concept: straight into its review.
    arriveAt("course=c1&concepts=Bio&start=1");
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

  it("the same review, entered through the builder's Start", async () => {
    arriveAt("course=c1");
    mockedRate.mockResolvedValue({ ok: true });
    renderFlashcards();
    // The home, not a card; then the builder.
    await openBuilder();
    await userEvent.click(await screen.findByRole("checkbox", { name: /^Bio/ }));
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await screen.findByText("Card 1 of 2");

    await flipCard();
    act(() => { press("3"); press("3"); });
    expect(await screen.findByText("Card 2 of 2")).toBeTruthy();
    expect(mockedRate).toHaveBeenCalledTimes(1);
    await flipCard();
    await act(async () => { press("3"); });
    expect(await screen.findByText("Deck complete")).toBeTruthy();
  });

  it("the rating keys do nothing while typing a set's name in the builder", async () => {
    arriveAt("course=c1");
    renderFlashcards();
    await openBuilder();
    await screen.findByRole("checkbox", { name: /^Bio/ });
    const name = screen.getByRole("textbox", { name: "Set name" });

    await userEvent.type(name, "Week 3 1 2");

    expect(name).toHaveValue("Week 3 1 2");
    expect(mockedRate).not.toHaveBeenCalled();
  });

  it("deleting a card drops it from the deck and starts the deck over", async () => {
    mockedRate.mockResolvedValue({ ok: true });
    mockedDelete.mockResolvedValue({ ok: true });
    renderFlashcards();
    await screen.findByText("Card 1 of 2");
    await flipCard();
    await act(async () => { press("3"); });
    await screen.findByText("Card 2 of 2");

    await userEvent.click(screen.getByRole("button", { name: /delete card/i }));

    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    expect(mockedDelete).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Card deleted")).toBeTruthy();
  });

  it("generating for a selected course sends that course's id (#829)", async () => {
    // Chem has no cards: Start makes them, for that concept, on that course.
    arriveAt("course=c1");
    mockedGenerate.mockResolvedValue({ flashcards: [card("n", "Chem")], context_used: { documents_found: 2, weak_concepts_found: 0 } });
    renderFlashcards();
    await openBuilder();
    await userEvent.click(await screen.findByRole("checkbox", { name: /^Chem/ }));
    mockedCards.mockResolvedValue({ flashcards: [card("a"), card("b"), card("n", "Chem")] });
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
    expect(mockedGenerate).toHaveBeenCalledTimes(1);
    expect(mockedGenerate).toHaveBeenCalledWith("u1", "Chem", 5, undefined, "c1");
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
  });

  it("a link with no course sends no course id (#829)", async () => {
    // A student with no courses, sent to a topic: generation is by name only.
    mockedCourses.mockResolvedValue({ courses: [] });
    mockedCards.mockResolvedValueOnce({ flashcards: [] });
    mockedGenerate.mockResolvedValue({ flashcards: [card("n")], context_used: { documents_found: 0, weak_concepts_found: 0 } });
    arriveAt("concepts=Bio&start=1");
    renderFlashcards();

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
    expect(mockedGenerate).toHaveBeenCalledWith("u1", "Bio", 5, undefined, undefined);
  });

  it("cards are generated BEFORE the review, which then starts at its first card", async () => {
    // Bio has two cards, Chem none. The review waits for Chem's cards and
    // opens on card 1 of all three; nothing is generated once it is open.
    arriveAt("course=c1&concepts=Bio|Chem&start=1");
    const pending = deferred<{ flashcards: ReturnType<typeof card>[] }>();
    mockedGenerate.mockReturnValue(pending.promise);
    renderFlashcards();

    expect(await screen.findByText("Making cards for Chem…")).toBeTruthy();
    expect(screen.queryByText(/Card \d of/)).toBeNull();
    mockedCards.mockResolvedValue({ flashcards: [card("n", "Chem"), card("a"), card("b")] });
    await act(async () => { pending.resolve({ flashcards: [card("n", "Chem")] }); });

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(mockedGenerate).toHaveBeenCalledTimes(1);
    expect(mockedGenerate).toHaveBeenCalledWith("u1", "Chem", 5, undefined, "c1");
    expect(screen.queryByRole("button", { name: /generate cards/i })).toBeNull();
  });
});
