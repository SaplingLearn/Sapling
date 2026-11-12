/**
 * Pure derivations behind the Flashcards home (pick concepts, then review).
 * Everything the screen shows is computed here from real data, so the rules
 * are testable without rendering:
 *
 *  - A card belongs to a CONCEPT when its `topic` equals the concept's name
 *    (trimmed, case-insensitive) and the card is in the chosen course.
 *  - "In the chosen course" is the card's `course_id` when it has one. A card
 *    with NO course is placed by its topic instead (see `cardsInCourse`):
 *    every AI-generated card is one today, because the generate route stores
 *    no offering, and the Study hub counts a concept's cards by topic alone.
 *    Leaving them out would show "No cards yet" for decks the hub says exist,
 *    and Start would pay to generate them again.
 *  - Topics that are not one of the course's concepts (imported decks, decks
 *    named for the course, the old "A, B" decks made for several concepts at
 *    once) stay reachable in "Your own", the last column of the map. The same
 *    column holds the CUSTOM concepts a student adds by name: they have no
 *    cards until Start generates them, and they live in the draft (and in any
 *    set saved with them), not on the course's graph.
 *  - A card is DUE when its `due_at` is at or before now. When no card at all
 *    carries a `due_at`, due dates are not tracked: every due figure is hidden
 *    (`showDue: false`) rather than shown as zero.
 *  - A selection is a list of concept NAMES, which is also what a saved set
 *    stores and what the Study hub's deep link carries.
 *
 * The roadmap itself (columns, exam coverage) is the Study hub's, imported
 * from `study/studyModel`.
 */
import type { Assignment } from "@/lib/api";
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import {
  classifyAssessment,
  daysTo,
  roadmapGroups,
  type Concept,
  type Status,
} from "../../study/studyModel";

export interface Card {
  id: string;
  /** The abstract course the card belongs to (null: not tied to a course). */
  course_id?: string | null;
  topic?: string | null;
  front: string;
  back: string;
  /** When the card is next due for review (ISO). Absent: not scheduled. */
  due_at?: string | null;
}

/** How names are compared everywhere: trimmed, case-insensitive. */
export const normName = (name?: string | null) => (name ?? "").trim().toLowerCase();

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ── cards ────────────────────────────────────────────────────────────────────

/**
 * The chosen course's cards. No course chosen (a student with none): all.
 *
 * A card with a course belongs to that course and no other. A card with no
 * course belongs where its topic points: it names one of the course's
 * concepts, lists one ("Recursion, Sorting": what generating for several
 * concepts at once used to store), or mentions the course by name.
 */
export function cardsInCourse(
  cards: Card[],
  courseId: string,
  course: { name?: string | null; conceptNames: string[] } = { conceptNames: [] },
): Card[] {
  if (!courseId) return cards;
  const courseKey = normName(course.name);
  const conceptKeys = new Set(course.conceptNames.map(normName));
  const pointsHere = (topic?: string | null) => {
    const key = normName(topic);
    if (!key) return false;
    if (conceptKeys.has(key) || (!!courseKey && key.includes(courseKey))) return true;
    return key.split(",").some(part => conceptKeys.has(part.trim()));
  };
  return cards.filter(c => (c.course_id ? c.course_id === courseId : pointsHere(c.topic)));
}

export const hasDueData = (cards: Card[]) => cards.some(c => !!c.due_at);

export function isDue(card: Card, now: number): boolean {
  if (!card.due_at) return false;
  const at = Date.parse(card.due_at);
  return Number.isFinite(at) && at <= now;
}

export interface CardIndex {
  /** Normalised topic -> the cards a selection of that name reviews. */
  byKey: Map<string, Card[]>;
  /** Topics that are not one of the course's concepts, by name. */
  others: { key: string; name: string }[];
  now: number;
  showDue: boolean;
}

export function indexCards(
  courseCards: Card[],
  conceptNames: string[],
  when: { now: number; showDue: boolean },
): CardIndex {
  const conceptKeys = new Set(conceptNames.map(normName));
  const byKey = new Map<string, Card[]>();
  const otherNames = new Map<string, string>();
  for (const card of courseCards) {
    const key = normName(card.topic);
    if (!key) continue;
    const isConcept = conceptKeys.has(key);
    const list = byKey.get(key);
    if (list) list.push(card);
    else byKey.set(key, [card]);
    if (!isConcept && !otherNames.has(key)) otherNames.set(key, (card.topic ?? "").trim());
  }
  const others = [...otherNames]
    .map(([key, name]) => ({ key, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return { byKey, others, now: when.now, showDue: when.showDue };
}

export function countsFor(index: CardIndex, name: string): { cards: number; due: number } {
  const list = index.byKey.get(normName(name)) ?? [];
  const due = index.showDue ? list.filter(c => isDue(c, index.now)).length : 0;
  return { cards: list.length, due };
}

/** A tile's second line. */
export const cardsLabel = (cards: number, due: number) =>
  !cards ? "No cards yet" : due ? `${plural(cards, "card")} · ${due} due` : plural(cards, "card");

// ── the map ──────────────────────────────────────────────────────────────────

export interface MapItem {
  id: string;
  name: string;
  /** Mastery status of a concept; null for a deck that is not a concept. */
  status: Status | null;
  cards: number;
  due: number;
  /** Added by the student and not generated yet: it can be taken off again. */
  custom: boolean;
}

export interface MapColumn {
  label: string;
  items: MapItem[];
}

export const YOUR_OWN = "Your own";
/** The longest name a concept (and so a set's entry) may have. */
export const CONCEPT_NAME_MAX = 120;

/** A concept name as it may be stored: trimmed, 1-120 characters. */
export function validConceptName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const name = raw.trim();
  return name && name.length <= CONCEPT_NAME_MAX ? name : null;
}

/**
 * The hub's roadmap columns, each concept with its card counts, then "Your
 * own": the decks that are not concepts, and the custom concepts the student
 * added (those that are not on the map some other way already).
 */
export function mapColumns(concepts: Concept[], index: CardIndex, custom: string[] = []): MapColumn[] {
  const columns: MapColumn[] = roadmapGroups(concepts).map(label => ({
    label,
    items: concepts
      .filter(c => c.group === label)
      .map(c => ({ id: c.id, name: c.name, status: c.st, ...countsFor(index, c.name), custom: false })),
  }));
  const own: MapItem[] = index.others.map(o => ({
    id: `deck:${o.key}`, name: o.name, status: null, ...countsFor(index, o.name), custom: false,
  }));
  const taken = new Set([...concepts.map(c => normName(c.name)), ...index.others.map(o => o.key)]);
  for (const name of uniqueNames(custom)) {
    const key = normName(name);
    if (taken.has(key)) continue;
    own.push({ id: `own:${key}`, name, status: null, cards: 0, due: 0, custom: true });
  }
  if (own.length) columns.push({ label: YOUR_OWN, items: own });
  return columns;
}

/** Normalised name -> the name the map shows it under. */
function mapNames(columns: MapColumn[]): Map<string, string> {
  const known = new Map<string, string>();
  for (const col of columns) {
    for (const item of col.items) {
      const key = normName(item.name);
      if (!known.has(key)) known.set(key, item.name);
    }
  }
  return known;
}

/** The map's own spelling of a name it shows, or null. */
export const findOnMap = (name: string, columns: MapColumn[]) => mapNames(columns).get(normName(name)) ?? null;

/** Which of these names the map shows (under its spelling), and which not. */
export function namesOnMap(names: string[], columns: MapColumn[]): { found: string[]; missing: string[] } {
  const known = mapNames(columns);
  const found: string[] = [];
  const missing: string[] = [];
  for (const name of uniqueNames(names)) {
    const hit = known.get(normName(name));
    if (hit) found.push(hit);
    else missing.push(name);
  }
  return { found, missing };
}

// ── selection ────────────────────────────────────────────────────────────────

export function uniqueNames(names: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of names) {
    const key = normName(raw);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(raw.trim());
  }
  return out;
}

export const hasName = (selected: string[], name: string) => {
  const key = normName(name);
  return selected.some(n => normName(n) === key);
};

export const withNames = (selected: string[], names: string[]) => uniqueNames([...selected, ...names]);

export function withoutNames(selected: string[], names: string[]): string[] {
  const drop = new Set(names.map(normName));
  return selected.filter(n => !drop.has(normName(n)));
}

export function sameNames(a: string[], b: string[]): boolean {
  const left = new Set(a.map(normName));
  const right = new Set(b.map(normName));
  return left.size === right.size && [...left].every(k => right.has(k));
}

/** A column header's checkbox: all, none or some of its tiles are ticked. */
export function columnCheck(selected: string[], items: MapItem[]): { ticked: number; state: "all" | "none" | "some" } {
  const ticked = items.filter(item => hasName(selected, item.name)).length;
  const state = ticked === 0 ? "none" : ticked === items.length ? "all" : "some";
  return { ticked, state };
}

/** The tray's figures: how many concepts, how many cards a review would hold,
 *  and which ticked names have no cards at all (Start generates those). */
export function summarize(selected: string[], index: CardIndex, onlyDue: boolean) {
  let cards = 0;
  const missing: string[] = [];
  for (const name of selected) {
    const n = countsFor(index, name);
    cards += onlyDue ? n.due : n.cards;
    if (!n.cards) missing.push(name);
  }
  return { concepts: selected.length, cards, missing };
}

// ── exams ────────────────────────────────────────────────────────────────────

export interface ExamRef {
  id: string;
  title: string;
  /** YYYY-MM-DD */
  iso: string;
}

/** The course's dated exams and quizzes, soonest first (the hub's exam tabs). */
export function examsForCourse(assignments: Assignment[], courseId: string): ExamRef[] {
  return assignments
    .filter(a => a.course_id === courseId && !!a.due_date && classifyAssessment(a.assignment_type, a.title) !== "Homework")
    .map(a => ({ id: a.id, title: a.title, iso: String(a.due_date).slice(0, 10) }))
    .sort((p, q) => p.iso.localeCompare(q.iso));
}

// ── the deck ─────────────────────────────────────────────────────────────────

/** Fisher-Yates over a copy, with the random source handed in. */
export function shuffled<T>(items: readonly T[], random: () => number): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** The selection in the map's order (columns left to right, tiles top to
 *  bottom); names the map does not show keep their order at the end. */
export function orderNames(selected: string[], columns: MapColumn[]): string[] {
  const rank = new Map<string, number>();
  for (const col of columns) {
    for (const item of col.items) {
      const key = normName(item.name);
      if (!rank.has(key)) rank.set(key, rank.size);
    }
  }
  const at = (name: string) => rank.get(normName(name)) ?? Number.MAX_SAFE_INTEGER;
  return selected
    .map((name, i) => ({ name, i }))
    .sort((a, b) => at(a.name) - at(b.name) || a.i - b.i)
    .map(x => x.name);
}

/** The review deck for a selection: every card of the named concepts, in the
 *  order the names are given (or shuffled), only the due ones when asked. */
export function buildDeck(input: {
  names: string[];
  index: CardIndex;
  onlyDue: boolean;
  shuffle: boolean;
  random: () => number;
}): Card[] {
  const { names, index, onlyDue, shuffle, random } = input;
  const seen = new Set<string>();
  const deck: Card[] = [];
  for (const name of names) {
    for (const card of index.byKey.get(normName(name)) ?? []) {
      if (seen.has(card.id) || (onlyDue && !isDue(card, index.now))) continue;
      seen.add(card.id);
      deck.push(card);
    }
  }
  return shuffle ? shuffled(deck, random) : deck;
}

/** Why Start produced nothing to review. */
export function emptyDeckReason(onlyDue: boolean, triedToGenerate: boolean): string {
  if (onlyDue) return "Nothing in this selection is due right now.";
  if (triedToGenerate) return "No cards could be made for this selection, so there is nothing to review yet.";
  return "This selection has no cards to review.";
}

// ── saved sets ───────────────────────────────────────────────────────────────

/**
 * A saved set's concepts as the home shows them: the ones on the map under the
 * map's spelling, and the rest as CUSTOM concepts (a set stores names, and a
 * name that is not on the course map is one the student added). Only a blank
 * or over-long name is dropped.
 */
export function resolveSet(concepts: unknown[], columns: MapColumn[]): { names: string[]; custom: string[]; dropped: number } {
  const valid: string[] = [];
  let dropped = 0;
  for (const raw of concepts) {
    const name = validConceptName(raw);
    if (name) valid.push(name);
    else dropped++;
  }
  const known = mapNames(columns);
  const names: string[] = [];
  const custom: string[] = [];
  // The set's own order, whichever kind each name is.
  for (const name of uniqueNames(valid)) {
    const hit = known.get(normName(name));
    names.push(hit ?? name);
    if (!hit) custom.push(name);
  }
  return { names, custom, dropped };
}

/** What "Sort it" did, for the line under the field. */
export function describeNote(matched: number, considered: number): string {
  if (!matched) return "Nothing on this course's map matched that, so your selection is as it was. Try naming the concepts or the exam.";
  const total = Math.max(considered, matched);
  return `Sorted ${matched} of ${plural(total, "concept")} into this set. Tick or untick to adjust, then save.`;
}

/** "6 concepts · 24 cards · 9 due" */
export function setMeta(set: Pick<FlashcardSet, "concepts">, index: CardIndex): string {
  const names = uniqueNames(set.concepts);
  let cards = 0;
  let due = 0;
  for (const name of names) {
    const n = countsFor(index, name);
    cards += n.cards;
    due += n.due;
  }
  return [plural(names.length, "concept"), plural(cards, "card"), due ? `${due} due` : ""].filter(Boolean).join(" · ");
}

export const setOptions = (set: Pick<FlashcardSet, "options">) => ({
  onlyDue: set.options?.only_due ?? false,
  shuffle: set.options?.shuffle ?? true,
});

// ── the tray's draft ─────────────────────────────────────────────────────────

export type PerConcept = 3 | 5 | 10;
export const PER_CONCEPT: PerConcept[] = [3, 5, 10];

/** What the tray holds: the selection, its options, and the set it came from. */
export interface Draft {
  selected: string[];
  onlyDue: boolean;
  shuffle: boolean;
  perConcept: PerConcept;
  name: string;
  /** The saved set this selection was loaded from (or saved as). */
  setId: string | null;
  examId: string | null;
  /** Concepts the student added by name (or a loaded set named) that are not
   *  on the course map. Shown in "Your own" whether ticked or not. */
  custom: string[];
  /** The name the page last put in the name field itself (a loaded or saved
   *  set's, or a suggestion). A field that still holds it was not typed in. */
  givenName: string | null;
}

export const emptyDraft = (selected: string[] = []): Draft => ({
  selected: uniqueNames(selected),
  onlyDue: false,
  shuffle: true,
  perConcept: 5,
  name: "",
  setId: null,
  examId: null,
  // The URL's names: any that turn out not to be on the map show as custom.
  custom: uniqueNames(selected),
  givenName: null,
});

export type DraftAction =
  | { type: "toggle"; name: string }
  /** A column header, or a set's "Add": tick or untick several at once.
   *  `custom`: the ones among them that are not on the map. */
  | { type: "many"; names: string[]; on: boolean; custom?: string[] }
  /** "Add your own concept", and its remove control. */
  | { type: "custom"; name: string }
  | { type: "uncustom"; name: string }
  /** "Sort it": the described concepts that are on the map, and its name. */
  | { type: "describe"; names: string[]; name: string }
  | { type: "clear" }
  /** `names`: the set's concepts; `custom`: those not on the map. */
  | { type: "load"; set: FlashcardSet; names: string[]; custom: string[] }
  | { type: "option"; patch: Partial<Pick<Draft, "onlyDue" | "shuffle" | "perConcept">> }
  | { type: "name"; value: string }
  | { type: "saved"; set: FlashcardSet }
  | { type: "renamed"; set: FlashcardSet }
  | { type: "deleted"; setId: string }
  /** A builder read back after a reload (buildSession.ts). */
  | { type: "restore"; draft: Draft }
  | { type: "reset" };

/** A selection that was replaced wholesale is no longer the loaded set's. The
 *  set's name goes with it, unless the student has typed over it. */
function detached(draft: Draft, selected: string[], examId: string | null): Draft {
  const setsName = !!draft.setId && draft.name === draft.givenName;
  return {
    ...draft,
    selected,
    examId,
    setId: null,
    name: setsName ? "" : draft.name,
    givenName: setsName ? null : draft.givenName,
  };
}

const reselected = (draft: Draft, selected: string[]): Draft => ({
  ...draft,
  selected,
  examId: selected.length ? draft.examId : null,
});

/** A described selection is new (not a loaded set). Its suggested name fills
 *  the name field only when the field is empty or still holds a name the page
 *  put there: what the student typed is never overwritten. */
function described(draft: Draft, names: string[], suggestion: string): Draft {
  const base = detached(draft, uniqueNames(names), null);
  const typed = base.name.trim() !== "" && base.name !== base.givenName;
  const name = suggestion.trim();
  return typed || !name ? base : { ...base, name, givenName: name };
}

const loaded = (draft: Draft, set: FlashcardSet, names: string[], custom: string[]): Draft => ({
  ...draft,
  ...setOptions(set),
  selected: names,
  custom: withNames(draft.custom, custom),
  name: set.name,
  givenName: set.name,
  setId: set.id,
  examId: set.exam_id,
});

export function draftReducer(draft: Draft, action: DraftAction): Draft {
  switch (action.type) {
    case "toggle":
      return reselected(draft, hasName(draft.selected, action.name)
        ? withoutNames(draft.selected, [action.name])
        : withNames(draft.selected, [action.name]));
    case "many":
      return action.on
        ? { ...reselected(draft, withNames(draft.selected, action.names)), custom: withNames(draft.custom, action.custom ?? []) }
        : reselected(draft, withoutNames(draft.selected, action.names));
    case "custom":
      return { ...reselected(draft, withNames(draft.selected, [action.name])), custom: withNames(draft.custom, [action.name]) };
    case "uncustom":
      return { ...reselected(draft, withoutNames(draft.selected, [action.name])), custom: withoutNames(draft.custom, [action.name]) };
    case "describe":
      return described(draft, action.names, action.name);
    case "clear":
      return detached(draft, [], null);
    case "load":
      return loaded(draft, action.set, action.names, action.custom);
    case "option":
      return { ...draft, ...action.patch };
    case "name":
      return { ...draft, name: action.value };
    case "saved":
      return { ...draft, name: action.set.name, givenName: action.set.name, setId: action.set.id, examId: action.set.exam_id };
    case "renamed":
      return draft.setId === action.set.id ? { ...draft, name: action.set.name, givenName: action.set.name } : draft;
    case "deleted":
      return draft.setId === action.setId ? { ...draft, setId: null } : draft;
    case "restore":
      return action.draft;
    case "reset":
      return emptyDraft();
    default:
      return draft;
  }
}

/** What the review's header calls the deck: the set's name, the one concept,
 *  or how many concepts. */
export function deckTitle(draft: Pick<Draft, "name" | "selected">): string {
  const name = draft.name.trim();
  if (name) return name;
  return draft.selected.length === 1 ? draft.selected[0] : plural(draft.selected.length, "concept");
}

/** The draft differs from the saved set it was loaded from. */
export function draftChanged(set: FlashcardSet, draft: Draft): boolean {
  const saved = setOptions(set);
  return (
    draft.name.trim() !== set.name
    || !sameNames(draft.selected, set.concepts)
    || draft.onlyDue !== saved.onlyDue
    || draft.shuffle !== saved.shuffle
    || draft.examId !== set.exam_id
  );
}

export interface SaveState {
  /** "update" saves over the loaded set; "create" makes a new one. */
  mode: "create" | "update";
  label: "Save set" | "Update set";
  enabled: boolean;
  /** A loaded set was changed: it can also be kept and a copy saved. */
  canSaveAsNew: boolean;
}

/** What the tray's save button does for this draft. */
export function saveState(draft: Draft, sets: FlashcardSet[] | null): SaveState {
  const valid = draft.name.trim().length > 0 && draft.selected.length > 0;
  const loaded = (sets ?? []).find(s => s.id === draft.setId);
  if (!loaded) return { mode: "create", label: "Save set", enabled: valid, canSaveAsNew: false };
  if (!draftChanged(loaded, draft)) return { mode: "update", label: "Save set", enabled: false, canSaveAsNew: false };
  return { mode: "update", label: "Update set", enabled: valid, canSaveAsNew: valid };
}

/** The draft as the sets API stores it. */
export const draftPayload = (draft: Draft) => ({
  name: draft.name.trim(),
  concepts: draft.selected,
  options: { only_due: draft.onlyDue, shuffle: draft.shuffle },
  exam_id: draft.examId,
});

// ── what a deck on the home says about itself ────────────────────────────────

/** At most this many concept chips on a deck, in this many characters. */
export const PEEK_CHIPS = 3;
export const PEEK_CHARS = 36;

/**
 * A peek at what is in a deck: its first few concept names, and how many more
 * there are. The chips sit on one line that never wraps, so a name is only
 * shown when it fits whole within the line's budget of characters: long names
 * mean two chips, or one. (The first is always shown; the stylesheet shortens
 * it with an ellipsis if it alone is too long.)
 */
export function peekNames(names: string[], maxChips = PEEK_CHIPS, maxChars = PEEK_CHARS): { shown: string[]; more: number } {
  const all = uniqueNames(names);
  const shown: string[] = [];
  let used = 0;
  for (const name of all) {
    if (shown.length >= maxChips) break;
    if (shown.length > 0 && used + name.length > maxChars) break;
    shown.push(name);
    used += name.length;
  }
  return { shown, more: all.length - shown.length };
}

/** How many of a deck's concepts are mastered, being learned, struggled with.
 *  The rest of `total` is not started, or not a course concept. */
export interface MasteryCounts {
  mastered: number;
  learning: number;
  struggling: number;
  total: number;
}

export function masteryCounts(names: string[], concepts: Pick<Concept, "name" | "st">[]): MasteryCounts {
  const wanted = uniqueNames(names);
  const status = new Map(concepts.map(c => [normName(c.name), c.st]));
  const out: MasteryCounts = { mastered: 0, learning: 0, struggling: 0, total: wanted.length };
  for (const name of wanted) {
    const st = status.get(normName(name));
    if (st === "mastered") out.mastered += 1;
    else if (st === "progress") out.learning += 1;
    else if (st === "review") out.struggling += 1;
  }
  return out;
}

/** The legend under the bar: only the groups that have anything in them. */
export function masteryLegend(counts: MasteryCounts): { kind: "mastered" | "learning" | "struggling"; count: number }[] {
  return (["mastered", "learning", "struggling"] as const)
    .map(kind => ({ kind, count: counts[kind] }))
    .filter(part => part.count > 0);
}

/** A set's exam is this close: its countdown is shown as a warning. */
export const EXAM_SOON_DAYS = 7;

/**
 * The one fact at the foot of a deck, from what is really known: a linked
 * exam still ahead ("Exam in 9 days"), else concepts in it that have no cards
 * yet ("2 concepts need cards"), else nothing.
 */
export function deckFact(input: {
  /** The exam the set is for, when it has one. */
  exam: ExamRef | null;
  today: Date;
  /** How many of its concepts have no cards. */
  missing: number;
}): { text: string; urgent: boolean } | null {
  const days = input.exam ? daysTo(input.exam.iso, input.today) : -1;
  if (days >= 0) {
    const when = days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
    return { text: `Exam ${when}`, urgent: days <= EXAM_SOON_DAYS };
  }
  if (input.missing > 0) {
    return { text: `${plural(input.missing, "concept")} ${input.missing === 1 ? "needs" : "need"} cards`, urgent: false };
  }
  return null;
}

// ── everything the home shows, in one pass ───────────────────────────────────

export interface HomeModel {
  courseCards: Card[];
  index: CardIndex;
  columns: MapColumn[];
  /** Every due card in the course (empty when due dates are not tracked). */
  dueCards: Card[];
}

export function homeModel(input: {
  cards: Card[];
  courseId: string;
  courseName?: string | null;
  concepts: Concept[];
  /** The student's own concepts (the draft's): tiles in "Your own". */
  custom?: string[];
  /** Names the saved sets hold. They place cards like `custom`, without
   *  becoming tiles. */
  known?: string[];
  now: number;
}): HomeModel {
  const { cards, courseId, courseName, concepts, custom = [], known = [], now } = input;
  const conceptNames = concepts.map(c => c.name);
  // A card with no course is placed by its topic; a custom concept's name
  // (the draft's, or a saved set's) places its cards here as a course
  // concept's does.
  const courseCards = cardsInCourse(cards, courseId, { name: courseName, conceptNames: [...conceptNames, ...custom, ...known] });
  const showDue = hasDueData(cards);
  const index = indexCards(courseCards, conceptNames, { now, showDue });
  const columns = mapColumns(concepts, index, custom);
  const dueCards = showDue ? courseCards.filter(c => isDue(c, now)) : [];
  return { courseCards, index, columns, dueCards };
}
