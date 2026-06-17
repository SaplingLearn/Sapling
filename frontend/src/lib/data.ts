import type { GraphNode as ApiNode } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";

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
// `paletteFor` (palette index seeding) and `KnowledgeGraph3D`'s `shadeFor`
// (per-node HSL jitter seeding). Keep the body identical across consumers
// so the same input always maps to the same downstream color.
//
// OVERFLOW SAFETY: the naive `Math.abs(h)` is broken — `Math.abs(-2^31)`
// stays NEGATIVE (the value has no positive 32-bit counterpart), which
// would produce a negative array index and an `undefined` color. We coerce
// to an unsigned 32-bit integer with `>>> 0` instead, which is always in
// `[0, 2^32)`, so every `% COURSE_PALETTE.length` is non-negative.
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
  last_studied_at?: string;
};

export type GraphEdge = {
  source: string;
  target: string;
  strength: number;
};

// Adapter from the backend `ApiNode` shape to the frontend `GraphNode`
// shape consumed by `KnowledgeGraph`. Hoisted here from Tree/Learn/
// Dashboard so the three screens share a single source of truth.
export function apiToGraphNode(n: ApiNode, courses: EnrolledCourse[]): GraphNode {
  const course = courses.find((c) => c.course_name === n.subject);
  return {
    id: n.id,
    name: n.concept_name,
    subject: n.subject,
    // Resolved hex (not CSS custom property): the 3D KnowledgeGraph feeds
    // this into Three.js which can't resolve `var(--…)`.
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
    last_studied_at: n.last_studied_at || undefined,
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

const COURSES: Course[] = [
  { id: "c1", course_code: "CS 131", name: "Algorithms", color: "#4e873c" },
  { id: "c2", course_code: "MATH 242", name: "Linear Algebra", color: "#3e6f8a" },
  { id: "c3", course_code: "PHIL 150", name: "Philosophy of Mind", color: "#7b4b99" },
  { id: "c4", course_code: "BIO 108", name: "Molecular Biology", color: "#b4562c" },
];

const tiers: GraphNode["mastery_tier"][] = ["mastered", "learning", "struggling", "unexplored"];

const concepts: [string, string[]][] = [
  ["Algorithms", ["Dynamic Programming", "Greedy Algorithms", "Graph Traversal", "Divide & Conquer", "Hashing", "Big-O Analysis", "Sorting Networks", "NP-Completeness", "Amortized Analysis", "Union-Find"]],
  ["Linear Algebra", ["Eigenvalues", "Vector Spaces", "Determinants", "Linear Maps", "Orthogonality", "SVD", "Matrix Factorization", "Rank & Nullity"]],
  ["Philosophy of Mind", ["Qualia", "Functionalism", "Mind-Body Problem", "Intentionality", "Consciousness", "Identity Theory"]],
  ["Molecular Biology", ["Transcription", "DNA Replication", "Protein Folding", "mRNA Splicing", "CRISPR", "Lipid Bilayers", "Ribosomes"]],
];

// Deterministic PRNG so SSR/CSR match
function seeded(seed: number) {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function buildGraph() {
  const rand = seeded(42);
  const nodes: GraphNode[] = [];
  COURSES.forEach((c) => {
    nodes.push({
      id: c.id + "_root",
      name: c.name,
      subject: c.name,
      color: c.color,
      is_subject_root: true,
      mastery_tier: "mastered",
      mastery_score: 1,
      course_id: c.id,
    });
  });
  concepts.forEach(([sub, list]) => {
    const course = COURSES.find((c) => c.name === sub)!;
    list.forEach((n, i) => {
      const tier = tiers[Math.floor(rand() * 4)];
      const score =
        tier === "mastered"
          ? 0.85 + rand() * 0.15
          : tier === "learning"
            ? 0.45 + rand() * 0.3
            : tier === "struggling"
              ? 0.15 + rand() * 0.25
              : rand() * 0.1;
      nodes.push({
        id: `${course.id}_${i}`,
        name: n,
        subject: sub,
        color: course.color,
        mastery_tier: tier,
        mastery_score: score,
        course_id: course.id,
        last_studied_at: ["today", "yesterday", "3d ago", "1w ago", "never"][Math.floor(rand() * 5)],
      });
    });
  });
  const edges: GraphEdge[] = [];
  COURSES.forEach((c) => {
    const kids = nodes.filter((n) => n.subject === c.name && !n.is_subject_root);
    kids.forEach((k) => edges.push({ source: c.id + "_root", target: k.id, strength: 0.8 }));
    for (let i = 0; i < kids.length - 1; i++) {
      if (rand() > 0.5) edges.push({ source: kids[i].id, target: kids[i + 1].id, strength: 0.4 + rand() * 0.4 });
    }
  });
  return { nodes, edges };
}

const { nodes, edges } = buildGraph();

const assignments: Assignment[] = [
  { id: "a1", title: "Problem Set 6: DP", course_name: "Algorithms", due_date: "2026-04-21", type: "homework", notes: "Ch. 15" },
  { id: "a2", title: "Midterm II", course_name: "Linear Algebra", due_date: "2026-04-24", type: "exam", notes: "SVD emphasis" },
  { id: "a3", title: "Reading Response", course_name: "Philosophy of Mind", due_date: "2026-04-22", type: "reading", notes: "Dennett ch.3" },
  { id: "a4", title: "Lab Report 4", course_name: "Molecular Biology", due_date: "2026-04-28", type: "project", notes: "CRISPR screen" },
  { id: "a5", title: "Quiz: Graph Algos", course_name: "Algorithms", due_date: "2026-04-20", type: "quiz" },
];

const sessions: Session[] = [
  { id: "s1", topic: "Dynamic Programming", mode: "socratic", course: "Algorithms", started_at: "2h ago", messages: 14 },
  { id: "s2", topic: "SVD", mode: "expository", course: "Linear Algebra", started_at: "yesterday", messages: 22 },
  { id: "s3", topic: "Qualia", mode: "teachback", course: "Philosophy of Mind", started_at: "3d ago", messages: 9 },
];

const documents: Document[] = [
  { id: "d1", name: "CS131-Lecture-12-DP.pdf", category: "lecture_notes", course: "Algorithms", created: "3d ago", summary: "Introduction to dynamic programming: memoization, bottom-up table construction, optimal substructure.", takeaways: ["Memoization vs tabulation", "Knapsack variants", "LCS via DP table"] },
  { id: "d2", name: "Syllabus-Spring.pdf", category: "syllabus", course: "Linear Algebra", created: "2w ago", summary: "Course overview: linear maps, eigenvalue decomposition, SVD.", takeaways: ["2 midterms + final", "Weekly problem sets"] },
  { id: "d3", name: "Chapter-3-Consciousness.pdf", category: "reading", course: "Philosophy of Mind", created: "5d ago", summary: "Dennett on heterophenomenology.", takeaways: ["First-person vs third-person", "Zombie thought experiment"] },
  { id: "d4", name: "CRISPR-slides.pptx", category: "slides", course: "Molecular Biology", created: "1w ago", summary: "CRISPR-Cas9 mechanism and applications.", takeaways: ["Guide RNA targeting", "HDR vs NHEJ"] },
  { id: "d5", name: "pset5-solutions.pdf", category: "study_guide", course: "Algorithms", created: "1w ago", summary: "Worked solutions for pset 5 covering greedy algorithms.", takeaways: ["Exchange argument", "Matroid structure"] },
  { id: "d6", name: "HW3.pdf", category: "assignment", course: "Linear Algebra", created: "2d ago", summary: "Vector space problems.", takeaways: [] },
];

const rooms: Room[] = [
  { id: "r1", name: "CS131 Study Crew", invite_code: "LEAF-42X", members: 6, unread: 3, lastMsg: "Alice is typing…" },
  { id: "r2", name: "Linear Algebra pals", invite_code: "SAGE-9KQ", members: 4, unread: 0, lastMsg: "eigen stuff" },
  { id: "r3", name: "Bio Thursday", invite_code: "ROOT-7PT", members: 11, unread: 12, lastMsg: "midterm prep?" },
];

const flashcards: Flashcard[] = [
  { id: "f1", topic: "Dynamic Programming", q: "Define optimal substructure.", a: "A problem has optimal substructure when an optimal solution to it contains optimal solutions to subproblems.", times_reviewed: 4, last_rating: "easy" },
  { id: "f2", topic: "Algorithms", q: "What is the time complexity of Kruskal's algorithm?", a: "O(E log E) using a disjoint-set data structure for cycle detection.", times_reviewed: 2, last_rating: "hard" },
  { id: "f3", topic: "SVD", q: "What does the SVD decompose a matrix into?", a: "A = UΣVᵀ — orthogonal U, diagonal Σ (singular values), orthogonal Vᵀ.", times_reviewed: 1, last_rating: "forgot" },
  { id: "f4", topic: "Qualia", q: "What is a quale?", a: "A subjective, qualitative property of conscious experience (the \"what it is like\" aspect).", times_reviewed: 3, last_rating: "easy" },
  { id: "f5", topic: "CRISPR", q: "What enzyme cuts DNA in CRISPR-Cas9?", a: "Cas9 endonuclease, guided by the sgRNA to the target site.", times_reviewed: 2 },
];

const achievements = {
  earned: [
    { id: "ach1", name: "First Steps", description: "Complete your first Learn session", category: "milestone" as const, rarity: "common" as const, icon: "🌱", earnedAt: "2 weeks ago" },
    { id: "ach2", name: "Night Owl", description: "Study after midnight 5 times", category: "activity" as const, rarity: "uncommon" as const, icon: "🦉", earnedAt: "1 week ago" },
    { id: "ach3", name: "Top Scholar", description: "Reach 90% mastery in a course", category: "milestone" as const, rarity: "rare" as const, icon: "📘", earnedAt: "3 days ago" },
    { id: "ach4", name: "Helpful Peer", description: "Send 50 messages in a study room", category: "social" as const, rarity: "uncommon" as const, icon: "🤝", earnedAt: "5 days ago" },
  ] as Achievement[],
  available: [
    { id: "ach5", name: "Unshakable", description: "30-day study streak", category: "activity" as const, rarity: "epic" as const, icon: "🔥", progress: 0.4 },
    { id: "ach6", name: "Secret Achievement", description: "Keep exploring to discover this", category: "special" as const, rarity: "legendary" as const, icon: "?", isSecret: true },
    { id: "ach7", name: "Polymath", description: "Master concepts in 4 different subjects", category: "milestone" as const, rarity: "rare" as const, icon: "🎓", progress: 0.75 },
  ] as Achievement[],
};

export const MOCK = {
  COURSES,
  nodes,
  edges,
  assignments,
  sessions,
  documents,
  rooms,
  flashcards,
  achievements,
};
