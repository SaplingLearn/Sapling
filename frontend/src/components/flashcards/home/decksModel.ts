/**
 * Pure derivations behind the Flashcards HOME: the hero's example prompts and
 * figures, and the decks under it.
 *
 * A DECK is what the home shows for something reviewable:
 *   - "due":  the cards due today, when due dates are tracked and some are due;
 *   - "all":  everything on the course's map, made for the student (not stored);
 *   - "set":  each saved set.
 * A deck is a list of concept NAMES (a set stores names; see flashcardsModel),
 * so two or more can be mixed by taking the union of their names.
 *
 * What a deck says about itself (the chips that peek at its concepts, the
 * mastery counts, the one fact at its foot) is decided by pure helpers in
 * flashcardsModel.
 *
 * Playing a saved set generates cards for its concepts that have none, like
 * Start in the builder. The "all" deck never generates: one press would pay to
 * make cards for every concept of the course that has none.
 */
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import {
  OTHER_GROUP,
  categoriesFromChecklist,
  daysTo,
  roadmapGroups,
  type CategoryTopic,
  type Concept,
} from "../../study/studyModel";
import {
  deckFact,
  masteryCounts,
  peekNames,
  plural,
  resolveSet,
  setMeta,
  setOptions,
  summarize,
  uniqueNames,
  type ExamRef,
  type HomeModel,
  type MasteryCounts,
  YOUR_OWN,
  hasName,
  type MapColumn,
} from "./flashcardsModel";

// ── colour ───────────────────────────────────────────────────────────────────

/** The deck palettes the stylesheet defines (home.module.css, [data-palette]). */
export const PALETTES = ["green", "blue", "amber", "plum", "clay"] as const;
export type Palette = (typeof PALETTES)[number];
/** The automatic decks keep one each: olive for "all", clay for "due". */
export const PALETTE_ALL: Palette = "green";
export const PALETTE_DUE: Palette = "clay";

/** The colours saved sets take, in order. Olive is not one of them: it is
 *  the "everything" deck's, which sits beside the newest set. */
export const SET_PALETTES: Palette[] = ["blue", "amber", "plum", "clay"];

/**
 * Each saved set's palette: the sets in the order they were made take the
 * colours in turn, so neighbours differ (a hash of the id gave three blues
 * out of five). It does not depend on the order the list
 * arrives in, and making a new set never recolours the others; deleting one
 * moves the sets made after it one colour along.
 */
export function setPalettes(sets: Pick<FlashcardSet, "id" | "created_at">[]): Map<string, Palette> {
  const made = [...sets].sort((a, b) =>
    (a.created_at || "").localeCompare(b.created_at || "") || a.id.localeCompare(b.id));
  return new Map(made.map((set, i) => [set.id, SET_PALETTES[i % SET_PALETTES.length]]));
}

/** A column of the builder's map has a colour too: the units take the set
 *  colours left to right, and "Your own" is olive. */
export function columnPalette(label: string, index: number): Palette {
  return label === YOUR_OWN ? PALETTE_ALL : SET_PALETTES[index % SET_PALETTES.length];
}

/** How the selection divides over the map's columns, for the tray's bar: one
 *  entry per column with anything ticked, in the map's order. */
export function selectionMix(columns: MapColumn[], selected: string[]): { palette: Palette; label: string; count: number }[] {
  return columns
    .map((col, i) => ({
      palette: columnPalette(col.label, i),
      label: col.label,
      count: col.items.filter(item => hasName(selected, item.name)).length,
    }))
    .filter(part => part.count > 0);
}

// ── decks ────────────────────────────────────────────────────────────────────

export interface Deck {
  id: string;
  kind: "set" | "all" | "due";
  name: string;
  /** The pill on the band: the set's exam, "everything", "due". */
  tag: string | null;
  /** "6 concepts · 24 cards" */
  meta: string;
  /** The concepts it reviews, as the map spells them. Empty for "due". */
  names: string[];
  /** The names Start may generate cards for when they have none. */
  generate: string[];
  cards: number;
  /** A few of the names in it, as chips, and how many more there are. */
  peek: { shown: string[]; more: number };
  mastery: MasteryCounts;
  /** The one fact at its foot, when there is one. */
  fact: { text: string; urgent: boolean } | null;
  palette: Palette;
  /** The saved set behind a "set" deck. */
  set: FlashcardSet | null;
  onlyDue: boolean;
  shuffle: boolean;
}

export const ALL_DECK_ID = "auto:all";
export const DUE_DECK_ID = "auto:due";

/** The decks of the home, in order: due, everything, then the saved sets. */
export function buildDecks(input: {
  /** null: the list could not be read. */
  sets: FlashcardSet[] | null;
  model: HomeModel;
  concepts: Concept[];
  exams: ExamRef[];
  courseLabel: string;
  today: Date;
}): Deck[] {
  const { sets, model, concepts, exams, courseLabel, today } = input;
  /** What every deck made of concepts says about them. */
  const about = (names: string[], exam: ExamRef | null) => {
    const sum = summarize(names, model.index, false);
    return {
      cards: sum.cards,
      peek: peekNames(names),
      mastery: masteryCounts(names, concepts),
      fact: deckFact({ exam, today, missing: sum.missing.length }),
    };
  };
  const decks: Deck[] = [];
  if (model.dueCards.length) {
    const topics = uniqueNames(model.dueCards.map(c => c.topic ?? ""));
    decks.push({
      id: DUE_DECK_ID, kind: "due", name: "Due today", tag: "due",
      meta: plural(model.dueCards.length, "card"),
      names: [], generate: [], cards: model.dueCards.length,
      peek: peekNames(topics), mastery: masteryCounts(topics, concepts), fact: null,
      palette: PALETTE_DUE, set: null, onlyDue: true, shuffle: true,
    });
  }
  const everything = model.columns.flatMap(col => col.items).filter(item => !item.custom).map(item => item.name);
  if (everything.length) {
    const said = about(everything, null);
    decks.push({
      id: ALL_DECK_ID, kind: "all", name: courseLabel ? `All of ${courseLabel}` : "All your cards", tag: "everything",
      meta: `${plural(everything.length, "concept")} · ${plural(said.cards, "card")}`,
      names: everything, generate: [], ...said,
      palette: PALETTE_ALL, set: null, onlyDue: false, shuffle: true,
    });
  }
  const palettes = setPalettes(sets ?? []);
  for (const set of sets ?? []) {
    const names = resolveSet(set.concepts, model.columns).names;
    const options = setOptions(set);
    const exam = exams.find(e => e.id === set.exam_id) ?? null;
    decks.push({
      id: set.id, kind: "set", name: set.name, tag: exam?.title ?? null,
      meta: setMeta(set, model.index),
      names, generate: names, ...about(names, exam),
      palette: palettes.get(set.id) ?? SET_PALETTES[0], set,
      onlyDue: options.onlyDue && model.index.showDue, shuffle: options.shuffle,
    });
  }
  return decks;
}

/** A deck that can be ticked to mix with others: one made of concepts. */
export const mixable = (deck: Deck) => deck.kind !== "due";

/** What ticked decks come to together: the union of their concepts (in the
 *  order first met), which of those Start may generate for, and the cards. */
export function mixOf(ticked: Deck[], model: HomeModel) {
  const names = uniqueNames(ticked.flatMap(deck => deck.names));
  const generate = uniqueNames(ticked.flatMap(deck => deck.generate));
  return { sets: ticked.length, names, generate, cards: summarize(names, model.index, false).cards };
}

/** Every name the student's saved sets hold: a card with no course whose topic
 *  is one of these belongs to this course (see `cardsInCourse`). */
export const namesInSets = (sets: FlashcardSet[] | null): string[] =>
  uniqueNames((sets ?? []).flatMap(set => set.concepts.filter((c): c is string => typeof c === "string")));

// ── the hero ─────────────────────────────────────────────────────────────────

/** The next exam still ahead (today counts), or null. `exams` is by date. */
export const nextExam = (exams: ExamRef[], today: Date): ExamRef | null =>
  exams.find(e => daysTo(e.iso, today) >= 0) ?? null;

/**
 * The map's first UNIT column, when its columns are the course's own units
 * (the outline's categories) and not the hub's fallback layers: a concept's
 * column is then the category the outline gives it.
 */
export function firstUnit(concepts: Concept[], outline: CategoryTopic[]): string | null {
  const categories = categoriesFromChecklist(outline);
  const units = new Set(concepts.filter(c => categories.get(c.id) === c.group).map(c => c.group));
  return roadmapGroups(concepts).find(label => label !== OTHER_GROUP && units.has(label)) ?? null;
}

/** The hero's "Try" chips, built from what the course really has. At most 4. */
export function examplePrompts(input: { exam: ExamRef | null; concepts: Concept[]; unit: string | null }): string[] {
  const { exam, concepts, unit } = input;
  const out: string[] = [];
  if (exam) out.push(`Everything on ${exam.title}`);
  if (concepts.some(c => c.st === "review")) out.push("What I'm struggling with");
  if (unit) out.push(`${unit} from scratch`);
  out.push("Just the basics");
  return out.slice(0, 4);
}
