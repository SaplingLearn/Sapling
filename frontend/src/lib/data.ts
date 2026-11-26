import type { GraphNode as ApiNode } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import { LOOP_GOAL_MAX_TARGETS } from "@/lib/inputLimits";

export type Course = {
  id: string;
  course_code: string;
  name: string;
  color: string;
};

// Deterministic course palette used as a fallback when the backend doesn't
// supply a per-course color. SVG `fill=` and Three.js can't resolve
// `var(--…)`, so a missing color previously rendered black; this maps a
// stable seed to a hue.
//
// Each entry hits >=3:1 contrast against the cream `--bg` (#faf8f3) — the
// WCAG AA threshold for non-text UI elements. Sage and ochre were nudged
// darker (from #8a9a5b -> #7a874f and #c89c4a -> #a87d2e) so the nodes
// stay legible on the light theme. Brand --accent (#8a9a5b) remains
// unchanged elsewhere; this palette is only the backend-color fallback.
const COURSE_PALETTE = [
  "#7a874f", "#3e6f8a", "#7b4b99", "#b4562c",
  "#3f8a7c", "#a87d2e", "#a06b8e", "#6b8a3e",
];

// DJB2-ish string hash -> non-negative 32-bit integer. Shared by
// `paletteFor` (palette index seeding) and `lib/graph/nodeStyle`'s `shadeFor`
// (per-node HSL jitter seeding). Keep the body identical across consumers
// so the same input always maps to the same downstream color.
//
// UNSIGNED NORMALIZATION: `h` is a signed 32-bit int (the `| 0` keeps it in
// `[-2^31, 2^31)`), so its raw value can be negative. We coerce it to an
// unsigned 32-bit integer with `>>> 0`, which is always in `[0, 2^32)`. This
// gives consistent, deterministic indexing for every `% COURSE_PALETTE.length`
// and keeps the hash semantics identical across both consumers (the 2D
// `paletteFor` and `nodeStyle`'s `shadeFor`).
export function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h >>> 0;
}

export function paletteFor(seed: string | null | undefined): string {
  if (!seed) return COURSE_PALETTE[0];
  // `hashSeed` returns an unsigned 32-bit int, so the modulo is always
  // non-negative — no positive-modulo dance needed.
  return COURSE_PALETTE[hashSeed(seed) % COURSE_PALETTE.length];
}

export type GraphNode = {
  id: string;
  name: string;
  subject: string;
  color: string;
  is_subject_root?: boolean;
  mastery_tier: "mastered" | "learning" | "struggling" | "unexplored";
  mastery_score: number;
  course_id: string;
  description?: string;
  last_studied_at?: string;
  /** Present only on a skill graph (the loop on): `lib/levels.ts`. */
  skill?: number | null;
  skill_mastered?: boolean;
};

export type GraphEdge = {
  source: string;
  target: string;
  strength: number;
  /** Absent on synthesized course spokes and on older payloads. */
  relationship_type?: "related" | "prerequisite" | "builds_on" | "part_of";
};

// Deep-link from a knowledge-graph node into the AI Tutor (`/learn`).
//
// Subject-root (course) nodes carry the *course* name, which must never be
// sent as the session topic: doing so pre-selected the course name as a topic
// on redirect (#319). For a course node we scope the tutor to the course and
// leave the topic empty so the learner picks a concept; concept nodes seed
// their own name as the topic. The course is passed as `course` — the param
// the Learn screen reads (`searchParams.get("course")`); the earlier handlers
// passed `course_id`, which Learn silently ignored, dropping course scope.
// A concept node also names itself (`concept`, #866 K05): the learning loop's
// Tutor starts a session on that concept; the legacy Learn screen ignores it.
export function learnHrefForNode(
  n: Pick<GraphNode, "id" | "name" | "course_id" | "is_subject_root">,
  mode = "socratic",
): string {
  const p = new URLSearchParams();
  if (!n.is_subject_root) p.set("topic", n.name);
  if (!n.is_subject_root && n.id) p.set("concept", n.id);
  p.set("mode", mode);
  if (n.course_id) p.set("course", n.course_id);
  return `/learn?${p.toString()}`;
}

// Send to tutor's link (#866 K05): the note's title and course, the note itself
// (`note`), and its linked concepts (`concept`, comma-joined node ids), so the
// learning loop's session is on what the note is about; the legacy Learn
// screen ignores `concept`. Only the concepts of the course the link names go
// (the loop's goal refuses another course's), at most the goal's target cap,
// in linked order: a note linked across courses or past the cap still starts.
export function noteTutorHref(
  res: { topic?: string; course_id?: string | null },
  noteId: string,
  concepts: { id: string; courseId: string | null }[],
): string {
  const href = `/learn?topic=${encodeURIComponent(res.topic ?? "")}&course=${encodeURIComponent(res.course_id ?? "")}`
    + `&note=${encodeURIComponent(noteId)}`;
  const ids = res.course_id
    ? concepts.filter((c) => c.courseId === res.course_id).map((c) => c.id).slice(0, LOOP_GOAL_MAX_TARGETS)
    : [];
  return ids.length > 0 ? `${href}&concept=${encodeURIComponent(ids.join(","))}` : href;
}

// Adapter from the backend `ApiNode` shape to the frontend `GraphNode`
// shape consumed by `KnowledgeGraph`. Hoisted here from Tree/Learn/
// Dashboard so the three screens share a single source of truth.
export function apiToGraphNode(n: ApiNode, courses: EnrolledCourse[]): GraphNode {
  const course = courses.find((c) => c.course_name === n.subject);
  return {
    id: n.id,
    name: n.concept_name,
    subject: n.subject,
    // Resolved hex (not CSS custom property): `shadeFor` can only jitter a
    // hex base — a `var(--…)` passes through unshaded.
    // Seed prefers the course-record id so every node in the same family
    // hashes to the same palette color, even if some nodes arrive without
    // `n.course_id` set (round-2 fix — two siblings could otherwise land
    // on different fallback colors).
    color:
      n.course_color ||
      course?.color ||
      paletteFor(course?.course_id || n.course_id || n.subject),
    is_subject_root: n.is_subject_root,
    mastery_tier: n.mastery_tier === "subject_root" ? "mastered" : n.mastery_tier,
    mastery_score: n.mastery_score,
    course_id: n.course_id || course?.course_id || "",
    description: n.description || undefined,
    last_studied_at: n.last_studied_at || undefined,
    // Only a skill graph carries the key (`carriesSkill`), so its absence
    // keeps a loop-off node exactly as it was.
    ...(n.skill !== undefined ? { skill: n.skill, skill_mastered: !!n.skill_mastered } : {}),
  };
}

export type Assignment = {
  id: string;
  title: string;
  course_name: string;
  due_date: string;
  type: "homework" | "exam" | "reading" | "project" | "quiz";
  notes?: string;
};

export type Session = {
  id: string;
  topic: string;
  mode: "socratic" | "expository" | "teachback" | "quiz";
  course: string;
  started_at: string;
  messages: number;
};

export type Document = {
  id: string;
  name: string;
  category: "lecture_notes" | "syllabus" | "reading" | "slides" | "study_guide" | "assignment";
  course: string;
  created: string;
  summary: string;
  takeaways: string[];
};

export type Room = {
  id: string;
  name: string;
  invite_code: string;
  members: number;
  unread: number;
  lastMsg: string;
};

export type Flashcard = {
  id: string;
  topic: string;
  q: string;
  a: string;
  times_reviewed: number;
  last_rating?: "forgot" | "hard" | "good" | "easy";
};

export type Achievement = {
  id: string;
  name: string;
  description: string;
  category: "milestone" | "activity" | "social" | "special";
  rarity: "common" | "uncommon" | "rare" | "epic" | "legendary";
  icon: string;
  earnedAt?: string;
  progress?: number;
  isSecret?: boolean;
};
