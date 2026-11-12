// @vitest-environment jsdom
/**
 * The Flashcards HOME, through the page: the hero prompt, the decks, the mix
 * bar, and the Study hub's deep links.
 *
 * The builder the home opens is pinned in SetBuilder.test.tsx; the pure rules
 * are in decksModel.test.ts and flashcardsModel.test.ts.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, cleanup, waitFor, within, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

// The student's nav flags (#620): nothing hidden unless a spec says so.
const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));

vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: () => null,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(),
  getFlashcards: vi.fn(),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(),
  getGraph: vi.fn(),
  getAllAssignments: vi.fn(),
}));

vi.mock("@/lib/topicChecklistApi", () => ({
  getTopicChecklist: vi.fn(),
}));

// The real module's constants (the description's length limits) with every
// call mocked.
vi.mock("@/lib/flashcardSetsApi", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/flashcardSetsApi")>()),
  listFlashcardSets: vi.fn(),
  createFlashcardSet: vi.fn(),
  updateFlashcardSet: vi.fn(),
  deleteFlashcardSet: vi.fn(),
  suggestFlashcardSet: vi.fn(),
}));

import type { getGraph } from "@/lib/api";
import type { FlashcardSetSuggestion } from "@/lib/flashcardSetsApi";
import type { TopicChecklist } from "@/lib/topicChecklistApi";
import {
  CARDS,
  CARDS_NO_DUE,
  COURSE,
  EDGES,
  EXAM,
  NODES,
  POINTERS_SET,
  arriveAt,
  card,
  deck,
  deferred,
  figure,
  findTile,
  generated,
  home,
  homeStatus,
  mocks,
  renderPage,
  resetMocks,
  savedSet,
  selection,
  suggestion,
  ticked,
} from "./pageTestKit";

beforeEach(() => {
  resetMocks();
  flagState.flags = {};
});

afterEach(() => {
  cleanup();
  arriveAt("");
  vi.restoreAllMocks();
});

const VARS_SET = savedSet({ id: "s3", name: "Vars and recursion", concepts: ["Variables", "Recursion"], options: { only_due: false, shuffle: true }, exam_id: null });
/** The decks' ids in grid order (a deck is the list item; its parts have testids of their own). */
const deckIds = () => [...document.querySelectorAll("li[data-testid^='flashcards-deck-']")].map(el => el.getAttribute("data-testid")!.replace("flashcards-deck-", ""));
const mastery = (id: string) =>
  [...within(deck(id)).getByTestId("flashcards-mastery").querySelectorAll("i")].map(i => `${i.getAttribute("data-kind")} ${i.style.width}`);
const legend = (id: string) => within(deck(id)).getByTestId("flashcards-deck-legend").textContent;
const peek = (id: string) => [...within(deck(id)).getByTestId("flashcards-deck-peek").children].map(el => el.textContent);
const fact = (id: string) => within(deck(id)).getByTestId("flashcards-deck-fact").textContent;
const mixBar = () => screen.queryByTestId("flashcards-mix");
const homeStatusOrNull = () => screen.queryByTestId("flashcards-home-status");
const describeField = () => screen.getByRole("textbox", { name: "Describe a set" });
const sortIt = () => screen.getByRole("button", { name: /Sort it|Sorting…/ });

// ── the hero ──────────────────────────────────────────────────────────────

describe("Flashcards home: the hero", () => {
  it("opens on the prompt and the decks: no card, no concept grid, no tray", async () => {
    await home();

    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /^Variables/ })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Your selection" })).toBeNull();
    // Cards in this course (the sixth is another course's), everything on its
    // map (the course's concepts plus a card topic that is not one, the same
    // count the "All of" deck shows), sets.
    expect([figure("cards"), figure("concepts"), figure("sets")]).toEqual(["5", "6", "0"]);
  });

  it("the header keeps the course field (no all-courses row) and Import, and has no Generate button", async () => {
    const user = await home();
    expect(screen.queryByRole("button", { name: /generate cards/i })).toBeNull();
    expect(screen.getByRole("button", { name: /Import/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /^CS101/ }));
    expect(screen.queryByRole("option", { name: /All courses/ })).toBeNull();
    expect(screen.getByRole("option", { name: /CS101/ })).toBeTruthy();
  });

  it("offers example prompts made from the course; tapping one fills the field and asks nothing", async () => {
    const user = await home();
    const ideas = ["Everything on Midterm 2", "What I'm struggling with", "Just the basics"];
    for (const idea of ideas) expect(screen.getByRole("button", { name: idea })).toBeTruthy();
    // The map's columns are the fallback layers here, not the course's units.
    expect(screen.queryByRole("button", { name: /from scratch/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Everything on Midterm 2" }));
    expect(describeField()).toHaveValue("Everything on Midterm 2");
    expect(describeField()).toHaveFocus();
    expect(mocks.suggest).not.toHaveBeenCalled();
    expect(sortIt()).toBeEnabled();
  });

  it("names the course's first unit in an example when the outline gives the map units", async () => {
    mocks.checklist.mockResolvedValue({
      topics: [
        { id: "u1", name: "Memory and Data", parent_id: null, node_id: null },
        { id: "t3", name: "Sorting", parent_id: "u1", node_id: "n3" },
        { id: "t4", name: "Pointers", parent_id: "u1", node_id: "n4" },
        { id: "t5", name: "Trees", parent_id: "u1", node_id: "n5" },
      ],
    } as unknown as TopicChecklist);
    await home();
    expect(screen.getByRole("button", { name: "Memory and Data from scratch" })).toBeTruthy();
  });

  it("Sort it opens the builder with the described concepts ticked, named, and says what it did", async () => {
    mocks.suggest.mockResolvedValue(suggestion());
    const user = await home();

    await user.type(describeField(), "  pointers and recursion for the midterm  ");
    await user.click(sortIt());

    // Trimmed, and always for the course the page is on.
    await waitFor(() => expect(mocks.suggest).toHaveBeenCalledWith("u1", "pointers and recursion for the midterm", "c1"));
    await findTile("Variables");
    // Exactly the returned concepts the map has, under the map's spelling;
    // "Dynamic Programming" is not on this map.
    expect(ticked()).toEqual(["Pointers", "Recursion"]);
    expect(screen.queryByRole("checkbox", { name: /^Dynamic Programming/ })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("Midterm: pointers and recursion");
    expect(screen.getByTestId("flashcards-build-note").textContent).toBe("Sorted 2 of 5 concepts into this set. Tick or untick to adjust, then save.");
    // A described selection is a new set, not a loaded one.
    expect(screen.getByRole("button", { name: "Save set" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Update set" })).toBeNull();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("New set");
    expect(selection()).toBe("2 concepts · 2 cards");
  });

  it("Enter submits; the button reads Sorting… and is disabled while it works", async () => {
    const pending = deferred<FlashcardSetSuggestion>();
    mocks.suggest.mockReturnValue(pending.promise);
    const user = await home();

    await user.type(describeField(), "recursion{Enter}");
    expect(await screen.findByRole("button", { name: "Sorting…" })).toBeDisabled();
    // A second Enter while it works asks nothing more.
    await user.type(describeField(), "{Enter}");
    expect(mocks.suggest).toHaveBeenCalledTimes(1);

    pending.resolve(suggestion());
    await findTile("Variables");
    expect(ticked()).toEqual(["Pointers", "Recursion"]);
  });

  it("does not ask for under three characters, and caps the description at 300", async () => {
    mocks.suggest.mockResolvedValue(suggestion({ concepts: [] }));
    const user = await home();

    expect(sortIt()).toBeDisabled();
    await user.type(describeField(), " ab {Enter}");
    expect(sortIt()).toBeDisabled();
    expect(mocks.suggest).not.toHaveBeenCalled();

    await user.clear(describeField());
    await user.click(describeField());
    await user.paste("x".repeat(400));
    expect((describeField() as HTMLInputElement).value).toHaveLength(300);
    await user.click(sortIt());
    await waitFor(() => expect(mocks.suggest).toHaveBeenCalledTimes(1));
    expect(mocks.suggest.mock.calls[0][1]).toHaveLength(300);
  });

  it("stays on the home and says so under the field when nothing matched", async () => {
    mocks.suggest.mockResolvedValue(suggestion({ name: "Organic chemistry", concepts: [{ name: "Alkenes", course_id: null, source: "model", confidence: 0.4 }] }));
    const user = await home();

    await user.type(describeField(), "organic chemistry");
    await user.click(sortIt());

    expect(await screen.findByText(/Nothing on this course's map matched that/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /^Variables/ })).toBeNull();
    expect(describeField()).toHaveValue("organic chemistry");
    expect(sortIt()).toBeEnabled();
  });

  it("a 429 is a toast, and the student stays on the home", async () => {
    mocks.suggest.mockRejectedValue(Object.assign(new Error("HTTP 429"), { status: 429 }));
    const user = await home();
    await user.type(describeField(), "recursion please");
    await user.click(sortIt());

    expect(await screen.findByText("Too many requests right now. Wait a moment and try again.")).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /^Variables/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Sort it" })).toBeEnabled();
  });

  it("a 422 shows the server's reason", async () => {
    mocks.suggest.mockRejectedValue(Object.assign(new Error(JSON.stringify({ detail: "Describe the set in 3 to 300 characters." })), { status: 422 }));
    const user = await home();
    await user.type(describeField(), "abc");
    await user.click(sortIt());
    expect(await screen.findByText("Describe the set in 3 to 300 characters.")).toBeTruthy();
  });
});

// ── decks ─────────────────────────────────────────────────────────────────

describe("Flashcards home: decks", () => {
  beforeEach(() => {
    // Due dates are not tracked today; the due deck has its own suite below.
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
  });

  it("shows each saved set as a deck: name, counts, mastery, the exam it is for", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet(), POINTERS_SET] });
    await home();

    const midterm = within(deck("s1"));
    expect(midterm.getByText("Midterm crunch")).toBeTruthy();
    expect(midterm.getByText("3 concepts · 3 cards")).toBeTruthy();
    // The exam it is for, as the pill on its band.
    expect(midterm.getByTestId("flashcards-deck-tag").textContent).toBe("Midterm 2");
    // Variables is mastered, Recursion struggling; "Graphs" is not a course
    // concept, so a third of the track shows through and it is not listed.
    expect(mastery("s1")).toEqual(["mastered 33%", "struggling 33%"]);
    expect(midterm.getByRole("img", { name: "Mastery: 1 mastered, 1 struggling" })).toBeTruthy();
    expect(legend("s1")).toBe("1 mastered1 struggling");

    const pointers = within(deck("s2"));
    expect(pointers.getByText("1 concept · 1 card")).toBeTruthy();
    expect(pointers.queryByTestId("flashcards-deck-tag")).toBeNull();
    expect(mastery("s2")).toEqual(["learning 100%"]);
    expect(legend("s2")).toBe("1 learning");
    expect(figure("sets")).toBe("2");
    expect(screen.getByText("Tick sets to study them together")).toBeTruthy();
  });

  it("peeks at what is in a deck: a few concept chips, then how many more", async () => {
    mocks.sets.mockResolvedValue({ sets: [
      savedSet(),
      POINTERS_SET,
      savedSet({ id: "s5", name: "Long ones", concepts: ["Pointers", "A concept with a very long name", "Trees", "Sorting"], exam_id: null }),
    ] });
    await home();

    expect(peek("s1")).toEqual(["Variables", "Recursion", "Graphs"]);
    expect(peek("s2")).toEqual(["Pointers"]);
    // The long name does not fit beside the first: it and the rest are counted.
    expect(peek("s5")).toEqual(["Pointers", "+3"]);
    // Five concepts and the "CS Basics" deck in everything: three shown.
    expect(peek("auto:all")).toEqual(["Pointers", "Sorting", "Trees", "+3"]);
  });

  it("the foot of a deck says one real thing: the exam's countdown, else what needs cards, else nothing", async () => {
    const soon = { id: "e2", user_id: "u1", title: "Quiz 4", due_date: "2026-11-15", assignment_type: "quiz", course_id: "c1" };
    const past = { id: "e0", user_id: "u1", title: "Midterm 1", due_date: "2026-10-01", assignment_type: "exam", course_id: "c1" };
    mocks.assignments.mockResolvedValue({ assignments: [EXAM, soon, past] });
    mocks.sets.mockResolvedValue({ sets: [
      savedSet(),
      savedSet({ id: "s5", name: "Quiz prep", concepts: ["Sorting"], exam_id: "e2" }),
      savedSet({ id: "s6", name: "Old exam, new gaps", concepts: ["Pointers", "Sorting", "Trees"], exam_id: "e0" }),
      savedSet({ id: "s7", name: "One gap", concepts: ["Variables", "Trees"], exam_id: null }),
      POINTERS_SET,
    ] });
    await home();

    // Nine days to its exam (that outranks "Graphs" having no cards).
    expect(fact("s1")).toBe("Exam in 9 days");
    // Three days: within the week, so it is flagged.
    expect(fact("s5")).toBe("Exam in 3 days");
    expect(within(deck("s5")).getByTestId("flashcards-deck-fact").className).not.toBe(within(deck("s1")).getByTestId("flashcards-deck-fact").className);
    // Its exam is behind it: the next real fact.
    expect(fact("s6")).toBe("2 concepts need cards");
    expect(within(deck("s6")).getByTestId("flashcards-deck-tag").textContent).toBe("Midterm 1");
    expect(fact("s7")).toBe("1 concept needs cards");
    // Nothing to say: nothing said.
    expect(fact("s2")).toBe("");
    expect(fact("auto:all")).toBe("2 concepts need cards");
  });

  it("every part of a deck is a named control", async () => {
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET] });
    await home();
    const d = within(deck("s2"));
    expect(d.getByRole("button", { name: "Open Pointers only" })).toBeTruthy();
    expect(d.getByRole("button", { name: "Review Pointers only" })).toBeTruthy();
    expect(d.getByRole("checkbox", { name: "Select Pointers only" })).toBeTruthy();
    expect(d.getByRole("button", { name: "More for Pointers only" })).toBeTruthy();
  });

  it("sets take the colours in the order they were made; everything is always olive", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet(), POINTERS_SET] });
    await home();
    const first = [deck("s1").getAttribute("data-palette"), deck("s2").getAttribute("data-palette")];
    expect(first).toEqual(["blue", "amber"]);
    expect(deck("auto:all").getAttribute("data-palette")).toBe("green");

    // Another visit, the list in another order: the same colours.
    cleanup();
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET, savedSet()] });
    renderPage();
    await screen.findByTestId("flashcards-deck-s1");
    expect([deck("s1").getAttribute("data-palette"), deck("s2").getAttribute("data-palette")]).toEqual(first);
  });

  it("a reload inside a review comes back to the same card of the same deck", async () => {
    mocks.sets.mockResolvedValue({ sets: [VARS_SET, POINTERS_SET] });
    const user = await home();
    await user.click(screen.getByRole("button", { name: "Review Vars and recursion" }));
    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    act(() => { fireEvent.keyDown(window, { key: "ArrowRight", code: "ArrowRight" }); });
    expect(screen.getByText("Card 2 of 3")).toBeTruthy();
    const second = screen.getByTestId("flashcards-card").textContent;
    // The URL says a review is open (and still names nothing else new).
    expect(new URLSearchParams(window.location.search).get("review")).toBe("1");

    // The reload: a fresh page on the URL as it stands.
    cleanup();
    renderPage();

    expect(await screen.findByText("Card 2 of 3")).toBeTruthy();
    expect(screen.getByTestId("flashcards-card").textContent).toBe(second);
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Vars and recursion");
    expect(mocks.generate).not.toHaveBeenCalled();

    // Leaving it is leaving it: the home, and a reload there stays home.
    await userEvent.click(screen.getByRole("button", { name: "All sets" }));
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(new URLSearchParams(window.location.search).has("review")).toBe(false);
    cleanup();
    renderPage();
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByText(/Card \d+ of/)).toBeNull();
  });

  it("a review marker with nothing kept behind it (another tab, a shared link) opens the home", async () => {
    arriveAt("course=c1&review=1");
    renderPage();
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(new URLSearchParams(window.location.search).has("review")).toBe(false);
  });

  /** Opens the "Vars and recursion" review, then drops the page as a reload does. */
  const reloadInsideReview = async () => {
    mocks.sets.mockResolvedValue({ sets: [VARS_SET, POINTERS_SET] });
    const user = await home();
    await user.click(screen.getByRole("button", { name: "Review Vars and recursion" }));
    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    cleanup();
  };

  it("a reload inside a review waits for the course list: the cards answering first does not lose it", async () => {
    // The URL of a review opened from a bare /flashcards names no course, and
    // the review is kept under the course it was started on.
    await reloadInsideReview();
    const courses = deferred<{ courses: (typeof COURSE)[] }>();
    mocks.courses.mockReturnValue(courses.promise);
    renderPage();

    await waitFor(() => expect(mocks.cards).toHaveBeenCalledTimes(2));
    await act(async () => {});
    expect(screen.queryByRole("heading", { name: "What do you want to study?" })).toBeNull();
    expect(new URLSearchParams(window.location.search).get("review")).toBe("1");

    await act(async () => { courses.resolve({ courses: [COURSE] }); });
    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Vars and recursion");
  });

  it("a reload inside a review whose card list fails keeps the review for the retry", async () => {
    await reloadInsideReview();
    mocks.cards.mockRejectedValueOnce(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Couldn't load your flashcards")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("review")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Vars and recursion");
  });

  it("play reviews the set's cards right away, and All sets comes back to the home", async () => {
    mocks.sets.mockResolvedValue({ sets: [VARS_SET, POINTERS_SET] });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "Review Vars and recursion" }));

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Vars and recursion");
    expect(mocks.generate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "All sets" }));
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(deck("s3")).toBeTruthy();
  });

  it("play makes cards for the set's concepts that have none first, and says which", async () => {
    const pending = deferred<ReturnType<typeof generated>>();
    mocks.generate.mockReturnValue(pending.promise);
    mocks.sets.mockResolvedValue({ sets: [savedSet({ id: "s6", name: "Pointers and sorting", concepts: ["Pointers", "Sorting"], options: { only_due: false, shuffle: true }, exam_id: null })] });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "Review Pointers and sorting" }));

    await waitFor(() => expect(homeStatus()).toBe("Making cards for Sorting… 1 of 1"));
    expect(mocks.generate).toHaveBeenCalledWith("u1", "Sorting", 5, undefined, "c1");
    expect(deck("s6").hasAttribute("data-busy")).toBe(true);
    // Nothing else can be started meanwhile.
    expect(screen.getByRole("button", { name: "Review All of CS101" })).toBeDisabled();

    const made = [card("g1", "Sorting", { course_id: null })];
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS_NO_DUE, ...made] });
    pending.resolve(generated(made));

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(1);
  });

  it("a play that ends with nothing to review stays on the home and says why", async () => {
    mocks.generate.mockRejectedValue(new Error("boom"));
    mocks.sets.mockResolvedValue({ sets: [savedSet({ id: "s6", name: "Just sorting", concepts: ["Sorting"], exam_id: null })] });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "Review Just sorting" }));

    await waitFor(() => expect(homeStatus()).toMatch(/No cards could be made for this selection/));
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    expect(screen.getByRole("button", { name: "Review Just sorting" })).toBeEnabled();
  });

  it("the deck's body, or Edit in its menu, opens the builder with the set loaded", async () => {
    mocks.sets.mockResolvedValue({ sets: [VARS_SET] });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "More for Vars and recursion" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    await findTile("Variables");
    expect(ticked()).toEqual(["Variables", "Recursion"]);
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("Vars and recursion");
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Vars and recursion");

    await user.click(screen.getByRole("button", { name: "All sets" }));
    await user.click(await screen.findByRole("button", { name: "Open Vars and recursion" }));
    await findTile("Variables");
    expect(ticked()).toEqual(["Variables", "Recursion"]);
  });

  it("renames a set from its menu", async () => {
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET] });
    mocks.update.mockResolvedValue({ set: { ...POINTERS_SET, name: "Memory" } });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "More for Pointers only" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename set" });
    await user.clear(input);
    await user.type(input, "Memory{Enter}");

    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("u1", "s2", { name: "Memory" }));
    expect(await within(deck("s2")).findByText("Memory")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Review Memory" })).toBeTruthy();
  });

  it("a set write that answers after a course switch leaves the new course's home up", async () => {
    const other = { ...COURSE, enrollment_id: "enr-c0", course_id: "c0", course_code: "MA123", course_name: "Calculus" };
    mocks.courses.mockResolvedValue({ courses: [COURSE, other] });
    mocks.sets.mockImplementation(async (_user, courseId) => ({ sets: courseId === "c1" ? [POINTERS_SET] : [] }));
    const renamed = deferred<{ set: typeof POINTERS_SET }>();
    mocks.update.mockReturnValue(renamed.promise);
    const user = await home();

    await user.click(screen.getByRole("button", { name: "More for Pointers only" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename set" });
    await user.clear(input);
    await user.type(input, "Memory{Enter}");
    await waitFor(() => expect(mocks.update).toHaveBeenCalled());

    // On to the other course (no concepts there), whose own list lands first.
    await user.click(screen.getByRole("button", { name: /CS101/, expanded: false }));
    await user.click(screen.getByRole("option", { name: /MA123/ }));
    expect(await screen.findByText(/No concepts for this course yet/)).toBeTruthy();
    await waitFor(() => expect(mocks.sets).toHaveBeenCalledWith("u1", "c0"));

    await act(async () => { renamed.resolve({ set: { ...POINTERS_SET, name: "Memory" } }); });
    expect(screen.queryByTestId("flashcards-home-loading")).toBeNull();
    expect(screen.getByText(/No concepts for this course yet/)).toBeTruthy();
  });

  it("deletes a set only after a second, confirming click", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet(), POINTERS_SET] });
    mocks.remove.mockResolvedValue({ deleted: true });
    const user = await home();
    await user.click(screen.getByRole("checkbox", { name: "Select Pointers only" }));
    expect(mixBar()).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "More for Pointers only" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(mocks.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("menuitem", { name: "Click again to delete" }));

    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith("u1", "s2"));
    await waitFor(() => expect(screen.queryByTestId("flashcards-deck-s2")).toBeNull());
    expect(deck("s1")).toBeTruthy();
    // It was ticked: the mix bar goes with it.
    expect(mixBar()).toBeNull();
  });

  it("the last cell builds a set by hand: the builder, with nothing ticked", async () => {
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET] });
    const user = await home();
    expect(deckIds()).toEqual(["auto:all", "s2"]);

    await user.click(screen.getByRole("button", { name: /Build one by hand/ }));

    await findTile("Variables");
    expect(ticked()).toEqual([]);
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("New set");
    expect(selection()).toBe("Nothing ticked yet");
  });
});

// ── the automatic decks ───────────────────────────────────────────────────

describe("Flashcards home: the automatic decks", () => {
  it("All of the course comes first: everything on the map, not stored, playable and tickable", async () => {
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET] });
    const user = await home();

    expect(deckIds()[0]).toBe("auto:all");
    const all = within(deck("auto:all"));
    expect(all.getByText("All of CS101")).toBeTruthy();
    expect(all.getByTestId("flashcards-deck-tag").textContent).toBe("everything");
    // Five concepts and the "CS Basics" deck; five cards.
    expect(all.getByText("6 concepts · 5 cards")).toBeTruthy();
    expect(mastery("auto:all")).toEqual(["mastered 17%", "learning 17%", "struggling 17%"]);
    expect(legend("auto:all")).toBe("1 mastered1 learning1 struggling");
    // Not a saved set: nothing to open, rename or delete.
    expect(all.queryByRole("button", { name: /^Open/ })).toBeNull();
    expect(all.queryByRole("button", { name: /^More for/ })).toBeNull();
    expect(all.getByRole("checkbox", { name: "Select All of CS101" })).toBeTruthy();

    // Playing it reviews what exists. It never generates: Sorting and Trees
    // have no cards, and one press must not pay to make a whole course's.
    await user.click(all.getByRole("button", { name: "Review All of CS101" }));
    expect(await screen.findByText("Card 1 of 5")).toBeTruthy();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it("Due today exists only when cards carry due dates, and plays the due cards", async () => {
    const user = await home();

    expect(deckIds()).toEqual(["auto:due", "auto:all"]);
    const due = within(deck("auto:due"));
    expect(due.getByText("Due today")).toBeTruthy();
    expect(due.getByTestId("flashcards-deck-tag").textContent).toBe("due");
    expect(deck("auto:due").getAttribute("data-palette")).toBe("clay");
    // What is due, at a glance.
    expect(peek("auto:due")).toEqual(["Variables", "Recursion"]);
    // x1 is due too, but in another course.
    expect(due.getByText("2 cards")).toBeTruthy();
    // It is cards, not concepts: nothing to mix it with.
    expect(due.queryByRole("checkbox")).toBeNull();

    await user.click(due.getByRole("button", { name: "Review Due today" }));
    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Due today");
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it("with no due dates there is no due deck and no due figure anywhere", async () => {
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    mocks.sets.mockResolvedValue({ sets: [savedSet()] });
    await home();

    expect(deckIds()).toEqual(["auto:all", "s1"]);
    expect(screen.queryByText(/\bdue\b/i)).toBeNull();
    expect(within(deck("s1")).getByText("3 concepts · 3 cards")).toBeTruthy();
  });

  it("a set saved to review only what's due plays all its cards while due dates are not tracked", async () => {
    // `due_at` is null on every card today: the option cannot be seen or
    // changed, so it must not turn the set's review into an empty one.
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    mocks.sets.mockResolvedValue({ sets: [savedSet({ concepts: ["Variables", "Recursion"], options: { only_due: true, shuffle: false } })] });
    const user = await home();

    expect(within(deck("s1")).getByText("2 concepts · 3 cards")).toBeTruthy();
    expect(deck("s1").textContent).not.toMatch(/due/i);
    await user.click(screen.getByRole("button", { name: "Review Midterm crunch" }));

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(homeStatusOrNull()).toBeNull();
  });

  it("a set saved to review only what's due plays only that", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet()] });
    const user = await home();
    expect(within(deck("s1")).getByText("3 concepts · 3 cards · 2 due")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Review Midterm crunch" }));

    // v1 and r1 are due; "Graphs" has no cards, and only-due never generates.
    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mocks.generate).not.toHaveBeenCalled();
  });
});

// ── mixing ────────────────────────────────────────────────────────────────

describe("Flashcards home: ticking decks and the mix bar", () => {
  beforeEach(() => {
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    mocks.sets.mockResolvedValue({ sets: [VARS_SET, POINTERS_SET] });
  });

  it("one ticked deck brings up the bar with Study and Clear", async () => {
    const user = await home();
    expect(mixBar()).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: "Select Pointers only" }));

    const bar = within(mixBar()!);
    expect(bar.getByRole("status").textContent).toBe("1 set · 1 card");
    expect(bar.queryByRole("button", { name: "Merge into one" })).toBeNull();
    expect(bar.queryByRole("button", { name: "Study together" })).toBeNull();

    await user.click(bar.getByRole("button", { name: "Study" }));
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Pointers only");
  });

  it("Study together reviews the union of the ticked sets' concepts", async () => {
    const user = await home();
    await user.click(screen.getByRole("checkbox", { name: "Select Pointers only" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Vars and recursion" }));

    const bar = within(mixBar()!);
    expect(bar.getByRole("status").textContent).toBe("2 sets · 4 cards");
    await user.click(bar.getByRole("button", { name: "Study together" }));

    expect(await screen.findByText("Card 1 of 4")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("2 sets together");
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it("a concept two ticked sets share is counted and reviewed once", async () => {
    mocks.sets.mockResolvedValue({ sets: [VARS_SET, savedSet({ id: "s8", name: "Variables again", concepts: ["variables", "Pointers"], exam_id: null })] });
    const user = await home();
    await user.click(screen.getByRole("checkbox", { name: "Select Vars and recursion" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Variables again" }));

    expect(within(mixBar()!).getByRole("status").textContent).toBe("2 sets · 4 cards");
    await user.click(screen.getByRole("button", { name: "Study together" }));
    expect(await screen.findByText("Card 1 of 4")).toBeTruthy();
  });

  it("mixing in the everything deck makes cards only for the saved sets' own concepts", async () => {
    const made = [card("g1", "Sorting", { course_id: null })];
    mocks.generate.mockResolvedValue(generated(made));
    mocks.sets.mockResolvedValue({ sets: [savedSet({ id: "s6", name: "Just sorting", concepts: ["Sorting"], exam_id: null })] });
    const user = await home();
    await user.click(screen.getByRole("checkbox", { name: "Select All of CS101" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Just sorting" }));
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS_NO_DUE, ...made] });

    await user.click(screen.getByRole("button", { name: "Study together" }));

    // Sorting is the set's, so it is made; Trees is only in "everything".
    expect(await screen.findByText("Card 1 of 6")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(1);
    expect(mocks.generate).toHaveBeenCalledWith("u1", "Sorting", 5, undefined, "c1");
  });

  it("Merge into one opens the builder with the union ticked, unnamed and attached to no set", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet({ exam_id: null }), POINTERS_SET] });
    const user = await home();
    await user.click(screen.getByRole("checkbox", { name: "Select Midterm crunch" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Pointers only" }));

    await user.click(screen.getByRole("button", { name: "Merge into one" }));

    await findTile("Variables");
    // "Graphs" is the first set's own concept: it comes along.
    expect(ticked()).toEqual(["Pointers", "Variables", "Recursion", "Graphs"]);
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("");
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("New set");
    expect(screen.queryByRole("button", { name: "Update set" })).toBeNull();

    // Naming it saves a NEW set; neither original is touched.
    mocks.create.mockResolvedValue({ set: savedSet({ id: "s9", name: "Both", concepts: ["Variables", "Recursion", "Graphs", "Pointers"], exam_id: null }) });
    await user.type(screen.getByRole("textbox", { name: "Set name" }), "Both");
    await user.click(screen.getByRole("button", { name: "Save set" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create.mock.calls[0][1]).toMatchObject({ name: "Both", concepts: ["Variables", "Recursion", "Graphs", "Pointers"] });
    expect(mocks.update).not.toHaveBeenCalled();
    expect(await screen.findByTestId("flashcards-deck-s9")).toBeTruthy();
  });

  it("Clear unticks every deck and puts the bar away", async () => {
    const user = await home();
    const a = screen.getByRole("checkbox", { name: "Select Pointers only" });
    const b = screen.getByRole("checkbox", { name: "Select Vars and recursion" });
    await user.click(a);
    await user.click(b);

    await user.click(within(mixBar()!).getByRole("button", { name: "Clear" }));

    expect(mixBar()).toBeNull();
    expect(a).not.toBeChecked();
    expect(b).not.toBeChecked();
  });

  it("unticking the last ticked deck puts the bar away too", async () => {
    const user = await home();
    const a = screen.getByRole("checkbox", { name: "Select Pointers only" });
    await user.click(a);
    expect(mixBar()).toBeTruthy();
    await user.click(a);
    expect(mixBar()).toBeNull();
  });
});

// ── loading, failure, nothing to show ─────────────────────────────────────

describe("Flashcards home: loading, failing and empty", () => {
  it("shows the hero with blank figures and deck placeholders while it loads", async () => {
    const pending = deferred<{ flashcards: typeof CARDS }>();
    mocks.cards.mockReturnValue(pending.promise);
    renderPage();

    const loading = await screen.findByTestId("flashcards-home-loading");
    expect(within(loading).getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect([figure("cards"), figure("concepts"), figure("sets")]).toEqual(["–", "–", "–"]);
    expect(sortIt()).toBeDisabled();

    pending.resolve({ flashcards: CARDS });
    await screen.findByTestId("flashcards-home-status");
    expect(figure("cards")).toBe("5");
  });

  it("a sets list that fails to load still shows the hero, the automatic deck and the build tile", async () => {
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    mocks.sets.mockRejectedValue(new Error("boom"));
    const user = await home();

    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(deckIds()).toEqual(["auto:all"]);
    expect(figure("sets")).toBe("0");
    await user.click(screen.getByRole("button", { name: /Build one by hand/ }));
    await findTile("Variables");
  });

  it("a course with no concepts: the hero, a line pointing to the Library, and no decks", async () => {
    mocks.graph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
    mocks.cards.mockResolvedValue({ flashcards: [] });
    renderPage();

    expect(await screen.findByText(/No concepts for this course yet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Library" }).getAttribute("href")).toBe("/library");
    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByTestId(/^flashcards-deck-/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Build one by hand/ })).toBeNull();
    // Nothing to sort a description into.
    expect(describeField()).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Just the basics" })).toBeNull();
    expect([figure("cards"), figure("concepts"), figure("sets")]).toEqual(["0", "0", "0"]);
  });

  it("with the Library hidden from this student, the empty home does not link to it", async () => {
    flagState.flags = { hide_library: "on" };
    mocks.graph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
    mocks.cards.mockResolvedValue({ flashcards: [] });
    renderPage();

    expect(await screen.findByText(/No concepts for this course yet/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Library" })).toBeNull();
    expect(screen.getByTestId("flashcards-no-concepts").textContent).not.toMatch(/Library/);

    // The same for a student with no course at all.
    cleanup();
    mocks.courses.mockResolvedValue({ courses: [] });
    renderPage();
    expect(await screen.findByText(/Add a course to make flashcards for it/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Library" })).toBeNull();
  });

  it("a student with no courses gets the hero and the way to the Library", async () => {
    mocks.courses.mockResolvedValue({ courses: [] });
    mocks.cards.mockResolvedValue({ flashcards: [] });
    renderPage();

    expect(await screen.findByText(/Add a course to make flashcards for it/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByTestId(/^flashcards-deck-/)).toBeNull();
    expect(mocks.sets).not.toHaveBeenCalled();
  });

  it("a course list that fails to load says so (not 'add a course'), and Try again loads it", async () => {
    mocks.courses.mockRejectedValueOnce(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Couldn't load your flashcards")).toBeTruthy();
    expect(screen.queryByText(/Add a course to make flashcards for it/)).toBeNull();
    expect(screen.queryByTestId(/^flashcards-deck-/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await within(await screen.findByTestId("flashcards-deck-auto:all")).findByText("All of CS101")).toBeTruthy();
    expect(mocks.courses).toHaveBeenCalledTimes(2);
    // Only what failed is read again.
    expect(mocks.cards).toHaveBeenCalledTimes(1);
  });

  it("start=1 survives a course list that fails first: the retry starts what the link asked for", async () => {
    mocks.courses.mockRejectedValueOnce(new Error("boom"));
    arriveAt("course=c1&concepts=Variables|Recursion&start=1");
    renderPage();

    expect(await screen.findByText("Couldn't load your flashcards")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("start")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("start")).toBeNull();
  });

  it("does not offer decks over a card list it could not read", async () => {
    mocks.cards.mockRejectedValueOnce(new Error("boom"));
    renderPage();

    expect(await screen.findByText("Couldn't load your flashcards")).toBeTruthy();
    expect(screen.queryByTestId(/^flashcards-deck-/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("flashcards-deck-auto:all")).toBeTruthy();
  });
});

// ── deep links ────────────────────────────────────────────────────────────

describe("Flashcards deep links from the Study hub", () => {
  it("start=1 goes straight into the review of the named concepts and leaves the URL", async () => {
    arriveAt("course=c1&concepts=Variables|Recursion&start=1");
    renderPage();

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "What do you want to study?" })).toBeNull();
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("2 concepts");
    // `start` is consumed; the rest of the link stays.
    const left = new URLSearchParams(window.location.search);
    expect(left.get("start")).toBeNull();
    expect(left.get("course")).toBe("c1");
    expect(left.get("concepts")).toBe("Variables|Recursion");

    // "All sets" lands on the home.
    await userEvent.click(screen.getByRole("button", { name: "All sets" }));
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /^Variables/ })).toBeNull();
  });

  it("start=1 on a concept with no cards makes them first, then reviews", async () => {
    const pending = deferred<ReturnType<typeof generated>>();
    mocks.generate.mockReturnValue(pending.promise);
    arriveAt("course=c1&concepts=Sorting&start=1");
    renderPage();

    expect(await screen.findByText("Making cards for Sorting…")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledWith("u1", "Sorting", 5, undefined, "c1");
    expect(screen.queryByRole("heading", { name: "What do you want to study?" })).toBeNull();

    const made = [card("g1", "Sorting", { course_id: null }), card("g2", "Sorting", { course_id: null })];
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS, ...made] });
    pending.resolve(generated(made));

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Sorting");
    expect(mocks.generate).toHaveBeenCalledTimes(1);
  });

  it("start=1 reviews cards that carry no course without making new ones, even before the map loads", async () => {
    // Every AI-generated card today has no course; the hub counts them by
    // topic and sends the student here to review them.
    const graph = deferred<{ nodes: unknown[]; edges: unknown[]; stats: unknown }>();
    mocks.graph.mockReturnValue(graph.promise as ReturnType<typeof getGraph>);
    mocks.cards.mockResolvedValue({ flashcards: [card("o1", "Sorting", { course_id: null }), card("o2", "sorting", { course_id: null })] });
    arriveAt("course=c1&concepts=Sorting&start=1");
    renderPage();

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mocks.generate).not.toHaveBeenCalled();

    graph.resolve({ nodes: NODES, edges: EDGES, stats: {} });
    await userEvent.click(screen.getByRole("button", { name: "All sets" }));
    expect(await within(await screen.findByTestId("flashcards-deck-auto:all")).findByText("5 concepts · 2 cards")).toBeTruthy();
  });

  it("start=1 that ends with nothing to review lands on the home and says why", async () => {
    mocks.generate.mockRejectedValue(new Error("boom"));
    arriveAt("course=c1&concepts=Sorting&start=1");
    renderPage();

    await screen.findByTestId("flashcards-home-status");
    expect(homeStatus()).toMatch(/No cards could be made for this selection/);
    expect(screen.getByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("start")).toBeNull();
  });

  it("a link to a course opens the home on that course", async () => {
    const other = { ...COURSE, enrollment_id: "enr-c0", course_id: "c0", course_code: "MA123", course_name: "Calculus" };
    mocks.courses.mockResolvedValue({ courses: [other, COURSE] });
    arriveAt("course=c1");
    renderPage();

    expect(await within(await screen.findByTestId("flashcards-deck-auto:all")).findByText("All of CS101")).toBeTruthy();
    expect(mocks.sets).toHaveBeenCalledWith("u1", "c1");
    expect(mocks.sets).not.toHaveBeenCalledWith("u1", "c0");
  });

  it("start=1 for a course the student is not in starts nothing there or anywhere else", async () => {
    arriveAt("course=gone&concepts=Sorting&start=1");
    renderPage();

    // The page falls back to the first course's home.
    expect(await screen.findByTestId("flashcards-deck-auto:all")).toBeTruthy();
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /^Sorting/ })).toBeNull();
    expect(new URLSearchParams(window.location.search).get("start")).toBeNull();
  });

  it("with no course in the URL the home opens on the first course", async () => {
    await home();
    expect(mocks.sets).toHaveBeenCalledWith("u1", "c1");
    expect(mocks.checklist).toHaveBeenCalledWith("u1", "c1", undefined);
  });
});
