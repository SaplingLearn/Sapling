/**
 * Pure derivations behind the Home screen (Sapling Home v2).
 *
 * Everything the design shows as a sentence or a count is computed here from
 * data the Dashboard already loads (graph, courses, assignments, sessions,
 * flashcards, notes, gamification). Nothing is stored: the "goal" and the
 * "you are here" concept are read off the prerequisite edges and mastery
 * tiers every render, so they move as the student does.
 */
import type { Assignment } from "@/lib/api";
import type { GraphEdge, GraphNode } from "@/lib/data";

export type Tier = GraphNode["mastery_tier"];
export type DatedAssignment = Assignment & { due_date: string };

const DAY_MS = 86_400_000;

/** A mastered concept untouched this long reads as "Needs a Refresh". */
export const REFRESH_AFTER_DAYS = 21;

/** Status vocabulary and colours, straight from the design. */
export const STATUS: Record<Tier, { word: string; bar: string; text: string; seg: string }> = {
  mastered: { word: "Mastered", bar: "#4E8A3A", text: "#3E6F2E", seg: "#4E8A3A" },
  learning: { word: "Learning", bar: "#D9A93A", text: "#8A6420", seg: "#D9A93A" },
  struggling: { word: "Struggling", bar: "#C4534B", text: "#A8443F", seg: "#C4534B" },
  unexplored: { word: "Not Started", bar: "#C9C3B6", text: "#6F6857", seg: "#E2DDD2" },
};

/** Node size / fill per tier: [mass 0..1 (drives radius), fill opacity]. */
export const TIER_LOOK: Record<Tier, [number, number]> = {
  mastered: [0.9, 1],
  learning: [0.55, 0.78],
  struggling: [0.3, 0.55],
  unexplored: [0.05, 0.28],
};

const TIER_ORDER: Record<Tier, number> = { mastered: 0, learning: 1, struggling: 2, unexplored: 3 };

// ── Dates ────────────────────────────────────────────────────────────────────

/** Local-calendar YYYY-MM-DD: the week row compares in the student's own day. */
export function localDayKey(d: Date | string | null | undefined): string | null {
  if (!d) return null;
  const date = typeof d === "string" ? new Date(d) : d;
  if (isNaN(date.getTime())) return null;
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${m}-${day}`;
}

/** A date-only due date means the END of that day in the student's zone. */
export function dueAtMs(due: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 23, 59, 59, 999).getTime();
  return new Date(due).getTime();
}

function startOfLocalDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** Whole calendar days from today to the due day (0 = today). */
export function daysUntil(due: string, nowMs: number): number {
  return Math.round((startOfLocalDay(dueAtMs(due)) - startOfLocalDay(nowMs)) / DAY_MS);
}

export function greetingPrefix(d: Date): string {
  const h = d.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

/** Monday-first week containing `today`. */
export function weekDaysOf(today: Date): Date[] {
  const start = new Date(today);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

const WEEKDAY_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Today", "Yesterday", a weekday within the week, else "Nov 3". */
export function sessionDayLabel(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diff = Math.round((startOfLocalDay(nowMs) - startOfLocalDay(t)) / DAY_MS);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  const d = new Date(t);
  if (diff < 7) return WEEKDAY_LONG[d.getDay()];
  return `${MONTH_SHORT[d.getMonth()]} ${d.getDate()}`;
}

export function editedLabel(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diff = Math.round((startOfLocalDay(nowMs) - startOfLocalDay(t)) / DAY_MS);
  if (diff <= 0) return "Edited today";
  if (diff === 1) return "Edited yesterday";
  if (diff < 7) return `Edited ${diff} days ago`;
  const d = new Date(t);
  return `Edited ${MONTH_SHORT[d.getMonth()]} ${d.getDate()}`;
}

// ── Colour helpers ───────────────────────────────────────────────────────────

const DEFAULT_RGB = "192,96,32";

/** "#C06020" → "192,96,32". Anything unparseable falls back to the design's orange. */
export function hexToRgb(hex: string | null | undefined): string {
  if (!hex) return DEFAULT_RGB;
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return DEFAULT_RGB;
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

/** The course colour darkened for text (the design's #C06020 → #A04E18). */
export function darkerRgb(rgb: string, f = 0.83): string {
  const [r, g, b] = rgb.split(",").map(Number);
  return `rgb(${Math.round(r * f)},${Math.round(g * f)},${Math.round(b * f)})`;
}

// ── Prerequisite structure ───────────────────────────────────────────────────

export type Prereqs = Map<string, string[]>;

/** id → the ids it is built on. "A prerequisite B" and "B builds_on A" both
 *  mean A comes first; `related` / `part_of` carry no order. */
export function buildPrereqs(nodes: GraphNode[], edges: GraphEdge[]): Prereqs {
  const ids = new Set(nodes.map((n) => n.id));
  const map: Prereqs = new Map();
  for (const e of edges) {
    if (e.relationship_type !== "prerequisite" && e.relationship_type !== "builds_on") continue;
    if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue;
    const list = map.get(e.target) ?? [];
    if (!list.includes(e.source)) list.push(e.source);
    map.set(e.target, list);
  }
  return map;
}

export function prereqsOf(id: string, prereqs: Prereqs): string[] {
  return prereqs.get(id) ?? [];
}

/** The concept plus everything it is (transitively) built on. Cycle-safe. */
export function chainOf(id: string, prereqs: Prereqs): Set<string> {
  const seen = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const x = stack.pop() as string;
    if (seen.has(x)) continue;
    seen.add(x);
    for (const p of prereqsOf(x, prereqs)) stack.push(p);
  }
  return seen;
}

export const isSolid = (n: GraphNode | undefined) => n?.mastery_tier === "mastered";

export function needsRefresh(n: GraphNode, nowMs: number): boolean {
  if (n.mastery_tier !== "mastered" || !n.last_studied_at) return false;
  const t = new Date(n.last_studied_at).getTime();
  return !isNaN(t) && nowMs - t > REFRESH_AFTER_DAYS * DAY_MS;
}

/** Not started, and everything it needs is mastered. */
export function isReady(n: GraphNode, byId: Map<string, GraphNode>, prereqs: Prereqs): boolean {
  return n.mastery_tier === "unexplored" && prereqsOf(n.id, prereqs).every((p) => isSolid(byId.get(p)));
}

/** Per-course "where am I going / where am I" read off the graph. */
export type CourseFocus = {
  goalId: string | null;
  hereId: string | null;
  /** Unmastered chain concepts in learning order; `here` is one of them. */
  steps: string[];
};

/**
 * The goal is the concept with the deepest foundation that isn't mastered
 * yet (the furthest thing this course is building towards); "here" is the
 * first open step on the way to it whose prerequisites are all mastered.
 */
export function courseFocus(courseNodes: GraphNode[], prereqs: Prereqs): CourseFocus {
  const concepts = courseNodes.filter((n) => !n.is_subject_root);
  if (!concepts.length) return { goalId: null, hereId: null, steps: [] };
  const byId = new Map(concepts.map((n) => [n.id, n]));
  const depth = new Map(concepts.map((n) => [n.id, chainOf(n.id, prereqs).size]));
  const byDepth = (a: GraphNode, b: GraphNode) =>
    (depth.get(b.id) ?? 0) - (depth.get(a.id) ?? 0) ||
    a.mastery_score - b.mastery_score ||
    a.name.localeCompare(b.name);
  const open = concepts.filter((n) => !isSolid(n));
  const goal = (open.length ? [...open] : [...concepts]).sort(byDepth)[0];

  const chain = chainOf(goal.id, prereqs);
  const steps = [...chain]
    .map((id) => byId.get(id))
    .filter((n): n is GraphNode => !!n && !isSolid(n))
    .sort((a, b) => (depth.get(a.id) ?? 0) - (depth.get(b.id) ?? 0) || a.name.localeCompare(b.name))
    .map((n) => n.id);

  const frontier = steps
    .map((id) => byId.get(id) as GraphNode)
    .filter((n) => prereqsOf(n.id, prereqs).every((p) => !byId.has(p) || isSolid(byId.get(p))));
  const started = frontier.filter((n) => n.mastery_tier === "learning" || n.mastery_tier === "struggling");
  const here = (started.length ? started : frontier)[0] ?? null;
  return { goalId: goal.id, hereId: here?.id ?? null, steps };
}

// ── Assignments → pills, Coming Up, Roadmap ──────────────────────────────────

const EXAM_TYPES = new Set(["exam", "midterm", "final", "quiz"]);

export function isExam(a: Pick<Assignment, "assignment_type" | "title">): boolean {
  const t = (a.assignment_type || "").toLowerCase();
  return EXAM_TYPES.has(t) || (!t && /\b(midterm|final|exam)\b/i.test(a.title));
}

/** Pills only for what's close: an exam within two weeks, a deadline within one. */
export const EXAM_PILL_DAYS = 14;
export const DEADLINE_PILL_DAYS = 7;

export type Pill = { kind: "exam" | "deadline"; text: string; courseId: string | null; id: string };

function inDays(d: number): string {
  return d <= 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} days`;
}

export function notificationPills(assignments: DatedAssignment[], nowMs: number): Pill[] {
  const upcoming = assignments
    .filter((a) => dueAtMs(a.due_date) >= nowMs)
    .sort((a, b) => dueAtMs(a.due_date) - dueAtMs(b.due_date));
  const pills: Pill[] = [];
  const exam = upcoming.find((a) => isExam(a) && daysUntil(a.due_date, nowMs) <= EXAM_PILL_DAYS);
  if (exam) {
    pills.push({ kind: "exam", id: exam.id, courseId: exam.course_id ?? null, text: `${exam.title} ${inDays(daysUntil(exam.due_date, nowMs))}` });
  }
  const due = upcoming.find((a) => !isExam(a) && daysUntil(a.due_date, nowMs) <= DEADLINE_PILL_DAYS);
  if (due) {
    pills.push({ kind: "deadline", id: due.id, courseId: due.course_id ?? null, text: `${due.title} due ${inDays(daysUntil(due.due_date, nowMs))}` });
  }
  return pills;
}

const DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function dueDateParts(due: string): { dow: string; day: string; short: string } {
  const d = new Date(dueAtMs(due));
  return { dow: DOW[d.getDay()], day: String(d.getDate()), short: DOW_SHORT[d.getDay()] };
}

// ── Roadmap ──────────────────────────────────────────────────────────────────

export type RoadmapRow = { key: string; title: string; count: string; segs: string[]; note: string };

/** Max segments in one bar; longer lists are sampled so the bar stays legible. */
const MAX_SEGS = 16;

function segmentsFor(nodes: GraphNode[]): string[] {
  const sorted = [...nodes].sort((a, b) => TIER_ORDER[a.mastery_tier] - TIER_ORDER[b.mastery_tier]);
  if (sorted.length <= MAX_SEGS) return sorted.map((n) => STATUS[n.mastery_tier].seg);
  return Array.from({ length: MAX_SEGS }, (_, i) =>
    STATUS[sorted[Math.floor(((i + 0.5) * sorted.length) / MAX_SEGS)].mastery_tier].seg,
  );
}

function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function goalRow(focus: CourseFocus, byId: Map<string, GraphNode>, prereqs: Prereqs): RoadmapRow | null {
  const goal = focus.goalId ? byId.get(focus.goalId) : undefined;
  if (!goal) return null;
  const chain = [...chainOf(goal.id, prereqs)].map((id) => byId.get(id)).filter((n): n is GraphNode => !!n);
  const solid = chain.filter(isSolid).length;
  const openPrereqs = prereqsOf(goal.id, prereqs)
    .map((id) => byId.get(id))
    .filter((n): n is GraphNode => !!n && !isSolid(n) && n.id !== focus.hereId)
    .slice(0, 2)
    .map((n) => n.name);
  const here = focus.hereId ? byId.get(focus.hereId) : undefined;
  const note = isSolid(goal)
    ? "Goal reached. Review now and then to keep it fresh."
    : openPrereqs.length
      ? `Learn ${listNames(openPrereqs)} first.`
      : here && here.id !== goal.id
        ? `${here.name} is the next step.`
        : `You're ready to learn ${goal.name}.`;
  return { key: `goal-${goal.id}`, title: `Goal: ${goal.name}`, count: `${solid} of ${chain.length} solid`, segs: segmentsFor(chain), note };
}

export function examRow(exam: DatedAssignment, courseNodes: GraphNode[], courseLabel: string | null): RoadmapRow | null {
  const concepts = courseNodes.filter((n) => !n.is_subject_root);
  if (!concepts.length) return null;
  const ready = concepts.filter(isSolid).length;
  const weakest = concepts
    .filter((n) => !isSolid(n))
    .sort((a, b) => b.mastery_score - a.mastery_score || a.name.localeCompare(b.name));
  const share = ready / concepts.length;
  const note = !weakest.length
    ? "Everything is mastered. Review to keep it fresh."
    : share >= 0.6
      ? `On track. ${weakest[0].name} is the one to lock in.`
      : `${concepts.length - ready} concepts to go. Start with ${weakest[weakest.length - 1].name}.`;
  const title = [courseLabel, exam.title].filter(Boolean).join(" ") + ` · ${dueDateParts(exam.due_date).short}`;
  return { key: `exam-${exam.id}`, title, count: `${ready} of ${concepts.length} ready`, segs: segmentsFor(concepts), note };
}

// ── Flashcards → Quick Reviews ───────────────────────────────────────────────

export type CardLike = {
  topic?: string | null;
  times_reviewed?: number | null;
  last_rating?: number | string | null;
  last_reviewed_at?: string | null;
};

/** Days until a card comes back, by its last rating (1 forgot, 2 hard, 3 easy). */
const REVIEW_INTERVAL_DAYS: Record<number, number> = { 1: 1, 2: 3, 3: 7 };

export function isCardDue(c: CardLike, nowMs: number): boolean {
  if (!c.times_reviewed || !c.last_reviewed_at) return true;
  const t = new Date(c.last_reviewed_at).getTime();
  if (isNaN(t)) return true;
  const interval = REVIEW_INTERVAL_DAYS[Number(c.last_rating)] ?? 1;
  return nowMs - t >= interval * DAY_MS;
}

/** Distinct concepts (card topics) with at least one card due. */
export function dueReviewConcepts(cards: CardLike[], nowMs: number): number {
  const topics = new Set<string>();
  for (const c of cards) {
    if (isCardDue(c, nowMs)) topics.add((c.topic || "").trim().toLowerCase());
  }
  return topics.size;
}

// ── Quote ────────────────────────────────────────────────────────────────────

/**
 * The original Home's rotating learning quotes (pre-v3 Dashboard), written as
 * `“text” Author` so `splitQuote` can set the attribution in the v3 style. One
 * is picked at random per visit; test mode pins QUOTES[0] (see Dashboard).
 */
export const QUOTES = [
  "“Learning is the only thing the mind never exhausts, never fears, and never regrets.” da Vinci",
  "“The roots of education are bitter, but the fruit is sweet.” Aristotle",
  "“Live as if you were to die tomorrow. Learn as if you were to live forever.” Gandhi",
  "“An investment in knowledge pays the best interest.” Franklin",
  "“The beautiful thing about learning is that no one can take it away from you.” B.B. King",
  "“Tell me and I forget. Teach me and I remember. Involve me and I learn.” Franklin",
] as const;

/** Split `“text” Author` into its text and attribution, as the design does. */
export function splitQuote(q: string): { text: string; by: string } {
  const m = q.match(/^(.*[”"])\s+([^”"]+)$/);
  return m ? { text: m[1], by: m[2] } : { text: q, by: "" };
}

