export type Course = {
  id: string;
  course_code: string;
  name: string;
  color: string;
};

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
