/**
 * The Flashcards home's rules, without rendering: which cards belong to which
 * concept, what is due, what each quick pick ticks, how the deck is built, and
 * what the tray's draft does.
 */
import { describe, it, expect } from "vitest";
import type { Assignment } from "@/lib/api";
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import type { Concept, Status } from "../../study/studyModel";
import {
  YOUR_OWN,
  buildDeck,
  cardsInCourse,
  cardsLabel,
  columnCheck,
  deckFact,
  masteryCounts,
  masteryLegend,
  peekNames,
  describeNote,
  findOnMap,
  namesOnMap,
  validConceptName,
  countsFor,
  deckTitle,
  draftChanged,
  draftPayload,
  draftReducer,
  emptyDeckReason,
  emptyDraft,
  examsForCourse,
  hasDueData,
  homeModel,
  indexCards,
  isDue,
  mapColumns,
  orderNames,
  resolveSet,
  saveState,
  setMeta,
  shuffled,
  summarize,
  type Card,
  type Draft,
} from "./flashcardsModel";

const NOW = Date.parse("2026-11-12T12:00:00Z");
const PAST = "2026-11-11T09:00:00Z";
const FUTURE = "2026-11-20T09:00:00Z";

const card = (id: string, topic: string | null, extra: Partial<Card> = {}): Card => ({
  id, topic, front: `Q-${id}`, back: `A-${id}`, course_id: "c1", ...extra,
});

const concept = (id: string, name: string, st: Status = "new", group = "Foundations", step = 0): Concept => ({
  id, name, st, m: 0, lastStudied: null, pre: [], post: [], step, group, gap: "", weekDelta: 0,
});

const CONCEPTS = [
  concept("n1", "Variables", "mastered"),
  concept("n2", "Recursion", "review", "Core Methods", 1),
  concept("n3", "Sorting", "new", "Core Methods", 1),
];

const CARDS: Card[] = [
  card("v1", "Variables", { due_at: PAST }),
  card("v2", " variables ", { due_at: FUTURE }),
  card("r1", "Recursion", { due_at: PAST }),
  card("x1", "Recursion", { course_id: "c2", due_at: PAST }),
  card("d1", "CS Basics"),
  card("d2", "CS Basics", { due_at: PAST }),
];

const COURSE = { name: "Intro to CS", conceptNames: CONCEPTS.map(c => c.name) };
const indexOf = (cards: Card[], concepts = CONCEPTS, showDue = true) =>
  indexCards(cardsInCourse(cards, "c1", COURSE), concepts.map(c => c.name), { now: NOW, showDue });

const set = (over: Partial<FlashcardSet> = {}): FlashcardSet => ({
  id: "s1", name: "Midterm crunch", course_id: "c1", concepts: ["Variables", "Recursion"],
  options: { only_due: false, shuffle: true }, exam_id: null,
  created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...over,
});

describe("cards and concepts", () => {
  it("a card belongs to a concept by topic (trimmed, case-insensitive) and course", () => {
    const index = indexOf(CARDS);
    expect(countsFor(index, "Variables")).toEqual({ cards: 2, due: 1 });
    expect(countsFor(index, "RECURSION ")).toEqual({ cards: 1, due: 1 });
    expect(countsFor(index, "Sorting")).toEqual({ cards: 0, due: 0 });
  });

  it("a card of another course never matches this course's concept", () => {
    const ids = (indexOf(CARDS).byKey.get("recursion") ?? []).map(c => c.id);
    expect(ids).toEqual(["r1"]);
  });

  it("topics that are not concepts stay reachable as other decks", () => {
    expect(indexOf(CARDS).others).toEqual([{ key: "cs basics", name: "CS Basics" }]);
  });

  it("with no course chosen every card counts", () => {
    expect(cardsInCourse(CARDS, "")).toHaveLength(CARDS.length);
  });
});

// Every AI-generated card today: the generate route stores no offering.
describe("cards with no course", () => {
  const loose = (id: string, topic: string | null) => card(id, topic, { course_id: null });

  it("one whose topic names a concept is that concept's, as the Study hub counts it", () => {
    const index = indexOf([...CARDS, loose("g1", "sorting "), loose("g2", "Recursion")]);
    expect(countsFor(index, "Sorting").cards).toBe(1);
    expect((index.byKey.get("recursion") ?? []).map(c => c.id)).toEqual(["r1", "g2"]);
    expect(index.others.map(o => o.name)).toEqual(["CS Basics"]);
  });

  it("one made for several concepts at once, or named for the course, is an other deck", () => {
    const index = indexOf([loose("j1", "Recursion, Sorting"), loose("n1", "Intro to CS review")]);
    expect(index.others.map(o => o.name)).toEqual(["Intro to CS review", "Recursion, Sorting"]);
  });

  it("one that points at nothing in this course is not shown in it", () => {
    const elsewhere = [loose("l1", "Limits"), loose("l2", "Limits, Series"), loose("l3", null), loose("l4", "Sorting algorithms")];
    expect(cardsInCourse(elsewhere, "c1", COURSE)).toEqual([]);
    // A one-letter concept does not claim every topic that contains the letter.
    expect(cardsInCourse([loose("c1", "Calculus")], "c1", { name: "Programming", conceptNames: ["C"] })).toEqual([]);
    expect(cardsInCourse([loose("c2", "c")], "c1", { name: "Programming", conceptNames: ["C"] })).toHaveLength(1);
  });

  it("a concept whose own name has a comma still matches whole", () => {
    const course = { name: "Algorithms", conceptNames: ["Sorting, Searching and Hashing"] };
    expect(cardsInCourse([loose("s1", "Sorting, Searching and Hashing")], "c1", course)).toHaveLength(1);
  });
});

describe("due", () => {
  it("a card is due at or before now; null or absent is not due", () => {
    expect(isDue(card("a", "T", { due_at: PAST }), NOW)).toBe(true);
    expect(isDue(card("a", "T", { due_at: new Date(NOW).toISOString() }), NOW)).toBe(true);
    expect(isDue(card("a", "T", { due_at: FUTURE }), NOW)).toBe(false);
    expect(isDue(card("a", "T", { due_at: null }), NOW)).toBe(false);
    expect(isDue(card("a", "T"), NOW)).toBe(false);
    expect(isDue(card("a", "T", { due_at: "not a date" }), NOW)).toBe(false);
  });

  it("due dates are tracked only when some card has one", () => {
    expect(hasDueData(CARDS)).toBe(true);
    expect(hasDueData([card("a", "T"), card("b", "T", { due_at: null })])).toBe(false);
  });

  it("hides every due count when due dates are not tracked", () => {
    const index = indexOf(CARDS, CONCEPTS, false);
    expect(countsFor(index, "Variables")).toEqual({ cards: 2, due: 0 });
    expect(setMeta(set(), index)).toBe("2 concepts · 3 cards");
  });

  it("labels a tile", () => {
    expect(cardsLabel(0, 0)).toBe("No cards yet");
    expect(cardsLabel(1, 0)).toBe("1 card");
    expect(cardsLabel(4, 2)).toBe("4 cards · 2 due");
  });
});

describe("the map", () => {
  it("lays concepts out in the hub's columns, then the other decks", () => {
    const columns = mapColumns(CONCEPTS, indexOf(CARDS));
    expect(columns.map(c => c.label)).toEqual(["Foundations", "Core Methods", YOUR_OWN]);
    expect(columns[1].items.map(i => [i.name, i.cards, i.due])).toEqual([["Recursion", 1, 1], ["Sorting", 0, 0]]);
    expect(columns[2].items).toEqual([{ id: "deck:cs basics", name: "CS Basics", status: null, cards: 2, due: 1, custom: false }]);
  });

  it("a column header reads all, none or some", () => {
    const items = mapColumns(CONCEPTS, indexOf(CARDS))[1].items;
    expect(columnCheck([], items)).toEqual({ ticked: 0, state: "none" });
    expect(columnCheck(["recursion"], items)).toEqual({ ticked: 1, state: "some" });
    expect(columnCheck(["Recursion", "Sorting", "Variables"], items)).toEqual({ ticked: 2, state: "all" });
  });

  it("sums the selection for the tray", () => {
    const index = indexOf(CARDS);
    expect(summarize(["Variables", "Sorting"], index, false)).toEqual({ concepts: 2, cards: 2, missing: ["Sorting"] });
    expect(summarize(["Variables", "Recursion"], index, true)).toEqual({ concepts: 2, cards: 2, missing: [] });
    expect(summarize([], index, false)).toEqual({ concepts: 0, cards: 0, missing: [] });
  });
});

describe("a course's exams", () => {
  it("reads a course's exams off its assignments, soonest first", () => {
    const a = (id: string, title: string, due: string | null, type?: string, course = "c1"): Assignment =>
      ({ id, user_id: "u1", title, due_date: due, assignment_type: type, course_id: course });
    const all = examsForCourse([
      a("e2", "Final", "2026-12-15T00:00:00", "exam"),
      a("e1", "Midterm 2", "2026-11-21", "midterm"),
      a("q1", "Quiz 3", "2026-11-01", "quiz"),
      a("h1", "Homework 4", "2026-11-20", "homework"),
      a("n1", "Undated exam", null, "exam"),
      a("o1", "Other course exam", "2026-11-22", "exam", "c2"),
    ], "c1");
    expect(all.map(e => e.id)).toEqual(["q1", "e1", "e2"]);
  });
});

describe("the deck", () => {
  const index = indexOf(CARDS);

  it("holds every card of the named concepts, in the order given", () => {
    const deck = buildDeck({ names: ["Recursion", "Variables"], index, onlyDue: false, shuffle: false, random: () => 0 });
    expect(deck.map(c => c.id)).toEqual(["r1", "v1", "v2"]);
  });

  it("only-due keeps the due ones", () => {
    const deck = buildDeck({ names: ["Variables", "Recursion", "Sorting"], index, onlyDue: true, shuffle: false, random: () => 0 });
    expect(deck.map(c => c.id)).toEqual(["v1", "r1"]);
  });

  it("never holds a card twice", () => {
    const deck = buildDeck({ names: ["Variables", "variables"], index, onlyDue: false, shuffle: false, random: () => 0 });
    expect(deck.map(c => c.id)).toEqual(["v1", "v2"]);
  });

  it("shuffles with the random source it is handed", () => {
    const rolls = [0.9, 0.1, 0.5];
    let i = 0;
    const random = () => rolls[i++ % rolls.length];
    expect(shuffled([1, 2, 3, 4], random)).toEqual([3, 2, 1, 4]);
    const first = buildDeck({ names: ["Variables", "Recursion"], index, onlyDue: false, shuffle: true, random: () => 0 });
    expect(first.map(c => c.id)).toEqual(["v2", "r1", "v1"]);
    expect(first).toHaveLength(3);
  });

  it("does not disturb the list it shuffles", () => {
    const items = [1, 2, 3];
    shuffled(items, () => 0);
    expect(items).toEqual([1, 2, 3]);
  });

  it("orders a selection as the map shows it; names the map lacks go last", () => {
    const columns = mapColumns(CONCEPTS, index);
    expect(orderNames(["Elsewhere", "CS Basics", "sorting", "Variables"], columns)).toEqual(["Variables", "sorting", "CS Basics", "Elsewhere"]);
  });

  it("says why a deck came out empty", () => {
    expect(emptyDeckReason(true, false)).toMatch(/due/);
    expect(emptyDeckReason(false, true)).toMatch(/could be made/);
    expect(emptyDeckReason(false, false)).toMatch(/no cards/);
  });

  it("names the deck: the set, the one concept, or how many", () => {
    expect(deckTitle({ name: " Midterm crunch ", selected: ["A", "B"] })).toBe("Midterm crunch");
    expect(deckTitle({ name: "", selected: ["Recursion"] })).toBe("Recursion");
    expect(deckTitle({ name: "", selected: ["A", "B", "C"] })).toBe("3 concepts");
  });
});

describe("saved sets", () => {
  const columns = mapColumns(CONCEPTS, indexOf(CARDS));

  it("loads a set's names: the map's under the map's spelling, the rest as the student's own", () => {
    expect(resolveSet(["variables", "Hash tables", "CS Basics", "Graphs", "VARIABLES"], columns)).toEqual({
      names: ["Variables", "Hash tables", "CS Basics", "Graphs"], custom: ["Hash tables", "Graphs"], dropped: 0,
    });
  });

  it("drops only a blank or invalid name", () => {
    expect(resolveSet(["Variables", "  ", "", 7, null, "x".repeat(121)], columns)).toEqual({ names: ["Variables"], custom: [], dropped: 5 });
    expect(resolveSet(["x".repeat(120)], columns).dropped).toBe(0);
  });

  it("describes a set on the shelf", () => {
    expect(setMeta(set(), indexOf(CARDS))).toBe("2 concepts · 3 cards · 2 due");
    expect(setMeta(set({ concepts: ["Sorting"] }), indexOf(CARDS))).toBe("1 concept · 0 cards");
  });
});

describe("your own concepts", () => {
  const index = indexOf(CARDS);

  it("a name must be 1 to 120 characters once trimmed", () => {
    expect(validConceptName("  Hash tables ")).toBe("Hash tables");
    expect(validConceptName("   ")).toBeNull();
    expect(validConceptName("x".repeat(121))).toBeNull();
    expect(validConceptName(undefined)).toBeNull();
  });

  it("show in the last column after the decks, with no cards and a way to remove them", () => {
    const columns = mapColumns(CONCEPTS, index, ["Hash tables", "Graphs"]);
    expect(columns.at(-1)?.label).toBe(YOUR_OWN);
    expect(columns.at(-1)?.items.map(i => [i.name, i.cards, i.custom])).toEqual([
      ["CS Basics", 2, false], ["Hash tables", 0, true], ["Graphs", 0, true],
    ]);
  });

  it("make the column on their own when the course has no other decks", () => {
    const columns = mapColumns(CONCEPTS, indexOf([]), ["Hash tables"]);
    expect(columns.at(-1)).toEqual({ label: YOUR_OWN, items: [{ id: "own:hash tables", name: "Hash tables", status: null, cards: 0, due: 0, custom: true }] });
    expect(mapColumns(CONCEPTS, indexOf([])).map(c => c.label)).toEqual(["Foundations", "Core Methods"]);
  });

  it("are not repeated when the map already has the name", () => {
    const columns = mapColumns(CONCEPTS, index, ["recursion", "cs basics", "Hash tables", "hash TABLES"]);
    expect(columns.flatMap(c => c.items).map(i => i.name)).toEqual(["Variables", "Recursion", "Sorting", "CS Basics", "Hash tables"]);
  });

  it("finds a name on the map under the map's spelling", () => {
    const columns = mapColumns(CONCEPTS, index, ["Hash tables"]);
    expect(findOnMap(" RECURSION", columns)).toBe("Recursion");
    expect(findOnMap("hash tables", columns)).toBe("Hash tables");
    expect(findOnMap("Graphs", columns)).toBeNull();
    expect(namesOnMap(["sorting", "Graphs", "Sorting", "cs basics"], columns)).toEqual({ found: ["Sorting", "CS Basics"], missing: ["Graphs"] });
  });

  it("place their generated cards in the course even when the cards carry none", () => {
    const made = card("g1", "Hash tables", { course_id: null });
    const input = { courseId: "c1", courseName: "Intro to CS", concepts: CONCEPTS, exams: [], outline: [], today: new Date(2026, 10, 12), now: NOW };
    expect(homeModel({ ...input, cards: [made] }).courseCards).toEqual([]);
    const model = homeModel({ ...input, cards: [made], custom: ["hash tables"] });
    // Now it has cards it is a deck like any other: no longer removable.
    expect(model.columns.at(-1)?.items).toEqual([{ id: "deck:hash tables", name: "Hash tables", status: null, cards: 1, due: 0, custom: false }]);
  });
});

describe("describing a set", () => {
  it("says how many concepts were sorted in, out of those weighed", () => {
    expect(describeNote(4, 12)).toBe("Sorted 4 of 12 concepts into this set. Tick or untick to adjust, then save.");
    expect(describeNote(1, 1)).toBe("Sorted 1 of 1 concept into this set. Tick or untick to adjust, then save.");
    // Never "5 of 3".
    expect(describeNote(5, 3)).toMatch(/^Sorted 5 of 5 concepts/);
  });

  it("says plainly when nothing matched", () => {
    expect(describeNote(0, 12)).toMatch(/Nothing on this course's map matched/);
  });
});

describe("the tray's draft", () => {
  const run = (draft: Draft, ...actions: Parameters<typeof draftReducer>[1][]) => actions.reduce(draftReducer, draft);

  it("starts with shuffle on, five new cards per concept, and the URL's concepts", () => {
    expect(emptyDraft(["A", "a ", "B"])).toEqual({
      selected: ["A", "B"], onlyDue: false, shuffle: true, perConcept: 5, name: "", setId: null, examId: null,
      // The URL's names double as own concepts: any not on the map still show.
      custom: ["A", "B"], givenName: null,
    });
  });

  it("toggles one name and ticks or unticks many", () => {
    const d = run(emptyDraft(), { type: "toggle", name: "Variables" }, { type: "many", names: ["Recursion", "variables"], on: true });
    expect(d.selected).toEqual(["Variables", "Recursion"]);
    expect(run(d, { type: "toggle", name: "VARIABLES" }).selected).toEqual(["Recursion"]);
    expect(run(d, { type: "many", names: ["Recursion", "Variables"], on: false }).selected).toEqual([]);
  });

  it("loading a set takes its concepts, options, name and exam", () => {
    const loaded = run(emptyDraft(["Sorting"]), { type: "load", set: set({ options: { only_due: true, shuffle: false }, exam_id: "e1" }), names: ["Variables"], custom: [] });
    expect(loaded).toMatchObject({ selected: ["Variables"], onlyDue: true, shuffle: false, name: "Midterm crunch", setId: "s1", examId: "e1" });
  });

  it("replacing a loaded set's selection lets go of the set and its name", () => {
    const loaded = run(emptyDraft(), { type: "load", set: set(), names: ["Variables", "Recursion"], custom: [] });
    expect(run(loaded, { type: "clear" })).toMatchObject({ selected: [], setId: null, name: "", examId: null });
    expect(run(loaded, { type: "clear" })).toMatchObject({ setId: null, name: "", selected: [] });
    // A name typed for a selection that was never a set is the student's to keep.
    const typed = run(emptyDraft(["A"]), { type: "name", value: "Mine" }, { type: "clear" });
    expect(typed.name).toBe("Mine");
  });

  it("follows the loaded set through a save, a rename and a delete", () => {
    const saved = run(emptyDraft(["Variables"]), { type: "name", value: "Mine" }, { type: "saved", set: set({ id: "s9", name: "Mine" }) });
    expect(saved).toMatchObject({ setId: "s9", name: "Mine" });
    expect(run(saved, { type: "renamed", set: set({ id: "s9", name: "Renamed" }) }).name).toBe("Renamed");
    expect(run(saved, { type: "renamed", set: set({ id: "other", name: "Renamed" }) }).name).toBe("Mine");
    expect(run(saved, { type: "deleted", setId: "s9" }).setId).toBeNull();
    expect(run(saved, { type: "deleted", setId: "other" }).setId).toBe("s9");
    expect(run(saved, { type: "reset" })).toEqual(emptyDraft());
  });

  it("knows when a loaded set was changed", () => {
    const loaded = run(emptyDraft(), { type: "load", set: set(), names: ["Variables", "Recursion"], custom: [] });
    expect(draftChanged(set(), loaded)).toBe(false);
    expect(draftChanged(set(), run(loaded, { type: "toggle", name: "Sorting" }))).toBe(true);
    expect(draftChanged(set(), run(loaded, { type: "option", patch: { shuffle: false } }))).toBe(true);
    expect(draftChanged(set(), run(loaded, { type: "name", value: "Other" }))).toBe(true);
    // Per-concept count is not part of a set.
    expect(draftChanged(set(), run(loaded, { type: "option", patch: { perConcept: 10 } }))).toBe(false);
  });

  it("decides what the save button does", () => {
    const sets = [set()];
    expect(saveState(emptyDraft(), sets)).toMatchObject({ mode: "create", label: "Save set", enabled: false });
    expect(saveState(run(emptyDraft(["A"]), { type: "name", value: "  " }), sets).enabled).toBe(false);
    expect(saveState(run(emptyDraft(["A"]), { type: "name", value: "Mine" }), sets)).toMatchObject({ mode: "create", label: "Save set", enabled: true, canSaveAsNew: false });
    const loaded = run(emptyDraft(), { type: "load", set: set(), names: ["Variables", "Recursion"], custom: [] });
    expect(saveState(loaded, sets)).toMatchObject({ label: "Save set", enabled: false, canSaveAsNew: false });
    expect(saveState(run(loaded, { type: "toggle", name: "Sorting" }), sets)).toMatchObject({ mode: "update", label: "Update set", enabled: true, canSaveAsNew: true });
    // The list could not be read: a save can only make a new set.
    expect(saveState(run(loaded, { type: "toggle", name: "Sorting" }), null)).toMatchObject({ mode: "create", label: "Save set" });
  });

  it("adds and removes a concept of the student's own", () => {
    const d = run(emptyDraft(), { type: "custom", name: "Hash tables" }, { type: "custom", name: "hash tables" });
    expect(d).toMatchObject({ selected: ["Hash tables"], custom: ["Hash tables"] });
    // Unticking keeps it on the map; removing takes it off both.
    expect(run(d, { type: "toggle", name: "Hash tables" })).toMatchObject({ selected: [], custom: ["Hash tables"] });
    expect(run(d, { type: "uncustom", name: "HASH TABLES" })).toMatchObject({ selected: [], custom: [] });
    // Clearing or picking leaves the student's own concepts on the map.
    expect(run(d, { type: "clear" }).custom).toEqual(["Hash tables"]);
  });

  it("a loaded or added set brings its own concepts with it", () => {
    const withOwn = set({ concepts: ["Variables", "Hash tables"] });
    const loaded = run(emptyDraft(), { type: "load", set: withOwn, names: ["Variables", "Hash tables"], custom: ["Hash tables"] });
    expect(loaded).toMatchObject({ selected: ["Variables", "Hash tables"], custom: ["Hash tables"], setId: "s1" });
    const added = run(emptyDraft(["Sorting"]), { type: "many", names: ["Variables", "Hash tables"], on: true, custom: ["Hash tables"] });
    expect(added).toMatchObject({ selected: ["Sorting", "Variables", "Hash tables"], custom: ["Sorting", "Hash tables"], setId: null });
  });

  it("a described selection replaces the selection and is not a loaded set", () => {
    const loaded = run(emptyDraft(), { type: "load", set: set({ exam_id: "e1" }), names: ["Variables", "Recursion"], custom: [] });
    const d = run(loaded, { type: "describe", names: ["Sorting", "sorting", "Recursion"], name: "Midterm sorting" });
    expect(d).toMatchObject({ selected: ["Sorting", "Recursion"], setId: null, examId: null, name: "Midterm sorting" });
    expect(saveState(d, [set()])).toMatchObject({ mode: "create", label: "Save set", enabled: true, canSaveAsNew: false });
  });

  it("a suggested name fills an empty field or replaces an earlier suggestion, never what was typed", () => {
    const first = run(emptyDraft(), { type: "describe", names: ["Sorting"], name: "First idea" });
    expect(first.name).toBe("First idea");
    expect(run(first, { type: "describe", names: ["Recursion"], name: "Second idea" }).name).toBe("Second idea");

    const typed = run(emptyDraft(), { type: "name", value: "Mine" }, { type: "describe", names: ["Sorting"], name: "Suggested" });
    expect(typed).toMatchObject({ name: "Mine", selected: ["Sorting"] });
    // Editing a suggestion makes it the student's.
    const edited = run(first, { type: "name", value: "First idea, week 3" }, { type: "describe", names: ["Recursion"], name: "Second idea" });
    expect(edited.name).toBe("First idea, week 3");
    // So does typing over a loaded set's name; the set's own name goes with the set.
    const loaded = run(emptyDraft(), { type: "load", set: set(), names: ["Variables"], custom: [] });
    expect(run(loaded, { type: "describe", names: ["Sorting"], name: "Suggested" }).name).toBe("Suggested");
    expect(run(loaded, { type: "name", value: "My rename" }, { type: "describe", names: ["Sorting"], name: "Suggested" }).name).toBe("My rename");
    // A suggestion that was saved as a set is still not something typed.
    const saved = run(first, { type: "saved", set: set({ id: "s9", name: "First idea" }) });
    expect(run(saved, { type: "describe", names: ["Recursion"], name: "Second idea" })).toMatchObject({ name: "Second idea", setId: null });
    // An empty suggestion leaves the field alone.
    expect(run(emptyDraft(), { type: "describe", names: ["Sorting"], name: "  " }).name).toBe("");
  });

  it("sends a draft as the API stores it", () => {
    const d = run(emptyDraft(["Variables"]), { type: "name", value: " Mine " }, { type: "option", patch: { onlyDue: true } });
    expect(draftPayload(d)).toEqual({ name: "Mine", concepts: ["Variables"], options: { only_due: true, shuffle: true }, exam_id: null });
  });
});

describe("homeModel", () => {
  const input = { courseId: "c1", courseName: "Intro to CS", concepts: CONCEPTS, now: NOW };

  it("puts the course's cards, map and due cards together", () => {
    const model = homeModel({ ...input, cards: CARDS });
    expect(model.courseCards.map(c => c.id)).toEqual(["v1", "v2", "r1", "d1", "d2"]);
    expect(model.dueCards.map(c => c.id)).toEqual(["v1", "r1", "d2"]);
  });

  it("with no due date on any card there is nothing due", () => {
    const model = homeModel({ ...input, cards: CARDS.map(c => ({ ...c, due_at: null })) });
    expect(model.index.showDue).toBe(false);
    expect(model.dueCards).toEqual([]);
  });
});

describe("what a deck says about itself", () => {
  const exam = (iso: string) => ({ id: "e1", title: "Midterm 2", iso });
  const today = new Date(2026, 10, 12);

  it("peeks at up to three names that fit the line, and counts the rest", () => {
    expect(peekNames(["Loops", "Arrays", "Trees", "Graphs", "Heaps"])).toEqual({ shown: ["Loops", "Arrays", "Trees"], more: 2 });
    expect(peekNames(["Loops", "Arrays"])).toEqual({ shown: ["Loops", "Arrays"], more: 0 });
    expect(peekNames([])).toEqual({ shown: [], more: 0 });
  });

  it("shows fewer chips when the names are long, never a cut one", () => {
    // 19 + 18 characters is over the line's 36: one chip, the rest counted.
    expect(peekNames(["Pointers and Memory", "Arrays and Strings", "Structs"])).toEqual({ shown: ["Pointers and Memory"], more: 2 });
    // 9 + 12 fits, a third of 17 does not.
    expect(peekNames(["Recursion", "Control Flow", "Sorting and merging", "Trees"])).toEqual({ shown: ["Recursion", "Control Flow"], more: 2 });
    // The first is always shown, however long (the stylesheet shortens it).
    const long = "A very long concept name that will not fit";
    expect(peekNames([long, "B"])).toEqual({ shown: [long], more: 1 });
  });

  it("counts a name once, and takes the limits it is given", () => {
    expect(peekNames(["Loops", "loops ", "Trees"])).toEqual({ shown: ["Loops", "Trees"], more: 0 });
    expect(peekNames(["A", "B", "C"], 2)).toEqual({ shown: ["A", "B"], more: 1 });
    expect(peekNames(["Loops", "Trees"], 3, 6)).toEqual({ shown: ["Loops"], more: 1 });
  });

  it("counts a deck's concepts by mastery; not started and unknown ones only add to the total", () => {
    expect(masteryCounts(["Variables", "recursion", "Sorting", "Graphs", "Variables "], CONCEPTS)).toEqual({ mastered: 1, learning: 0, struggling: 1, total: 4 });
    expect(masteryCounts([], CONCEPTS)).toEqual({ mastered: 0, learning: 0, struggling: 0, total: 0 });
    const learning = [...CONCEPTS, concept("n4", "Pointers", "progress")];
    expect(masteryCounts(["Pointers"], learning)).toEqual({ mastered: 0, learning: 1, struggling: 0, total: 1 });
  });

  it("lists only the groups that have something in them", () => {
    expect(masteryLegend({ mastered: 3, learning: 0, struggling: 1, total: 6 })).toEqual([{ kind: "mastered", count: 3 }, { kind: "struggling", count: 1 }]);
    expect(masteryLegend({ mastered: 0, learning: 0, struggling: 0, total: 4 })).toEqual([]);
  });

  it("the foot fact is the linked exam's countdown when it is still ahead", () => {
    expect(deckFact({ exam: exam("2026-11-21"), today, missing: 2 })).toEqual({ text: "Exam in 9 days", urgent: false });
    expect(deckFact({ exam: exam("2026-11-19"), today, missing: 0 })).toEqual({ text: "Exam in 7 days", urgent: true });
    expect(deckFact({ exam: exam("2026-11-13"), today, missing: 0 })).toEqual({ text: "Exam tomorrow", urgent: true });
    expect(deckFact({ exam: exam("2026-11-12"), today, missing: 0 })).toEqual({ text: "Exam today", urgent: true });
  });

  it("else the concepts that have no cards yet, else nothing", () => {
    expect(deckFact({ exam: exam("2026-11-01"), today, missing: 2 })).toEqual({ text: "2 concepts need cards", urgent: false });
    expect(deckFact({ exam: null, today, missing: 1 })).toEqual({ text: "1 concept needs cards", urgent: false });
    expect(deckFact({ exam: null, today, missing: 0 })).toBeNull();
    expect(deckFact({ exam: exam("2026-11-01"), today, missing: 0 })).toBeNull();
  });
});
