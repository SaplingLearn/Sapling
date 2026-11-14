/**
 * The home's rules, without rendering: a deck's colour and mastery shares,
 * which decks there are, what ticked decks come to, and the hero's examples.
 */
import { describe, it, expect } from "vitest";
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import type { Concept, Status } from "../../study/studyModel";
import {
  ALL_DECK_ID,
  DUE_DECK_ID,
  PALETTES,
  PALETTE_ALL,
  PALETTE_DUE,
  buildDecks,
  columnPalette,
  selectionMix,
  setPalettes,
  SET_PALETTES,
  examplePrompts,
  firstUnit,
  mixOf,
  mixable,
  namesInSets,
  nextExam,
} from "./decksModel";
import { homeModel, type Card } from "./flashcardsModel";

const NOW = Date.parse("2026-11-12T12:00:00Z");
const TODAY = new Date(2026, 10, 12);
const PAST = "2026-11-11T09:00:00Z";

const concept = (id: string, name: string, st: Status = "new", group = "Foundations", step = 0): Concept => ({
  id, name, st, m: 0, lastStudied: null, pre: [], post: [], step, group, gap: "", weekDelta: 0,
});
const CONCEPTS = [
  concept("n1", "Variables", "mastered"),
  concept("n2", "Recursion", "review", "Core Methods", 1),
  concept("n3", "Sorting", "new", "Core Methods", 1),
  concept("n4", "Pointers", "progress"),
];

const card = (id: string, topic: string, extra: Partial<Card> = {}): Card => ({ id, topic, front: "Q", back: "A", course_id: "c1", ...extra });
const CARDS = [card("v1", "Variables"), card("v2", "Variables"), card("r1", "Recursion"), card("p1", "Pointers"), card("d1", "CS Basics")];

const set = (over: Partial<FlashcardSet> = {}): FlashcardSet => ({
  id: "s1", name: "Midterm crunch", course_id: "c1", concepts: ["variables", "Recursion", "Graphs"],
  options: { only_due: false, shuffle: false }, exam_id: "e1",
  created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...over,
});
const EXAMS = [{ id: "e0", title: "Midterm 1", iso: "2026-10-01" }, { id: "e1", title: "Midterm 2", iso: "2026-11-21" }];

const modelOf = (cards: Card[], concepts = CONCEPTS) =>
  homeModel({ cards, courseId: "c1", courseName: "Intro to CS", concepts, now: NOW });
const decksOf = (sets: FlashcardSet[] | null, cards = CARDS, concepts = CONCEPTS) =>
  buildDecks({ sets, model: modelOf(cards, concepts), concepts, exams: EXAMS, courseLabel: "CS101", today: TODAY });

describe("a deck's colour", () => {
  const made = (id: string, day: number) => ({ id, created_at: `2026-11-${String(day).padStart(2, "0")}T00:00:00Z` });

  it("sets take the colours in turn in the order they were made, never the olive of the everything deck", () => {
    const sets = [made("a", 1), made("b", 2), made("c", 3), made("d", 4), made("e", 5), made("f", 6)];
    const palettes = setPalettes(sets);
    expect(sets.map(s => palettes.get(s.id))).toEqual(["blue", "amber", "plum", "clay", "blue", "amber"]);
    expect(SET_PALETTES).not.toContain(PALETTE_ALL);
    for (const p of SET_PALETTES) expect(PALETTES).toContain(p);
  });

  it("does not depend on the order the list arrives in, and a new set leaves the others alone", () => {
    const sets = [made("a", 1), made("b", 2), made("c", 3)];
    const before = setPalettes(sets);
    expect(setPalettes([...sets].reverse())).toEqual(before);
    const after = setPalettes([made("z", 9), ...sets]);
    for (const s of sets) expect(after.get(s.id)).toBe(before.get(s.id));
    expect(after.get("z")).toBe("clay");
    // Made at the same moment: the id settles it.
    expect([...setPalettes([made("y", 1), made("x", 1)]).entries()]).toEqual([["x", "blue"], ["y", "amber"]]);
  });

  it("the builder's columns take the set colours left to right, and Your own is olive", () => {
    expect(["Basics", "Memory", "Algorithms", "Structures", "More"].map(columnPalette)).toEqual(["blue", "amber", "plum", "clay", "blue"]);
    expect(columnPalette("Your own", 1)).toBe("green");
  });

  it("the selection divides over the columns that have something ticked, in the map's order", () => {
    const item = (name: string) => ({ id: name, name, cards: 0, due: 0, status: null, custom: false });
    const columns = [
      { label: "Basics", items: [item("Variables"), item("Loops")] },
      { label: "Memory", items: [item("Pointers")] },
      { label: "Your own", items: [item("Big O")] },
    ] as unknown as Parameters<typeof selectionMix>[0];
    expect(selectionMix(columns, [])).toEqual([]);
    expect(selectionMix(columns, ["loops", "Variables", "Big O", "Not on the map"])).toEqual([
      { palette: "blue", label: "Basics", count: 2 },
      { palette: "green", label: "Your own", count: 1 },
    ]);
  });

  it("the automatic decks keep theirs: olive for everything, clay for due", () => {
    expect([PALETTE_ALL, PALETTE_DUE]).toEqual(["green", "clay"]);
  });
});

describe("the decks", () => {
  it("lead with everything on the map, then each saved set", () => {
    const decks = decksOf([set(), set({ id: "s2", name: "Pointers only", concepts: ["Pointers"], exam_id: null })]);
    expect(decks.map(d => d.id)).toEqual([ALL_DECK_ID, "s1", "s2"]);
  });

  it("the everything deck covers the whole map, is not stored, and never generates", () => {
    const all = decksOf([])[0];
    expect(all).toMatchObject({
      kind: "all", name: "All of CS101", tag: "everything", set: null, palette: PALETTE_ALL,
      names: ["Variables", "Pointers", "Recursion", "Sorting", "CS Basics"],
      meta: "5 concepts · 5 cards", cards: 5, generate: [], onlyDue: false,
    });
    expect(all.mastery).toEqual({ mastered: 1, learning: 1, struggling: 1, total: 5 });
    // Sorting is the one concept with no cards.
    expect(all.fact).toEqual({ text: "1 concept needs cards", urgent: false });
    expect(all.peek).toEqual({ shown: ["Variables", "Pointers", "Recursion"], more: 2 });
    // With no concepts the map is the decks the cards make, and that is "everything".
    expect(decksOf([], CARDS, [])[0].names).toEqual(["CS Basics", "Pointers", "Recursion", "Variables"]);
  });

  it("there is no everything deck when the map is empty, and it is named plainly with no course", () => {
    expect(decksOf([], [], [])).toEqual([]);
    const loose = buildDecks({ sets: null, model: homeModel({ cards: CARDS, courseId: "", concepts: [], now: NOW }), concepts: [], exams: [], courseLabel: "", today: TODAY });
    expect(loose.map(d => d.name)).toEqual(["All your cards"]);
  });

  it("a saved set's deck has its names as the map spells them, its counts, shares, exam and options", () => {
    const deck = decksOf([set({ options: { only_due: true, shuffle: false } })])[1];
    expect(deck).toMatchObject({
      kind: "set", id: "s1", name: "Midterm crunch", tag: "Midterm 2",
      names: ["Variables", "Recursion", "Graphs"], generate: ["Variables", "Recursion", "Graphs"],
      meta: "3 concepts · 3 cards", cards: 3, palette: "blue", shuffle: false,
      // "Only what's due" means nothing while due dates are not tracked.
      onlyDue: false,
    });
    expect(deck.mastery).toEqual({ mastered: 1, learning: 0, struggling: 1, total: 3 });
    expect(deck.peek).toEqual({ shown: ["Variables", "Recursion", "Graphs"], more: 0 });
    // Its exam is nine days off: that is its fact, ahead of "Graphs needs cards".
    expect(deck.fact).toEqual({ text: "Exam in 9 days", urgent: false });
    expect(deck.set?.id).toBe("s1");
  });

  it("a set whose exam is gone has no tag, and says what it does know", () => {
    expect(decksOf([set({ exam_id: "deleted" })])[1].tag).toBeNull();
    const plain = decksOf([set({ exam_id: null })])[1];
    expect(plain.tag).toBeNull();
    expect(plain.fact).toEqual({ text: "1 concept needs cards", urgent: false });
    // A past exam still names the set, but is not counted down to.
    const past = decksOf([set({ exam_id: "e0", concepts: ["Variables"] })])[1];
    expect(past.tag).toBe("Midterm 1");
    expect(past.fact).toBeNull();
  });

  it("a due deck leads, only when due dates are tracked and something is due", () => {
    const due = [card("v1", "Variables", { due_at: PAST }), card("r1", "Recursion", { due_at: PAST }), card("p1", "Pointers")];
    const decks = decksOf([set({ options: { only_due: true, shuffle: true } })], due);
    expect(decks.map(d => d.id)).toEqual([DUE_DECK_ID, ALL_DECK_ID, "s1"]);
    expect(decks[0]).toMatchObject({
      kind: "due", name: "Due today", tag: "due", meta: "2 cards", cards: 2, names: [], palette: PALETTE_DUE,
      // A peek at what is due, and how those concepts are going; no fact.
      peek: { shown: ["Variables", "Recursion"], more: 0 },
      mastery: { mastered: 1, learning: 0, struggling: 1, total: 2 },
      fact: null,
    });
    expect(mixable(decks[0])).toBe(false);
    expect(mixable(decks[1])).toBe(true);
    // Due dates are tracked now, so the set's own option holds.
    expect(decks[2].onlyDue).toBe(true);
    expect(decks[2].meta).toBe("3 concepts · 2 cards · 2 due");

    const later = [card("v1", "Variables", { due_at: "2026-12-01T00:00:00Z" })];
    expect(decksOf([], later).map(d => d.id)).toEqual([ALL_DECK_ID]);
    expect(decksOf([]).map(d => d.id)).toEqual([ALL_DECK_ID]);
  });

  it("a failed sets list leaves the automatic decks", () => {
    expect(decksOf(null).map(d => d.id)).toEqual([ALL_DECK_ID]);
  });
});

describe("ticked decks together", () => {
  const decks = decksOf([set(), set({ id: "s2", name: "More", concepts: ["Recursion", "Pointers"], exam_id: null })]);
  const [all, first, second] = decks;
  const model = modelOf(CARDS);

  it("are the union of their concepts, each once, and the cards that makes", () => {
    expect(mixOf([first, second], model)).toEqual({
      sets: 2,
      names: ["Variables", "Recursion", "Graphs", "Pointers"],
      generate: ["Variables", "Recursion", "Graphs", "Pointers"],
      cards: 4,
    });
  });

  it("with the everything deck in, only the saved sets' concepts may be generated", () => {
    const mix = mixOf([all, second], model);
    expect(mix.names).toEqual(["Variables", "Pointers", "Recursion", "Sorting", "CS Basics"]);
    expect(mix.generate).toEqual(["Recursion", "Pointers"]);
    expect(mix.cards).toBe(5);
  });

  it("one deck, or none", () => {
    expect(mixOf([second], model)).toMatchObject({ sets: 1, names: ["Recursion", "Pointers"], cards: 2 });
    expect(mixOf([], model)).toEqual({ sets: 0, names: [], generate: [], cards: 0 });
  });

  it("the names in the saved sets place cards that carry no course", () => {
    const sets = [set(), set({ id: "s2", concepts: ["graphs", "Hash tables", 7 as unknown as string] })];
    expect(namesInSets(sets)).toEqual(["variables", "Recursion", "Graphs", "Hash tables"]);
    expect(namesInSets(null)).toEqual([]);
    const loose = card("g1", "Hash tables", { course_id: null });
    expect(homeModel({ cards: [loose], courseId: "c1", concepts: CONCEPTS, now: NOW }).courseCards).toEqual([]);
    const placed = homeModel({ cards: [loose], courseId: "c1", concepts: CONCEPTS, known: namesInSets(sets), now: NOW });
    expect(placed.courseCards).toEqual([loose]);
    // Known to the sets, but not a tile of its own until a set is opened.
    expect(placed.columns.flatMap(c => c.items).filter(i => i.custom)).toEqual([]);
  });
});

describe("the hero's examples", () => {
  const today = new Date(2026, 10, 12);

  it("the next exam is the nearest one still ahead; today counts", () => {
    expect(nextExam(EXAMS, today)?.id).toBe("e1");
    expect(nextExam(EXAMS, new Date(2026, 10, 21))?.id).toBe("e1");
    expect(nextExam(EXAMS, new Date(2026, 10, 22))).toBeNull();
    expect(nextExam([], today)).toBeNull();
  });

  it("the first unit is the map's first column that is one of the outline's categories", () => {
    const units = [concept("a", "Arrays", "new", "Memory and Data", 1), concept("b", "Loops", "new", "Programming Foundations", 0), concept("c", "Misc", "new", "Other", 0)];
    const outline = [
      { id: "u1", name: "Programming Foundations", parent_id: null, node_id: null },
      { id: "u2", name: "Memory and Data", parent_id: null, node_id: null },
      { id: "t1", name: "Loops", parent_id: "u1", node_id: "b" },
      { id: "t2", name: "Arrays", parent_id: "u2", node_id: "a" },
    ];
    expect(firstUnit(units, outline)).toBe("Programming Foundations");
    // The hub's fallback layers are not units, whatever they are called.
    expect(firstUnit(CONCEPTS, outline)).toBeNull();
    expect(firstUnit(CONCEPTS, [])).toBeNull();
  });

  it("are built from what the course has, at most four", () => {
    expect(examplePrompts({ exam: EXAMS[1], concepts: CONCEPTS, unit: "Memory and Data" })).toEqual([
      "Everything on Midterm 2", "What I'm struggling with", "Memory and Data from scratch", "Just the basics",
    ]);
    const calm = CONCEPTS.filter(c => c.st !== "review");
    expect(examplePrompts({ exam: null, concepts: calm, unit: null })).toEqual(["Just the basics"]);
    expect(examplePrompts({ exam: null, concepts: CONCEPTS, unit: null })).toEqual(["What I'm struggling with", "Just the basics"]);
  });
});
