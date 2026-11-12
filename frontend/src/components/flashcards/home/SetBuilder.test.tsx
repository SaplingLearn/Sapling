// @vitest-environment jsdom
/**
 * BUILD, through the page: the concept map and the tray. It is a step entered
 * from the home ("Build one by hand", a deck, "Sort it"), so every spec here
 * starts on the home and goes in the way a student does.
 *
 * What it pins is what the builder pinned when it WAS the home: ticking,
 * columns, the tray's counts, Start (with and without generation), saving and
 * updating sets, and the student's own concepts.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, cleanup, waitFor, within, act } from "@testing-library/react";
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

import {
  CARDS,
  CARDS_NO_DUE,
  POINTERS_SET,
  arriveAt,
  builder,
  card,
  deck,
  deferred,
  findTile,
  generated,
  home,
  mocks,
  ownColumn,
  renderPage,
  resetMocks,
  savedSet,
  selection,
  ticked,
  tile,
} from "./pageTestKit";

beforeEach(resetMocks);

afterEach(() => {
  cleanup();
  arriveAt("");
  vi.restoreAllMocks();
});

/** The way back from a review that was started in the builder. */
const backToSelection = () => screen.getByRole("button", { name: "Back to your selection" });

// ── the map ───────────────────────────────────────────────────────────────

describe("Flashcards builder: the concept map", () => {
  it("shows the course's concepts in the hub's columns, with their card counts", async () => {
    await builder();

    expect(screen.getByRole("checkbox", { name: "Select all of Foundations" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Select all of Core Methods" })).toBeTruthy();
    expect(within(screen.getByTestId("flashcards-tile-n1")).getByText("2 cards · 1 due")).toBeTruthy();
    expect(within(screen.getByTestId("flashcards-tile-n2")).getByText("1 card · 1 due")).toBeTruthy();
    expect(within(screen.getByTestId("flashcards-tile-n4")).getByText("1 card")).toBeTruthy();
    expect(within(screen.getByTestId("flashcards-tile-n3")).getByText("No cards yet")).toBeTruthy();
    // Another course's concept is not on this map.
    expect(screen.queryByRole("checkbox", { name: /^Limits/ })).toBeNull();
    // The describe field lives in the home's hero, not here.
    expect(screen.queryByRole("textbox", { name: "Describe a set" })).toBeNull();
  });

  it("keeps a deck that is not a concept reachable, in the last column", async () => {
    await builder();
    expect(within(ownColumn()).getByRole("checkbox", { name: /^CS Basics/ })).toBeTruthy();
  });

  it("the header names what is being built and offers the way back; the course field and Import are gone", async () => {
    const user = await builder();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("New set");
    expect(screen.queryByRole("button", { name: /CS101/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Import/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "All sets" }));
    expect(await screen.findByRole("button", { name: /Build one by hand/ })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /^Variables/ })).toBeNull();
  });

  it("ticking tiles fills the tray, and says what will be generated", async () => {
    const user = await builder();
    expect(selection()).toBe("Nothing ticked yet");
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();

    await user.click(tile("Variables"));
    expect(selection()).toBe("1 concept · 2 cards");
    await user.click(tile("Sorting"));
    expect(selection()).toBe("2 concepts · 2 cards");
    expect(screen.getByText("1 has no cards yet and will be generated.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();

    await user.click(tile("Variables"));
    expect(ticked()).toEqual(["Sorting"]);
    expect(selection()).toBe("1 concept · 0 cards");
  });

  it("a column header ticks and unticks its whole column, and reads mixed in between", async () => {
    const user = await builder();
    const column = screen.getByRole("checkbox", { name: "Select all of Foundations" });

    await user.click(tile("Pointers"));
    expect(column).toBePartiallyChecked();

    await user.click(column);
    expect(ticked()).toEqual(["Pointers", "Sorting", "Trees", "Variables"]);
    expect(column).toBeChecked();
    expect(column).not.toBePartiallyChecked();

    await user.click(column);
    expect(ticked()).toEqual([]);
    expect(column).not.toBeChecked();
  });

  it("Clear sits in the tray once something is ticked", async () => {
    const user = await builder();
    const tray = within(screen.getByRole("complementary", { name: "Your selection" }));
    // With nothing ticked there is nothing to clear (it is kept in the layout,
    // hidden, so the tray's head never changes height).
    expect(tray.queryByRole("button", { name: "Clear" })).toBeNull();

    await user.click(tile("Variables"));
    await user.click(tile("Recursion"));
    expect(ticked()).toEqual(["Variables", "Recursion"]);
    await user.click(tray.getByRole("button", { name: "Clear" }));
    expect(ticked()).toEqual([]);
  });

  it("hides every due figure when no card carries a due date", async () => {
    mocks.cards.mockResolvedValue({ flashcards: CARDS_NO_DUE });
    await builder();

    expect(screen.queryByRole("switch", { name: "Only what's due" })).toBeNull();
    expect(within(screen.getByTestId("flashcards-tile-n1")).getByText("2 cards")).toBeTruthy();
    expect(screen.queryByText(/\bdue\b/i)).toBeNull();
    expect(screen.getByRole("switch", { name: "Shuffle" })).toBeTruthy();
  });

  it("a link that names concepts without start opens the builder on them", async () => {
    arriveAt("course=c1&concepts=Recursion");
    renderPage();

    await findTile("Recursion");
    expect(ticked()).toEqual(["Recursion"]);
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    expect(mocks.generate).not.toHaveBeenCalled();
  });
});

// ── a set in the builder ──────────────────────────────────────────────────

describe("Flashcards builder: saved sets", () => {
  it("opening a deck loads its set: exactly its concepts, its options and its name", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet(), POINTERS_SET] });
    const user = await home();

    await user.click(screen.getByRole("button", { name: "Open Midterm crunch" }));
    await findTile("Variables");

    // "Graphs" is not on the course map: it is one of the student's own.
    expect(ticked()).toEqual(["Variables", "Recursion", "Graphs"]);
    expect(within(ownColumn()).getByRole("checkbox", { name: /^Graphs/ })).toBeChecked();
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("Midterm crunch");
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("Midterm crunch");
    expect(screen.getByRole("switch", { name: "Shuffle" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByRole("switch", { name: "Only what's due" }).getAttribute("aria-checked")).toBe("true");
    // Loaded as saved: nothing to update, and nothing was reported dropped.
    expect(screen.queryByRole("button", { name: "Update set" })).toBeNull();
    expect(screen.queryByText(/left out/)).toBeNull();
  });

  it("only a blank or invalid name in a set is reported as left out", async () => {
    mocks.sets.mockResolvedValue({ sets: [savedSet({ concepts: ["Variables", "   ", "x".repeat(121)] })] });
    const user = await home();
    await user.click(screen.getByRole("button", { name: "Open Midterm crunch" }));
    await findTile("Variables");

    expect(ticked()).toEqual(["Variables"]);
    expect(await screen.findByText('2 blank or invalid names in "Midterm crunch" were left out.')).toBeTruthy();
  });

  it("saves the selection under a name and returns to the home, where the new deck is", async () => {
    const created = savedSet({ id: "s9", name: "Exam prep", concepts: ["Sorting", "Recursion"], options: { only_due: false, shuffle: true }, exam_id: null });
    mocks.create.mockResolvedValue({ set: created });
    const user = await builder();
    const save = screen.getByRole("button", { name: "Save set" });
    expect(save).toBeDisabled();

    await user.click(tile("Sorting"));
    await user.click(tile("Recursion"));
    expect(save).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Set name" }), "Exam prep");
    await user.click(save);

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith("u1", {
      name: "Exam prep", course_id: "c1", concepts: ["Sorting", "Recursion"],
      options: { only_due: false, shuffle: true }, exam_id: null,
    });
    expect(await screen.findByText('Saved "Exam prep".')).toBeTruthy();
    // Back on the home, with the set as a deck.
    expect(within(await screen.findByTestId("flashcards-deck-s9")).getByText("Exam prep")).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /^Sorting/ })).toBeNull();
    // Building another starts clean.
    await user.click(screen.getByRole("button", { name: /Build one by hand/ }));
    await findTile("Variables");
    expect(ticked()).toEqual([]);
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("");
  });

  it("a changed loaded set is updated in place", async () => {
    mocks.sets.mockResolvedValue({ sets: [POINTERS_SET] });
    mocks.update.mockResolvedValue({ set: { ...POINTERS_SET, concepts: ["Pointers", "Variables"] } });
    const user = await home();
    await user.click(screen.getByRole("button", { name: "Open Pointers only" }));
    await findTile("Variables");

    expect(screen.queryByRole("button", { name: "Update set" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save as new" })).toBeNull();
    await user.click(tile("Variables"));
    await user.click(screen.getByRole("button", { name: "Update set" }));

    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    // The exam link did not change, so it is not sent (the server re-checks
    // an exam id it is given, and the exam may be gone by now).
    expect(mocks.update).toHaveBeenCalledWith("u1", "s2", {
      name: "Pointers only", concepts: ["Pointers", "Variables"],
      options: { only_due: false, shuffle: true },
    });
    expect(await screen.findByText('Updated "Pointers only".')).toBeTruthy();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(within(await screen.findByTestId("flashcards-deck-s2")).getByText("2 concepts · 3 cards · 1 due")).toBeTruthy();
  });

  it("a changed loaded set can be kept and a copy saved as new; a copy drops an exam that is gone", async () => {
    const stale = savedSet({ id: "s4", name: "Old midterm", concepts: ["Variables"], options: { only_due: false, shuffle: true }, exam_id: "deleted-exam" });
    mocks.sets.mockResolvedValue({ sets: [stale] });
    mocks.create.mockResolvedValue({ set: { ...stale, id: "s5", name: "Copy", concepts: ["Variables", "Trees"], exam_id: null } });
    const user = await home();
    await user.click(screen.getByRole("button", { name: "Open Old midterm" }));
    await findTile("Variables");

    await user.click(tile("Trees"));
    const name = screen.getByRole("textbox", { name: "Set name" });
    await user.clear(name);
    await user.type(name, "Copy");
    await user.click(screen.getByRole("button", { name: "Save as new" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create.mock.calls[0][1]).toMatchObject({ name: "Copy", concepts: ["Variables", "Trees"], exam_id: null });
    expect(mocks.update).not.toHaveBeenCalled();
    // Both are on the home afterwards.
    expect(await screen.findByTestId("flashcards-deck-s5")).toBeTruthy();
    expect(deck("s4")).toBeTruthy();
  });

  it("a failed save says why and leaves the builder as it was", async () => {
    mocks.create.mockRejectedValue(new Error(JSON.stringify({ detail: "You already have a set with that name." })));
    const user = await builder();
    await user.click(tile("Variables"));
    await user.type(screen.getByRole("textbox", { name: "Set name" }), "Mine");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(await screen.findByText("You already have a set with that name.")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("Mine");
    expect(ticked()).toEqual(["Variables"]);
    expect(screen.getByRole("button", { name: "Save set" })).toBeEnabled();
  });

  it("going back to all sets lets an unsaved selection go", async () => {
    const user = await builder();
    await user.click(tile("Variables"));
    await user.type(screen.getByRole("textbox", { name: "Set name" }), "Half done");

    await user.click(screen.getByRole("button", { name: "All sets" }));
    await user.click(await screen.findByRole("button", { name: /Build one by hand/ }));
    await findTile("Variables");

    expect(ticked()).toEqual([]);
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("");
    expect(mocks.create).not.toHaveBeenCalled();
  });
});

// ── start ─────────────────────────────────────────────────────────────────

describe("Flashcards builder: Start", () => {
  it("reviews the ticked concepts' cards, in concept order when shuffle is off, and comes back to the selection", async () => {
    const user = await builder();
    await user.click(tile("Recursion"));
    await user.click(tile("Variables"));
    await user.click(screen.getByRole("switch", { name: "Shuffle" }));
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    // Variables comes before Recursion on the map, whatever order they were ticked in.
    expect(screen.getByTestId("flashcards-topic").textContent).toBe("Variables");
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(screen.getByTestId("flashcards-deck-name").textContent).toBe("2 concepts");

    // The way back is to the builder, with the selection as it was.
    await user.click(backToSelection());
    await findTile("Variables");
    expect(ticked()).toEqual(["Variables", "Recursion"]);
    expect(screen.getByRole("switch", { name: "Shuffle" }).getAttribute("aria-checked")).toBe("false");
  });

  it("only-what's-due reviews just the due cards and generates nothing", async () => {
    const user = await builder();
    await user.click(tile("Variables"));
    await user.click(tile("Sorting"));
    await user.click(screen.getByRole("switch", { name: "Only what's due" }));
    expect(selection()).toBe("2 concepts · 1 card");
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it("generates for each concept with no cards, one at a time, and says which", async () => {
    const sorting = deferred<ReturnType<typeof generated>>();
    const trees = deferred<ReturnType<typeof generated>>();
    mocks.generate.mockReturnValueOnce(sorting.promise).mockReturnValueOnce(trees.promise);
    const user = await builder();
    await user.click(tile("Sorting"));
    await user.click(tile("Trees"));
    await user.click(screen.getByRole("radio", { name: "10" }));
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Making cards for Sorting… 1 of 2")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(1);
    expect(mocks.generate).toHaveBeenLastCalledWith("u1", "Sorting", 10, undefined, "c1");

    // The new cards come back with no course on them; they are still Sorting's.
    const made = [card("g1", "Sorting", { course_id: null }), card("g2", "Trees", { course_id: null })];
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS, ...made] });
    sorting.resolve(generated([made[0]]));
    expect(await screen.findByText("Making cards for Trees… 2 of 2")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(2);
    expect(mocks.generate).toHaveBeenLastCalledWith("u1", "Trees", 10, undefined, "c1");
    trees.resolve(generated([made[1]]));

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();

    // Back in the builder they count, so a second Start would not make them again.
    await user.click(backToSelection());
    await findTile("Sorting");
    expect(within(screen.getByTestId("flashcards-tile-n3")).getByText("1 card")).toBeTruthy();
  });

  it("a failed generation says so and moves on to the next concept", async () => {
    mocks.generate
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(generated([card("g2", "Trees")]));
    const user = await builder();
    await user.click(tile("Sorting"));
    await user.click(tile("Trees"));
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS, card("g2", "Trees")] });
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Couldn't make cards for Sorting.")).toBeTruthy();
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(2);
  });

  it("says which concept came back with no cards, and starts with the rest", async () => {
    // The generator answers 200 with nothing for a concept the material does
    // not cover: the review starts without it, and the student is told.
    mocks.generate
      .mockResolvedValueOnce(generated([]))
      .mockResolvedValueOnce(generated([card("g2", "Trees")]));
    const user = await builder();
    await user.click(tile("Sorting"));
    await user.click(tile("Trees"));
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS, card("g2", "Trees")] });
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("No cards could be made for Sorting. Your course material may not cover it yet.")).toBeTruthy();
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
  });

  it("stays in the builder and says why when nothing could be made", async () => {
    mocks.generate.mockRejectedValue(new Error("boom"));
    const user = await builder();
    await user.click(tile("Sorting"));
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText(/No cards could be made for this selection/)).toBeTruthy();
    expect(screen.queryByText(/Card 1 of/)).toBeNull();
    expect(ticked()).toEqual(["Sorting"]);
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();

    // The reason is about that selection: changing it clears the line.
    await user.click(tile("Trees"));
    expect(screen.queryByText(/No cards could be made/)).toBeNull();
  });

  it("stops generating once the server says to slow down", async () => {
    mocks.generate.mockRejectedValue(Object.assign(new Error("HTTP 429"), { status: 429 }));
    const user = await builder();
    await user.click(tile("Sorting"));
    await user.click(tile("Trees"));
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText(/No cards could be made for this selection/)).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledTimes(1);
  });
});

// ── reload and Back ───────────────────────────────────────────────────────

describe("Flashcards builder: a reload, and the browser's Back", () => {
  it("a reload keeps the builder as it was: what is ticked, the name, the options", async () => {
    const user = await builder();
    await user.click(tile("Variables"));
    await user.click(tile("Recursion"));
    await user.type(screen.getByRole("textbox", { name: "Set name" }), "Week 3");
    await user.click(screen.getByRole("switch", { name: "Shuffle" }));
    expect(new URLSearchParams(window.location.search).get("build")).toBe("1");

    // The reload: a fresh page on the URL as it stands.
    cleanup();
    renderPage();

    await findTile("Variables");
    expect(ticked()).toEqual(["Variables", "Recursion"]);
    expect(screen.getByRole("textbox", { name: "Set name" })).toHaveValue("Week 3");
    expect(screen.getByRole("switch", { name: "Shuffle" })).not.toBeChecked();

    // Leaving it is leaving it: the home, and a reload there stays home.
    await userEvent.click(screen.getByRole("button", { name: "All sets" }));
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(new URLSearchParams(window.location.search).has("build")).toBe(false);
    cleanup();
    renderPage();
    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Your selection" })).toBeNull();
  });

  it("the browser's Back leaves the builder for the home", async () => {
    const user = await builder();
    await user.click(tile("Variables"));
    expect(new URLSearchParams(window.location.search).get("build")).toBe("1");

    // What Back does: the marker's entry is left, and the page is told.
    act(() => {
      window.history.replaceState(null, "", "/flashcards");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(await screen.findByRole("heading", { name: "What do you want to study?" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Your selection" })).toBeNull();
  });
});

// ── your own concepts ─────────────────────────────────────────────────────

describe("Flashcards builder: your own concepts", () => {
  it("has no field to add one: Your own holds the decks that are not course concepts", async () => {
    await builder();
    expect(screen.queryByRole("textbox", { name: "Add your own concept" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
    // A deck of cards whose topic is not a concept sits there, and is not removable.
    expect(within(ownColumn()).getByRole("checkbox", { name: /^CS Basics/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove CS Basics" })).toBeNull();
  });

  it("a saved set's concept that is not on the map still loads, ticked, and can be removed", async () => {
    const stored = savedSet({ id: "s7", name: "With my own", concepts: ["Variables", "Hash tables"], options: { only_due: false, shuffle: true }, exam_id: null });
    mocks.sets.mockResolvedValue({ sets: [stored] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Open With my own" }));
    await findTile("Variables");

    expect(ticked()).toEqual(["Variables", "Hash tables"]);
    expect(within(ownColumn()).getByRole("checkbox", { name: /^Hash tables/ })).toBeChecked();
    expect(within(screen.getByTestId("flashcards-tile-own:hash tables")).getByText("No cards yet")).toBeTruthy();
    // Loaded as it was saved.
    expect(screen.queryByRole("button", { name: "Update set" })).toBeNull();
    // Unticking it keeps the tile, so it can be ticked back.
    await userEvent.click(tile("Hash tables"));
    expect(tile("Hash tables")).not.toBeChecked();

    await userEvent.click(screen.getByRole("button", { name: "Remove Hash tables" }));
    expect(screen.queryByRole("checkbox", { name: /^Hash tables/ })).toBeNull();
    expect(ticked()).toEqual(["Variables"]);
  });

  it("Start generates cards for it under its name, like a concept with none", async () => {
    const stored = savedSet({ id: "s7", name: "Mine", concepts: ["Hash tables"], options: { only_due: false, shuffle: true }, exam_id: null });
    const made = [card("g1", "Hash tables", { course_id: null }), card("g2", "Hash tables", { course_id: null })];
    mocks.sets.mockResolvedValue({ sets: [stored] });
    mocks.generate.mockResolvedValue(generated(made));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Open Mine" }));
    await findTile("Hash tables");
    mocks.cards.mockResolvedValue({ flashcards: [...CARDS, ...made] });
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mocks.generate).toHaveBeenCalledWith("u1", "Hash tables", 5, undefined, "c1");
  });
});
