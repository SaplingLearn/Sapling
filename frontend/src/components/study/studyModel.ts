/**
 * Pure derivations behind the Study hub (Sapling Study v2 design). Everything
 * the screen shows is computed here from real data, so the rules are testable
 * without rendering:
 *
 *  - Concepts come from the course's knowledge graph (`getGraph`). Status is the
 *    node's `mastery_tier`; mastery % is `mastery_score * 100`.
 *  - Prerequisites are `prerequisite` / `builds_on` edges, source -> target.
 *  - The graph has no category field, so roadmap columns are prerequisite
 *    LAYERS: depth 0 (nothing needed first) is "Foundations", then
 *    "Core Methods", "Building On", "Advanced", and everything deeper is "Goal".
 *    These are the design's own fallback labels for a course without categories.
 *  - Readiness = mean mastery % of the exam's concepts (assessments carry no
 *    concept list, so an exam covers every concept of its course).
 *  - "+N% this week" = the summed `node_mastery_events` deltas from the last 7
 *    days, averaged over the same concepts, in percentage points.
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
  mastered: "#4E8A3A",
  progress: "#D9A93A",
  review: "#C4534B",
  new: "#D6D0C3",
};
/** Status text colors. */
export const SC: Record<Status, string> = {
  mastered: "#3D7A2C",
  progress: "#8A6414",
  review: "#A8443F",
  new: "#6F6857",
};
export const STATUS_ORDER: Status[] = ["mastered", "progress", "review", "new"];
const W: Record<Status, number> = { mastered: 1, progress: 0.6, review: 0.3, new: 0 };
const STEP = ["Foundations", "Core Methods", "Building On", "Advanced", "Goal"];
const PREREQ_TYPES = new Set(["prerequisite", "builds_on"]);

const TIER: Record<string, Status> = {
  mastered: "mastered",
  learning: "progress",
  struggling: "review",
  unexplored: "new",
};

/* eslint-disable @typescript-eslint/no-explicit-any -- getGraph is untyped (any[]) */
export function conceptsForCourse(
  nodes: any[],
  edges: any[],
  courseId: string,
  now: Date = new Date(),
): Concept[] {
  const own = nodes.filter(n => n && n.course_id === courseId && !n.is_subject_root && n.mastery_tier !== "subject_root");
  const ids = new Set(own.map(n => String(n.id)));
  const pre: Record<string, string[]> = {};
  const post: Record<string, string[]> = {};
  for (const e of edges) {
    if (!e || !PREREQ_TYPES.has(e.relationship_type)) continue;
    const s = String(e.source), t = String(e.target);
    if (!ids.has(s) || !ids.has(t) || s === t) continue;
    pre[t] ||= [];
    post[s] ||= [];
    if (!pre[t].includes(s)) pre[t].push(s);
    if (!post[s].includes(t)) post[s].push(t);
  }
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
  const weekAgo = now.getTime() - 7 * 86400000;
  const base = own.map(n => {
    const id = String(n.id);
    const st: Status = TIER[n.mastery_tier] ?? "new";
    const score = Number(n.mastery_score) || 0;
    const events: any[] = Array.isArray(n.mastery_events) ? n.mastery_events : [];
    const weekDelta = events.reduce((sum, ev) => {
      const t = Date.parse(ev?.created_at ?? "");
      return Number.isFinite(t) && t >= weekAgo ? sum + (Number(ev.delta) || 0) : sum;
    }, 0);
    return {
      id,
      name: String(n.concept_name ?? ""),
      st,
      m: st === "new" ? 0 : Math.max(0, Math.min(100, Math.round(score * 100))),
      lastStudied: n.last_studied_at ?? null,
      pre: pre[id] || [],
      post: post[id] || [],
      step: d(id),
      group: "",
      gap: "",
      weekDelta,
    } as Concept;
  });
  const byId = new Map(base.map(c => [c.id, c]));
  for (const c of base) {
    c.group = STEP[Math.min(c.step, STEP.length - 1)];
    const weak = c.pre.filter(p => byId.get(p)?.st !== "mastered").map(p => byId.get(p)!.name);
    if (c.st !== "mastered" && weak.length) {
      const one = weak.length === 1;
      c.gap = `Based on ${weak.join(" and ")}, which ${one ? "isn't" : "aren't"} mastered yet. You can still start, but expect to revisit ${one ? "it" : "them"}.`;
    }
  }
  return base.sort((a, b) => a.step - b.step || a.name.localeCompare(b.name));
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/** Exams/quizzes vs homework, from the stored type or (for "other" rows) the title. */
export function classifyAssessment(rawType: string | null | undefined, title: string): AssessType {
  const t = (rawType || "").toLowerCase();
  if (t === "exam" || t === "midterm" || t === "final") return "Exam";
  if (t === "quiz") return "Quiz";
  if (t === "homework" || t === "project" || t === "reading" || t === "lab" || t === "assignment") return "Homework";
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
export const countFg = (n: number) => (n <= 3 ? "#A8443F" : n <= 7 ? "#8A6414" : "#6F6857");
export const scoreColor = (p: number) => (p >= 80 ? "#3D7A2C" : p >= 60 ? "#8A6414" : "#A8443F");

export function readiness(topics: Concept[]) {
  if (!topics.length) return { pct: 0, trend: 0 };
  const pct = Math.round(topics.reduce((n, t) => n + t.m, 0) / topics.length);
  const trend = Math.round((topics.reduce((n, t) => n + t.weekDelta, 0) / topics.length) * 100);
  return { pct, trend };
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

export interface PaceInput {
  examTitle: string;
  days: number;
  readiness: number;
  /** Readiness points gained over the last 7 days. */
  weekGain: number;
  /** Minutes studied over the last 7 days (all courses). */
  weekMinutes: number;
  nextConcept?: string;
}

const PACE_TARGET = 90;

/**
 * The AI pace pill. Projects readiness at the exam from the last week's real
 * rate (points/day), and when short of the 90% target converts the gap into
 * minutes per day using the observed points-per-minute. Returns null when
 * there's nothing honest to say (no exam ahead, or already at the target).
 */
export function pace(p: PaceInput): { ok: boolean; title: string; body: string } | null {
  if (p.days < 0 || p.readiness >= PACE_TARGET) return null;
  const when = p.days === 0 ? "today" : p.days === 1 ? "tomorrow" : `in ${p.days} days`;
  const perDay = Math.max(0, p.weekGain) / 7;
  const proj = Math.min(100, Math.round(p.readiness + perDay * Math.max(p.days, 0)));
  if (proj >= PACE_TARGET) {
    return {
      ok: true,
      title: `On pace for ${p.examTitle}`,
      body: `${p.examTitle} is ${when}. At your current pace you'll reach about ${proj}% readiness, above the ${PACE_TARGET}% target.`,
    };
  }
  const gap = PACE_TARGET - proj;
  if (perDay > 0 && p.weekMinutes > 0 && p.days > 0) {
    const pointsPerMin = p.weekGain / p.weekMinutes;
    const extra = Math.max(5, Math.round(gap / pointsPerMin / p.days / 5) * 5);
    const amount = extra >= 60 ? `${Math.round((extra / 60) * 10) / 10} more hours` : `${extra} more minutes`;
    return {
      ok: false,
      title: "You need to spend more time",
      body: `${p.examTitle} is ${when} and you're on track for about ${proj}% readiness. Plan on an average of ${amount} per day to reach ${PACE_TARGET}%.`,
    };
  }
  const start = p.nextConcept ? ` Start with ${p.nextConcept}.` : "";
  return {
    ok: false,
    title: "You need to spend more time",
    body: `${p.examTitle} is ${when} and you're at ${p.readiness}% readiness. Your mastery hasn't moved this week, so you're not on pace for ${PACE_TARGET}%.${start}`,
  };
}

export const ring = (m: number, r: number) => {
  const C = 2 * Math.PI * r;
  return `${((C * m) / 100).toFixed(1)} ${C.toFixed(1)}`;
};
