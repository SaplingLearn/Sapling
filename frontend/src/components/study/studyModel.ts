/**
 * Pure derivations behind the Study hub (Sapling Study v2 design). Everything
 * the screen shows is computed here from real data, so the rules are testable
 * without rendering:
 *
 *  - Concepts come from the course's knowledge graph (`getGraph`). Status is the
 *    node's `mastery_tier`; mastery % is `mastery_score * 100`.
 *  - Prerequisites are `prerequisite` / `builds_on` edges, source -> target.
 *  - Roadmap columns are the course's REAL categories: the topic checklist
 *    (`/api/topic-checklist`) is an evidence-grounded outline of the course's
 *    own materials, and its `node_id` links a topic to the graph node it
 *    describes. A concept's category is the name of its topic's root ancestor.
 *    The graph itself carries no category field, so when there is no usable
 *    outline the columns fall back to prerequisite LAYERS — depth 0 (nothing
 *    needed first) is "Foundations", then "Core Methods", "Building On",
 *    "Advanced", and deeper is "Goal". Those are the design's own fallback
 *    labels for a course without categories, never a claim about the course.
 *  - Readiness = mean mastery % of a set of concepts. An exam's set comes from
 *    the same topic checklist: a topic lists the assessments it is on
 *    (`assessments`, upcoming ones only) and the graph node it describes
 *    (`node_id`). When the checklist links the selected exam to at least one of
 *    the course's concepts, the readiness band is "Ready for <exam>" over those.
 *    Otherwise (no outline, a past exam, nothing linked) it is the whole
 *    course, and says so: "<course> Readiness".
 *  - "+N% this week" = the summed `node_mastery_events` deltas from the last 7
 *    days (the node's `week_delta`), averaged over the same concepts, in
 *    percentage points.
 */

export type Status = "mastered" | "progress" | "review" | "new";
export type AssessType = "Exam" | "Quiz" | "Homework";

export interface Concept {
  id: string;
  name: string;
  st: Status;
  /** Mastery 0..100. */
  m: number;
  lastStudied: string | null;
  pre: string[];
  post: string[];
  step: number;
  group: string;
  /** Sentence for an unmastered concept whose prerequisites aren't mastered. */
  gap: string;
  /** Mastery change over the last 7 days, 0..1 units. */
  weekDelta: number;
}

export interface Assessment {
  id: string;
  type: AssessType;
  /** The stored assignment_type, kept so an untouched row isn't rewritten. */
  rawType: string;
  title: string;
  /** YYYY-MM-DD */
  iso: string;
}

export const ST_LABEL: Record<Status, string> = {
  mastered: "Mastered",
  progress: "Learning",
  review: "Struggling",
  new: "Not Started",
};
/** Status fill colors (squares, rings, bars). */
export const TC: Record<Status, string> = {
  // The app's mastery-state tokens (globals.css), the same four the
  // Dashboard's mastery bar and legend use.
  mastered: "var(--state-mastery)",
  progress: "var(--state-progress)",
  review: "var(--state-struggle)",
  new: "var(--state-neutral)",
};
/** Status text colors. */
export const SC: Record<Status, string> = {
  mastered: "var(--sap-600)",
  progress: "var(--warn)",
  review: "var(--err)",
  new: "var(--text-muted)",
};
export const STATUS_ORDER: Status[] = ["mastered", "progress", "review", "new"];
const W: Record<Status, number> = { mastered: 1, progress: 0.6, review: 0.3, new: 0 };
const STEP = ["Foundations", "Core Methods", "Building On", "Advanced", "Goal"];
/** The column a concept falls into when the course has no usable outline. */
const layerLabel = (step: number) => STEP[Math.min(step, STEP.length - 1)];
/** Concepts the outline does not place. Always the last roadmap column. */
export const OTHER_GROUP = "Other";

/** The slice of a topic-checklist topic the roadmap needs. */
export interface CategoryTopic {
  id: string;
  name: string;
  parent_id: string | null;
  /** The graph node this topic describes, when the names matched. */
  node_id: string | null;
}

/**
 * Concept id -> category name, read off the course's topic checklist.
 *
 * A category is a topic's ROOT ancestor, and a root only counts when it
 * actually groups — it must be the parent of at least one other topic. A flat
 * outline (every topic a root) would otherwise put each concept in a column of
 * its own, which is noisier than no categories at all. Topics the graph never
 * matched (`node_id: null`) contribute nothing.
 */
export function categoriesFromChecklist(topics: CategoryTopic[]): Map<string, string> {
  const byId = new Map(topics.map(t => [t.id, t]));
  const groups = new Set(topics.map(t => t.parent_id).filter((p): p is string => !!p));
  const out = new Map<string, string>();
  for (const t of topics) {
    if (!t.node_id) continue;
    let root = t;
    const seen = new Set([t.id]);
    while (root.parent_id) {
      const up = byId.get(root.parent_id);
      // The server validates the hierarchy; a broken or cyclic one stops here
      // rather than hanging.
      if (!up || seen.has(up.id)) break;
      seen.add(up.id);
      root = up;
    }
    if (groups.has(root.id)) out.set(t.node_id, root.name);
  }
  return out;
}

/**
 * Roadmap column labels, left to right: by how deep into the course's
 * prerequisite chain the column's concepts sit (its mean depth), so a student
 * reads it as an order of work. The catch-all column is always last.
 *
 * Under the layer fallback a column IS a depth, so this is the identity order.
 */
export const roadmapGroups = (topics: Concept[]): string[] => {
  const depth = new Map<string, { sum: number; n: number }>();
  for (const t of topics) {
    const d = depth.get(t.group) || { sum: 0, n: 0 };
    depth.set(t.group, { sum: d.sum + t.step, n: d.n + 1 });
  }
  const mean = (label: string) => {
    const d = depth.get(label)!;
    return d.n ? d.sum / d.n : 0;
  };
  return [...depth.keys()].sort((a, b) => {
    if (a === OTHER_GROUP) return 1;
    if (b === OTHER_GROUP) return -1;
    return mean(a) - mean(b) || a.localeCompare(b);
  });
};
const PREREQ_TYPES = new Set(["prerequisite", "builds_on"]);

const TIER: Record<string, Status> = {
  mastered: "mastered",
  learning: "progress",
  struggling: "review",
  unexplored: "new",
};

/* eslint-disable @typescript-eslint/no-explicit-any -- getGraph is untyped (any[]) */
type Links = Record<string, string[]>;

/** Prerequisite links between the course's own concepts, each listed once. */
function prereqLinks(edges: any[], ids: Set<string>): { pre: Links; post: Links } {
  const pre: Links = {};
  const post: Links = {};
  const link = (map: Links, from: string, to: string) => {
    const list = (map[from] ||= []);
    if (!list.includes(to)) list.push(to);
  };
  for (const e of edges) {
    if (!e || !PREREQ_TYPES.has(e.relationship_type)) continue;
    const s = String(e.source), t = String(e.target);
    if (s === t || !ids.has(s) || !ids.has(t)) continue;
    link(pre, t, s);
    link(post, s, t);
  }
  return { pre, post };
}

/** A concept's depth in the prerequisite chain: 0 when nothing is needed first. */
function depthFinder(pre: Links): (id: string) => number {
  const depth: Record<string, number> = {};
  const visiting = new Set<string>();
  const d = (id: string): number => {
    if (depth[id] !== undefined) return depth[id];
    if (visiting.has(id)) return 0; // a cycle: treat the back edge as absent
    visiting.add(id);
    const ps = pre[id] || [];
    const v = ps.length ? 1 + Math.max(...ps.map(d)) : 0;
    visiting.delete(id);
    depth[id] = v;
    return v;
  };
  return d;
}

/** The summed mastery deltas of the events since `since` (0..1 units). */
function deltaSince(events: unknown, since: number): number {
  if (!Array.isArray(events)) return 0;
  return events.reduce((sum: number, ev: any) => {
    const t = Date.parse(ev?.created_at ?? "");
    return Number.isFinite(t) && t >= since ? sum + (Number(ev.delta) || 0) : sum;
  }, 0);
}

/**
 * A concept's mastery change over the last 7 days. The graph read sends it as
 * `week_delta`, summed over every event of the week. A payload without it
 * falls back to summing `mastery_events`, which holds only the node's last
 * five and so under-counts a busy week.
 */
const weekDeltaOf = (node: any, weekAgo: number): number =>
  typeof node.week_delta === "number" ? node.week_delta : deltaSince(node.mastery_events, weekAgo);

const masteryPct = (st: Status, score: unknown) =>
  st === "new" ? 0 : Math.max(0, Math.min(100, Math.round((Number(score) || 0) * 100)));

/** The sentence on an unmastered concept that rests on unmastered prerequisites. */
function gapSentence(weak: string[]): string {
  const one = weak.length === 1;
  return `Based on ${weak.join(" and ")}, which ${one ? "isn't" : "aren't"} mastered yet. You can still start, but expect to revisit ${one ? "it" : "them"}.`;
}

/** A concept's gap sentence, or "" when nothing unmastered sits under it. */
function gapFor(c: Concept, byId: Map<string, Concept>): string {
  if (c.st === "mastered") return "";
  const weak = c.pre.map(p => byId.get(p)!).filter(p => p.st !== "mastered").map(p => p.name);
  return weak.length ? gapSentence(weak) : "";
}

export function conceptsForCourse(
  nodes: any[],
  edges: any[],
  courseId: string,
  now: Date = new Date(),
  categories?: Map<string, string>,
): Concept[] {
  const own = nodes.filter(n => n && n.course_id === courseId && !n.is_subject_root && n.mastery_tier !== "subject_root");
  const { pre, post } = prereqLinks(edges, new Set(own.map(n => String(n.id))));
  const depth = depthFinder(pre);
  const weekAgo = now.getTime() - 7 * 86400000;
  const base = own.map((n): Concept => {
    const id = String(n.id);
    const st: Status = TIER[n.mastery_tier] ?? "new";
    return {
      id,
      name: String(n.concept_name ?? ""),
      st,
      m: masteryPct(st, n.mastery_score),
      lastStudied: n.last_studied_at ?? null,
      pre: pre[id] || [],
      post: post[id] || [],
      step: depth(id),
      group: "",
      gap: "",
      weekDelta: weekDeltaOf(n, weekAgo),
    };
  });
  const byId = new Map(base.map(c => [c.id, c]));
  // Real categories, but only when the outline speaks for this course: at
  // least half its concepts have to land in one. A checklist that matched a
  // handful of nodes would otherwise sweep the rest into one huge "Other"
  // column, which says less than the prerequisite layers do.
  const placed = categories ? base.filter(c => categories.has(c.id)).length : 0;
  const useCategories = placed > 0 && placed * 2 >= base.length;
  for (const c of base) {
    c.group = useCategories ? categories!.get(c.id) ?? OTHER_GROUP : layerLabel(c.step);
    c.gap = gapFor(c, byId);
  }
  return base.sort((a, b) => a.step - b.step || a.name.localeCompare(b.name));
}
/* eslint-enable @typescript-eslint/no-explicit-any */

const TYPE_BY_RAW = new Map<string, AssessType>([
  ["exam", "Exam"], ["midterm", "Exam"], ["final", "Exam"],
  ["quiz", "Quiz"],
  ["homework", "Homework"], ["project", "Homework"], ["reading", "Homework"], ["lab", "Homework"], ["assignment", "Homework"],
]);

/** Exams/quizzes vs homework, from the stored type or (for "other" rows) the title. */
export function classifyAssessment(rawType: string | null | undefined, title: string): AssessType {
  const known = TYPE_BY_RAW.get((rawType || "").toLowerCase());
  if (known) return known;
  if (/\b(midterm|final|exam)\b/i.test(title)) return "Exam";
  if (/\bquiz\b/i.test(title)) return "Quiz";
  return "Homework";
}

export const parseIso = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};
export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const daysTo = (iso: string, today: Date) =>
  Math.round((parseIso(iso).getTime() - startOfDay(today).getTime()) / 86400000);
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
/** "Fri, Nov 13" */
/** "Fri, Nov 13"; with `today`, a date in another year gets the year too ("Wed, Oct 15, 2025"). */
export const fmtDow = (iso: string, today?: Date) => {
  const d = parseIso(iso);
  const base = `${DOW[d.getDay()]}, ${MON[d.getMonth()]} ${d.getDate()}`;
  return today && d.getFullYear() !== today.getFullYear() ? `${base}, ${d.getFullYear()}` : base;
};
/** "Today" / "Yesterday" / "Nov 4" for a timestamp. */
export function fmtWhen(ts: string, today: Date): string {
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return "";
  const diff = Math.round((startOfDay(today).getTime() - startOfDay(t).getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return `${MON[t.getMonth()]} ${t.getDate()}`;
}
export const countdown = (n: number) => (n === 0 ? "Today" : n === 1 ? "Tomorrow" : `in ${n} days`);
export const countFg = (n: number) => (n <= 3 ? "var(--err)" : n <= 7 ? "var(--warn)" : "var(--text-muted)");
export const scoreColor = (p: number) => (p >= 80 ? "var(--sap-600)" : p >= 60 ? "var(--warn)" : "var(--err)");

export function readiness(topics: Concept[]) {
  if (!topics.length) return { pct: 0, trend: 0 };
  const pct = Math.round(topics.reduce((n, t) => n + t.m, 0) / topics.length);
  const trend = Math.round((topics.reduce((n, t) => n + t.weekDelta, 0) / topics.length) * 100);
  return { pct, trend };
}

/** The slice of a topic-checklist topic that ties a concept to an exam. */
export interface ExamTopic {
  /** The graph node this topic describes, when the names matched. */
  node_id: string | null;
  /** The assessments this topic is on. The server attaches upcoming ones only. */
  assessments?: { id: string }[] | null;
}

/**
 * The concepts an exam covers, per the course's topic checklist: the graph
 * nodes of the topics that list this exam. Empty when the outline says nothing
 * about it (no outline, a past exam, no topic linked, or none of the linked
 * topics matched a graph node).
 */
export function conceptIdsForExam(outline: ExamTopic[], examId: string | null | undefined): Set<string> {
  const out = new Set<string>();
  if (!examId) return out;
  for (const t of outline) {
    if (t.node_id && (t.assessments || []).some(a => a.id === examId)) out.add(t.node_id);
  }
  return out;
}

/**
 * What the readiness band speaks for, and the label that says so.
 *
 * The selected exam's own concepts when the outline links it to at least one
 * concept of this course: "Ready for <exam>". Otherwise every concept of the
 * course under the course's name, because a course-wide average under an
 * exam's title reads as a claim about that exam.
 */
export function readinessBand(
  topics: Concept[],
  outline: ExamTopic[],
  exam: { id: string; title: string } | null,
  courseLabel: string,
): { concepts: Concept[]; label: string } {
  if (!exam) return { concepts: topics, label: `${courseLabel} Mastery` };
  const ids = conceptIdsForExam(outline, exam.id);
  const covered = topics.filter(t => ids.has(t.id));
  return covered.length
    ? { concepts: covered, label: `Ready for ${exam.title}` }
    : { concepts: topics, label: `${courseLabel} Readiness` };
}

/** Up Next: struggling first, then learning, then not started; a not-started
 *  concept whose prerequisites aren't mastered goes last; ties by lowest mastery. */
export function studyQueue(topics: Concept[]): Concept[] {
  const rank: Record<Status, number> = { review: 0, progress: 1, new: 2, mastered: 3 };
  const blocked = (t: Concept) => (t.st === "new" && !!t.gap ? 1 : 0);
  return topics
    .filter(t => t.st !== "mastered")
    .sort((x, y) => blocked(x) - blocked(y) || rank[x.st] - rank[y.st] || x.m - y.m);
}

/** Squares order: mastered -> not started, higher mastery first. */
export const squaresOrder = (topics: Concept[]) =>
  [...topics].sort((p, q) => W[q.st] - W[p.st] || q.m - p.m);
export const barOrder = squaresOrder;

/** Quick Reviews: studied concepts that are stale (7+ days), struggling, or
 *  under 70%, most urgent first, at most 5. */
export function quickReviews(topics: Concept[], today: Date) {
  return topics
    .filter(t => t.st !== "new")
    .map(t => {
      const last = t.lastStudied ? Date.parse(t.lastStudied) : NaN;
      const ago = Number.isFinite(last)
        ? Math.max(0, Math.floor((startOfDay(today).getTime() - startOfDay(new Date(last)).getTime()) / 86400000))
        : 0;
      return { t, ago, score: ago * 3 + (100 - t.m) };
    })
    .filter(x => x.ago >= 7 || x.t.st === "review" || x.t.m < 70)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

export const ring = (m: number, r: number) => {
  const C = 2 * Math.PI * r;
  return `${((C * m) / 100).toFixed(1)} ${C.toFixed(1)}`;
};
