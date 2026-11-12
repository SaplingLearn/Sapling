/**
 * Pure derivations for the Study hub's own panels, on top of ./studyModel.ts
 * (which turns the graph into concepts): the course's dated work and exam
 * tabs, the roadmap's columns, the Up Next block, Recent Activity and the
 * Exams and Deadlines editor. Nothing here renders or fetches, so every rule
 * the hub applies is testable on its own.
 */
import type { Assignment, EnrolledCourse, StudyGuideCacheEntry } from "@/lib/api";
import type { AttemptSummary } from "@/lib/quiz/types";
import {
  classifyAssessment,
  daysTo,
  fmtWhen,
  roadmapGroups,
  scoreColor,
  squaresOrder,
  TC,
  type Assessment,
  type AssessType,
  type Concept,
  type Status,
} from "./studyModel";

/** The slice of a flashcard the hub reads. */
export type FlashcardRow = {
  id: string;
  topic?: string | null;
  /** The course the card was made for; absent on cards from before cards carried one. */
  course_id?: string | null;
  last_reviewed_at?: string | null;
};

const DAY_MS = 86400000;
const nameKey = (name: string) => name.trim().toLowerCase();

/** What the hub calls a course in a line of text: its code, else its name. */
export const courseLabel = (course: Pick<EnrolledCourse, "course_code" | "course_name"> | null): string =>
  course?.course_code || course?.course_name || "";

// ── exams and deadlines ──────────────────────────────────────────────────────

/** A course's dated work, soonest first. Undated rows have nowhere to go. */
export function assessmentsForCourse(assignments: Assignment[], courseId: string): Assessment[] {
  return assignments
    .filter(a => a.course_id === courseId && a.due_date)
    .map(a => ({
      id: a.id,
      type: classifyAssessment(a.assignment_type, a.title),
      rawType: a.assignment_type || "",
      title: a.title,
      iso: String(a.due_date).slice(0, 10),
    }))
    .sort((p, q) => p.iso.localeCompare(q.iso));
}

/** Dated work still ahead (today counts). */
export const upcomingOf = (list: Assessment[], today: Date): Assessment[] =>
  list.filter(e => daysTo(e.iso, today) >= 0);

/** How many of those are due within the week: the bell's badge. */
export const dueThisWeek = (upcoming: Assessment[], today: Date): number =>
  upcoming.filter(e => daysTo(e.iso, today) <= 7).length;

/**
 * The exam tabs and the one that is selected.
 *
 * Every exam and quiz configured for the course gets a tab, past or not (a
 * date in Exams and Deadlines is enough); homework stays in the bell only. The
 * default tab is the next exam ahead, else the most recent one.
 */
export function examTabs(
  list: Assessment[],
  today: Date,
  selectedId: string | null,
): { exams: Assessment[]; exam: Assessment | null } {
  const exams = list.filter(e => e.type !== "Homework");
  const next = exams.find(e => daysTo(e.iso, today) >= 0) || exams[exams.length - 1] || null;
  return { exams, exam: exams.find(e => e.id === selectedId) || next };
}

// ── which concept the panels are about ───────────────────────────────────────

/**
 * The concepts the hub's panels follow. The Up Next block (`focus`) follows
 * the CLICKED concept, else the head of the study queue; the roadmap's
 * prerequisite highlight (`hot`) follows the hovered one, else the clicked. An
 * id that is not one of the course's concepts (a stale selection) is no one.
 */
export function conceptMarks(
  byId: Map<string, Concept>,
  queueHead: Concept | null,
  topicId: string | null,
  hoverId: string | null,
): { sel: Concept | null; rec: Concept | null; focus: Concept | null; hot: Concept | null } {
  const find = (id: string | null) => (id && byId.get(id)) || null;
  const sel = find(topicId);
  return { sel, rec: queueHead, focus: sel || queueHead, hot: find(hoverId) || sel };
}

/** The concepts one rests on, in the graph's order; unknown ids are dropped. */
export const prerequisitesOf = (concept: Concept | null, byId: Map<string, Concept>): Concept[] =>
  (concept?.pre || []).map(id => byId.get(id)).filter((t): t is Concept => !!t);

// ── flashcards per concept ───────────────────────────────────────────────────

/**
 * The cards that can count toward this course: a card made for a course
 * belongs to that course and no other (as on the Flashcards page), so a
 * same-named concept in another course does not lend its cards here. A card
 * with no course still goes by its topic alone.
 */
export const cardsOfCourse = (cards: FlashcardRow[], courseId: string): FlashcardRow[] =>
  cards.filter(c => !c.course_id || c.course_id === courseId);

/** Cards per concept name (case and outer spaces ignored). */
export function cardCounts(cards: FlashcardRow[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const c of cards) {
    if (!c.topic) continue;
    const key = nameKey(c.topic);
    out.set(key, (out.get(key) || 0) + 1);
  }
  return out;
}

export const cardsFor = (counts: Map<string, number>, name: string): number =>
  (name && counts.get(nameKey(name))) || 0;

// ── the Up Next block ────────────────────────────────────────────────────────

/** The mastery arc's colour on the dark Up Next block. */
export const FOCUS_ARC: Record<Status, string> = {
  mastered: "var(--sap-300)",
  progress: "#F0C75E",
  review: "#F08A80",
  new: "rgba(255,255,255,0.4)",
};

/** Room on the block's one prerequisite line, and what a chip takes of it. */
const CHIP_LINE = 230;
const MORE_CHIP = 80;
const chipWidth = (name: string) => 28 + name.length * 6.4 + 5;

/**
 * How many prerequisite chips fit that line before "+N more" (which needs
 * room of its own unless the chip is the last). Always at least one when
 * there are any, so the line never reads as just "+3 more".
 */
export function chipsThatFit(names: string[]): number {
  let k = 0;
  let used = 0;
  for (; k < names.length; k++) {
    const reserve = k < names.length - 1 ? MORE_CHIP : 0;
    if (used + chipWidth(names[k]) + reserve > CHIP_LINE) break;
    used += chipWidth(names[k]);
  }
  return Math.max(k, Math.min(1, names.length));
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** The flashcards action on the Up Next block, by how many cards exist. */
export const focusCardsLabel = (n: number) =>
  n ? `Review ${n} ${plural(n, "flashcard", "flashcards")}` : "Make flashcards";
/** The flashcards action in a roadmap tile's menu. */
export const tileCardsLabel = (n: number) => (n ? `${n} Flashcards` : "Make Flashcards");
/** The tooltip on a tile's "..." button: what its menu offers (no Quiz under hide_quiz). */
export const tileActionsHint = (quizShown: boolean) =>
  quizShown ? "Quiz or flashcards for this concept" : "Flashcards for this concept";

// ── roadmap ──────────────────────────────────────────────────────────────────

/** How a tile relates to the concept under the pointer (or the selected one). */
export type TileRelation = "" | "Needed First" | "Unlocks";

export interface RoadmapTile {
  t: Concept;
  isSel: boolean;
  isNext: boolean;
  rel: TileRelation;
  dim: boolean;
  /** Never folded away, even when mastered. */
  pin: boolean;
}

export interface RoadmapColumn {
  label: string;
  /** The column's key in the hub's open/closed map: course id + label. */
  key: string;
  open: boolean;
  shown: RoadmapTile[];
  /** The mastered tiles the closed column folds into "N more mastered". */
  hidden: RoadmapTile[];
  /** "mastered/total" */
  frac: string;
  /** One status colour per concept, most mastered first. */
  bars: string[];
}

export interface RoadmapMarks {
  /** The clicked concept. */
  sel: Concept | null;
  /** Up Next. */
  rec: Concept | null;
  /** The hovered concept, else the clicked one: whose prerequisites light up. */
  hot: Concept | null;
  /** The legend's status filter. */
  lvl: Status | null;
}

/** Tiles a column shows before it folds its mastered ones away. */
const COLUMN_LIMIT = 4;

function tileMaker(marks: RoadmapMarks): (t: Concept) => RoadmapTile {
  const { sel, rec, hot, lvl } = marks;
  const needed = new Set(hot?.pre);
  const unlocks = new Set(hot?.post);
  const pinned = new Set([...(sel?.pre || []), ...(sel?.post || [])]);
  const linked = needed.size > 0 || unlocks.size > 0;
  const relation = (id: string): TileRelation => {
    if (needed.has(id)) return "Needed First";
    return unlocks.has(id) ? "Unlocks" : "";
  };
  return t => {
    const isSel = sel?.id === t.id;
    const isNext = rec?.id === t.id;
    const other = !!hot && hot.id !== t.id;
    const rel = other ? relation(t.id) : "";
    const offLevel = !!lvl && t.st !== lvl;
    return {
      t, isSel, isNext, rel,
      dim: offLevel || (other && !rel && linked),
      pin: isSel || isNext || pinned.has(t.id),
    };
  };
}

/**
 * Which tiles of a long column stay when it is closed: everything unmastered
 * or pinned, topped up with mastered ones to COLUMN_LIMIT. `hidden` is the
 * rest whether or not the column is open (it is the "Show Less" count too).
 */
function foldColumn(tiles: RoadmapTile[], open: boolean): { shown: RoadmapTile[]; hidden: RoadmapTile[] } {
  if (tiles.length <= COLUMN_LIMIT) return { shown: tiles, hidden: [] };
  const keep = tiles.map(x => x.t.st !== "mastered" || x.pin);
  let kept = keep.filter(Boolean).length;
  for (let i = 0; i < tiles.length && kept < COLUMN_LIMIT; i++) {
    if (!keep[i]) { keep[i] = true; kept++; }
  }
  const hidden = tiles.filter((_, i) => !keep[i]);
  return { shown: open ? tiles : tiles.filter((_, i) => keep[i]), hidden };
}

/** The roadmap, column by column, in `roadmapGroups`' order. */
export function roadmapColumns(
  topics: Concept[],
  marks: RoadmapMarks,
  courseId: string,
  openCols: Record<string, boolean>,
): RoadmapColumn[] {
  const tile = tileMaker(marks);
  return roadmapGroups(topics).map(label => {
    const own = topics.filter(t => t.group === label);
    const key = courseId + label;
    const open = !!openCols[key];
    return {
      label, key, open,
      ...foldColumn(own.map(tile), open),
      frac: `${own.filter(t => t.st === "mastered").length}/${own.length}`,
      bars: squaresOrder(own).map(t => TC[t.st]),
    };
  });
}

// ── quick reviews ────────────────────────────────────────────────────────────

/** Minutes the Quick Reviews row allows per concept. A flat guess, not a
 *  measurement (the app records no per-concept review time), so it is always
 *  shown as one: "~4 min". */
const QUICK_REVIEW_MIN = 2;
export const quickReviewEstimate = (concepts: number) => `~${concepts * QUICK_REVIEW_MIN} min`;

// ── recent activity ──────────────────────────────────────────────────────────

/** Recent Activity: rows shown in the rail, and the most "Show all" reveals. */
export const RECENT_SHOWN = 4;
export const RECENT_MAX = 30;

export type RecentKind = "quiz" | "cards" | "guide";

export interface RecentRow {
  key: string;
  /** Epoch ms, for the newest-first order. */
  at: number;
  kind: RecentKind;
  title: string;
  meta: string;
  result: string;
  resultColor: string;
  /** Mastery change per concept, in percentage points. */
  chips: { id: string; name: string; delta: number }[];
}

const DIM = "var(--text-dim)";

/** Finished, scored quizzes on this course or on one of its concepts. */
function quizRows(attempts: AttemptSummary[], courseId: string, conceptIds: Set<string>, today: Date): RecentRow[] {
  const scored = attempts.filter(a => a.status === "completed" && a.score != null && !!a.total);
  const here = scored.filter(a => a.course_id === courseId || conceptIds.has(a.concept_node_id));
  return here.map(a => {
    const ts = a.completed_at || a.created_at;
    const pct = Math.round((a.score! / a.total!) * 100);
    const moved = a.mastery_delta != null && !!a.concept_name;
    return {
      key: `q${a.quiz_id}`, at: Date.parse(ts), kind: "quiz" as const,
      title: `${a.concept_name || "Concept"} Quiz`,
      meta: `Quiz · ${fmtWhen(ts, today)}`,
      result: `${pct}%`, resultColor: scoreColor(pct),
      chips: moved ? [{ id: a.concept_node_id, name: a.concept_name, delta: Math.round(a.mastery_delta! * 100) }] : [],
    };
  });
}

/**
 * Flashcard reviews, one row per deck per day. A card keeps only its LATEST
 * review, so a row counts the cards last reviewed that day, not every review.
 */
function deckRows(cards: FlashcardRow[], names: Set<string>, today: Date): RecentRow[] {
  const decks = new Map<string, { topic: string; n: number; at: number }>();
  for (const c of cards) {
    if (!c.last_reviewed_at || !c.topic || !names.has(nameKey(c.topic))) continue;
    const at = Date.parse(c.last_reviewed_at);
    const key = `${c.topic}|${new Date(at).toDateString()}`;
    const deck = decks.get(key) || { topic: c.topic, n: 0, at: 0 };
    decks.set(key, { topic: deck.topic, n: deck.n + 1, at: Math.max(deck.at, at) });
  }
  return [...decks].map(([key, d]) => ({
    key: `c${key}`, at: d.at, kind: "cards" as const, title: d.topic,
    // An unparseable date has no day to name; the row is dropped below anyway.
    meta: `Flashcards · ${Number.isFinite(d.at) ? fmtWhen(new Date(d.at).toISOString(), today) : ""}`,
    result: `${d.n} ${plural(d.n, "card", "cards")}`, resultColor: DIM, chips: [],
  }));
}

function guideRows(guides: StudyGuideCacheEntry[], courseId: string, today: Date): RecentRow[] {
  return guides.filter(g => g.course_id === courseId).map(g => ({
    key: `g${g.id}`, at: Date.parse(g.generated_at), kind: "guide" as const,
    title: `${g.exam_title || "Exam"} Study Guide`,
    meta: `Study Guide · ${fmtWhen(g.generated_at, today)}`,
    result: "", resultColor: DIM, chips: [],
  }));
}

/**
 * The course's Recent Activity, newest first, at most RECENT_MAX rows: its
 * finished quizzes, its flashcard reviews (decks named for one of its concepts
 * or for the course itself, less the cards made for another course) and its
 * study guides.
 */
export function recentActivity(input: {
  attempts: AttemptSummary[];
  cards: FlashcardRow[];
  guides: StudyGuideCacheEntry[];
  topics: Concept[];
  course: Pick<EnrolledCourse, "course_id" | "course_code" | "course_name"> | null;
  today: Date;
}): RecentRow[] {
  const { topics, course, today } = input;
  const courseId = course?.course_id || "";
  const deckNames = [...topics.map(t => t.name), course?.course_name || "", course?.course_code || ""];
  const rows = [
    ...quizRows(input.attempts, courseId, new Set(topics.map(t => t.id)), today),
    ...deckRows(cardsOfCourse(input.cards, courseId), new Set(deckNames.map(n => n.toLowerCase()).filter(Boolean)), today),
    ...guideRows(input.guides, courseId, today),
  ];
  return rows.filter(r => Number.isFinite(r.at)).sort((a, b) => b.at - a.at).slice(0, RECENT_MAX);
}

// ── the Exams and Deadlines editor ───────────────────────────────────────────

/** One row of the editor. `isNew` rows have no saved assignment behind them. */
export interface Draft {
  id: string;
  type: AssessType;
  title: string;
  iso: string;
  isNew?: boolean;
}

/** The `assignment_type` each editor type is stored as. */
export const TYPE_RAW: Record<AssessType, string> = { Exam: "exam", Quiz: "quiz", Homework: "homework" };

const pad2 = (n: number) => String(n).padStart(2, "0");

/** A blank row for the editor: an exam, a week out. `stamp` keeps its id unique. */
export function newDraft(today: Date, n: number, stamp: number = Date.now()): Draft {
  const d = new Date(today.getTime() + 7 * DAY_MS);
  const iso = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  return { id: `new-${stamp}-${n}`, type: "Exam", title: "", iso, isNew: true };
}

export const draftsOf = (list: Assessment[]): Draft[] =>
  list.map(e => ({ id: e.id, type: e.type, title: e.title, iso: e.iso }));

export type AssignmentPatch = Partial<Pick<Assignment, "title" | "due_date" | "assignment_type">>;

export interface DatesPlan {
  /** Saved rows the editor no longer has. */
  remove: string[];
  /** Saved rows whose title, date or type changed: only what changed. */
  update: { id: string; patch: AssignmentPatch }[];
  /** New rows, as the calendar's save takes them (less the course). */
  add: { title: string; due_date: string; assignment_type: string }[];
  /** The last exam or quiz among the new rows: the tab to open once saved. */
  addedExam: { title: string; iso: string } | null;
}

function patchFor(row: Draft, saved: Assessment): AssignmentPatch {
  const patch: AssignmentPatch = {};
  if (row.title !== saved.title) patch.title = row.title;
  if (row.iso !== saved.iso) patch.due_date = row.iso;
  // The stored type is only rewritten when the row changed class, so a
  // "midterm" stays a midterm rather than becoming a plain "exam".
  if (row.type !== saved.type) patch.assignment_type = TYPE_RAW[row.type];
  return patch;
}

/**
 * Every row with a name. A blank one becomes "<Type> <row number>", counting
 * on past any name another row already has: the calendar refuses a second
 * "Exam 1" on the same day as a duplicate, and would save nothing for it.
 */
function namedRows(drafts: Draft[]): Draft[] {
  const taken = new Set(drafts.map(d => nameKey(d.title)).filter(Boolean));
  return drafts.map((d, i) => {
    const typed = d.title.trim();
    if (typed) return { ...d, title: typed };
    let n = i + 1;
    while (taken.has(nameKey(`${d.type} ${n}`))) n++;
    taken.add(nameKey(`${d.type} ${n}`));
    return { ...d, title: `${d.type} ${n}` };
  });
}

/**
 * What saving the editor writes, against the rows it was OPENED with (never
 * the live list: rows that loaded while it was open were never shown, so they
 * are not "removed").
 */
export function planDates(drafts: Draft[], opened: Map<string, Assessment>): DatesPlan {
  const rows = namedRows(drafts);
  const saved = rows.filter(r => !r.isNew);
  const added = rows.filter(r => r.isNew);
  const kept = new Set(saved.map(r => r.id));
  const update = saved
    .filter(r => opened.has(r.id))
    .map(r => ({ id: r.id, patch: patchFor(r, opened.get(r.id)!) }))
    .filter(u => Object.keys(u.patch).length > 0);
  const lastExam = added.filter(r => r.type !== "Homework").pop();
  return {
    remove: [...opened.keys()].filter(id => !kept.has(id)),
    update,
    add: added.map(r => ({ title: r.title, due_date: r.iso, assignment_type: TYPE_RAW[r.type] })),
    addedExam: lastExam ? { title: lastExam.title, iso: lastExam.iso } : null,
  };
}

/** True when saving the plan would write nothing at all. */
export const planIsEmpty = (plan: DatesPlan): boolean =>
  plan.remove.length + plan.update.length + plan.add.length === 0;

/** What the calendar's save answers. Only `saved_count` is on older servers. */
export interface SaveReply {
  saved_count?: number;
  skipped_count?: number;
  skipped?: { title: string; due_date?: string | null; reason?: string }[];
}

const SKIP_REASON: Record<string, string> = {
  duplicate: "already on your calendar",
  no_enrollment: "not a course you are enrolled in",
};
const skipNote = (row: { title: string; reason?: string }) =>
  `"${row.title}" (${SKIP_REASON[row.reason || ""] || "not accepted"})`;

/**
 * What to tell the student after a save. The calendar can accept fewer new
 * rows than it was sent (a duplicate, a course the student is not enrolled
 * in); "Dates saved" is only said when every one went in. `reply` is the
 * answer to the new rows, null when there were none to send.
 */
export function saveOutcome(plan: DatesPlan, reply: SaveReply | null): { saved: boolean; message: string } {
  const asked = plan.add.length;
  const went = typeof reply?.saved_count === "number" ? reply.saved_count : asked;
  if (went >= asked) return { saved: true, message: "Dates saved" };
  const skipped = reply?.skipped || [];
  const missing = asked - went;
  const what = skipped.length
    ? `Not saved: ${skipped.map(skipNote).join(", ")}.`
    : `${missing} of ${asked} new ${plural(asked, "date was", "dates were")} not saved.`;
  const rest = went + plan.remove.length + plan.update.length > 0 ? " Your other changes were saved." : "";
  return { saved: false, message: what + rest };
}
