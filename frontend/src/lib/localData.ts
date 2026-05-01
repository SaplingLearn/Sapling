/**
 * Local mode mock data — returned by api.ts when NEXT_PUBLIC_LOCAL_MODE=true.
 */
import type {
  GraphNode, GraphEdge, GraphStats, Assignment,
  UserProfile, UserSettings, UserAchievement, Achievement, Document,
  Role, Cosmetic, CosmeticType, RarityTier, AchievementCategory,
} from '@/lib/types';

const localRoles: Role[] = [];
const localAchievements: Achievement[] = [];
const localCosmetics: Cosmetic[] = [];

function parseBody<T = Record<string, unknown>>(options?: RequestInit): T {
  const body = options?.body;
  if (typeof body === 'string') {
    try { return JSON.parse(body) as T; } catch { return {} as T; }
  }
  return {} as T;
}

function randId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export const LOCAL_USER = {
  id: 'local-user-001',
  name: 'Local Dev',
  avatar: '',
};

const COURSES = [
  { name: 'Calculus II', color: '#2563eb' },
  { name: 'Intro to Psychology', color: '#9333ea' },
  { name: 'Data Structures', color: '#059669' },
];

function makeNodes(): GraphNode[] {
  const nodes: GraphNode[] = [];
  const concepts: Record<string, { name: string; mastery: number; tier: GraphNode['mastery_tier']; studied: string | null }[]> = {
    'Calculus II': [
      { name: 'Integration by Parts', mastery: 0.85, tier: 'mastered', studied: daysAgo(0) },
      { name: 'Taylor Series', mastery: 0.62, tier: 'learning', studied: daysAgo(1) },
      { name: 'Polar Coordinates', mastery: 0.35, tier: 'struggling', studied: daysAgo(3) },
      { name: 'Sequences & Convergence', mastery: 0.0, tier: 'unexplored', studied: null },
      { name: 'Partial Fractions', mastery: 0.91, tier: 'mastered', studied: daysAgo(2) },
    ],
    'Intro to Psychology': [
      { name: 'Classical Conditioning', mastery: 0.78, tier: 'learning', studied: daysAgo(0) },
      { name: 'Memory & Encoding', mastery: 0.45, tier: 'struggling', studied: daysAgo(2) },
      { name: 'Cognitive Biases', mastery: 0.0, tier: 'unexplored', studied: null },
    ],
    'Data Structures': [
      { name: 'Binary Trees', mastery: 0.95, tier: 'mastered', studied: daysAgo(1) },
      { name: 'Hash Maps', mastery: 0.7, tier: 'learning', studied: daysAgo(0) },
      { name: 'Graph Algorithms', mastery: 0.2, tier: 'struggling', studied: daysAgo(4) },
      { name: 'Dynamic Programming', mastery: 0.0, tier: 'unexplored', studied: null },
    ],
  };

  for (const course of COURSES) {
    const rootId = `subject_root__${course.name}`;
    nodes.push({
      id: rootId, concept_name: course.name, mastery_score: 0, mastery_tier: 'subject_root',
      times_studied: 0, last_studied_at: null, subject: course.name, is_subject_root: true,
      course_color: course.color,
    });
    for (const c of concepts[course.name] ?? []) {
      nodes.push({
        id: `node-${slugify(c.name)}`, concept_name: c.name, mastery_score: c.mastery,
        mastery_tier: c.tier, times_studied: Math.floor(c.mastery * 10),
        last_studied_at: c.studied, subject: course.name, course_color: course.color,
      });
    }
  }
  return nodes;
}

function makeEdges(nodes: GraphNode[]): GraphEdge[] {
  const edges: GraphEdge[] = [];
  const bySubject: Record<string, GraphNode[]> = {};
  for (const n of nodes) {
    if (n.is_subject_root) continue;
    (bySubject[n.subject] ??= []).push(n);
  }
  for (const [subject, conceptNodes] of Object.entries(bySubject)) {
    const rootId = `subject_root__${subject}`;
    for (const n of conceptNodes) {
      edges.push({ id: `e-${rootId}-${n.id}`, source: rootId, target: n.id, strength: 0.5 });
    }
    for (let i = 1; i < conceptNodes.length; i++) {
      edges.push({ id: `e-${conceptNodes[i - 1].id}-${conceptNodes[i].id}`, source: conceptNodes[i - 1].id, target: conceptNodes[i].id, strength: 0.3 });
    }
  }
  return edges;
}

const LOCAL_NODES = makeNodes();
const LOCAL_EDGES = makeEdges(LOCAL_NODES);

const LOCAL_STATS: GraphStats = {
  total_nodes: LOCAL_NODES.filter(n => !n.is_subject_root).length,
  mastered: LOCAL_NODES.filter(n => n.mastery_tier === 'mastered').length,
  learning: LOCAL_NODES.filter(n => n.mastery_tier === 'learning').length,
  struggling: LOCAL_NODES.filter(n => n.mastery_tier === 'struggling').length,
  unexplored: LOCAL_NODES.filter(n => n.mastery_tier === 'unexplored').length,
  streak: 4,
};

const LOCAL_RECOMMENDATIONS = [
  { concept_name: 'Polar Coordinates', reason: 'Low mastery — review recommended' },
  { concept_name: 'Memory & Encoding', reason: "Hasn't been studied recently" },
  { concept_name: 'Graph Algorithms', reason: 'Prerequisite for Dynamic Programming' },
];

const LOCAL_ASSIGNMENTS: Assignment[] = [
  { id: 'a1', title: 'Problem Set 7 — Series', course_name: 'Calculus II', course_id: 'c1', due_date: daysFromNow(2), assignment_type: 'homework' },
  { id: 'a2', title: 'Midterm Exam', course_name: 'Intro to Psychology', course_id: 'c2', due_date: daysFromNow(5), assignment_type: 'exam' },
  { id: 'a3', title: 'BST Implementation', course_name: 'Data Structures', course_id: 'c3', due_date: daysFromNow(3), assignment_type: 'project' },
  { id: 'a4', title: 'Reading: Chapter 12', course_name: 'Intro to Psychology', course_id: 'c2', due_date: daysFromNow(1), assignment_type: 'reading' },
  { id: 'a5', title: 'Integration Quiz', course_name: 'Calculus II', course_id: 'c1', due_date: daysFromNow(7), assignment_type: 'quiz' },
];

const LOCAL_COURSES = COURSES.map((c, i) => ({
  enrollment_id: `enr-${i}`, course_id: `c${i + 1}`, course_code: '',
  course_name: c.name, school: 'Local University', department: '',
  color: c.color, nickname: null,
  node_count: LOCAL_NODES.filter(n => n.subject === c.name && !n.is_subject_root).length,
  enrolled_at: daysAgo(30),
}));

const LOCAL_DOCUMENTS: Document[] = [
  { id: 'd1', user_id: LOCAL_USER.id, course_id: 'c1', file_name: 'Calc2_Syllabus.pdf', category: 'syllabus', summary: 'Syllabus for Calculus II.', concept_notes: [
    { name: 'Integration Techniques', description: 'Methods for evaluating $\\int f(x)\\,dx$, including substitution, integration by parts, and partial fractions.' },
    { name: 'Series Convergence Tests', description: 'Tests like the ratio test and integral test for deciding whether $\\sum a_n$ converges.' },
  ], created_at: daysAgo(20), processed_at: daysAgo(20) },
  { id: 'd2', user_id: LOCAL_USER.id, course_id: 'c3', file_name: 'Trees_Lecture.pdf', category: 'lecture_notes', summary: 'Binary trees and traversals.', concept_notes: [
    { name: 'Inorder Traversal', description: 'Visits the left subtree, root, then right subtree — yielding sorted output for a BST.' },
    { name: 'Tree Balancing', description: 'Restructuring rotations (e.g. AVL, red-black) that keep tree height $O(\\log n)$.' },
  ], created_at: daysAgo(5), processed_at: daysAgo(5) },
];

const LOCAL_FLASHCARDS = [
  { id: 'f1', user_id: LOCAL_USER.id, topic: 'Integration by Parts', front: 'What is the formula for integration by parts?', back: '\\int u\\,dv = uv - \\int v\\,du', rating: 4, created_at: daysAgo(3) },
  { id: 'f2', user_id: LOCAL_USER.id, topic: 'Binary Trees', front: 'What is the time complexity of search in a balanced BST?', back: 'O(log n)', rating: 5, created_at: daysAgo(2) },
  { id: 'f3', user_id: LOCAL_USER.id, topic: 'Classical Conditioning', front: 'Who is known for classical conditioning experiments?', back: 'Ivan Pavlov', rating: 3, created_at: daysAgo(1) },
];

const LOCAL_PROFILE: UserProfile = {
  id: LOCAL_USER.id, name: LOCAL_USER.name, username: 'localdev',
  bio: 'A local development user.', location: 'localhost', website: null,
  avatar_url: null, created_at: daysAgo(60), year: 'Junior',
  majors: ['Computer Science'], minors: ['Mathematics'], school: 'Local University',
  roles: [], featured_achievements: [], equipped_cosmetics: {},
  stats: { streak_count: 4, session_count: 12, documents_count: 2, achievements_count: 1 },
};

const LOCAL_SETTINGS: UserSettings = {
  display_name: LOCAL_USER.name, username: 'localdev',
  bio: 'A local development user.', location: 'localhost', website: null,
  notification_email: true, notification_push: false, notification_in_app: true,
  theme: 'light', font_size: 'medium', accent_color: '#1a5c2a',
  profile_visibility: 'public', activity_status_visible: true,
};

const LOCAL_ACHIEVEMENTS: { earned: UserAchievement[]; available: Achievement[] } = {
  earned: [
    { achievement: { id: 'ach1', name: 'First Steps', slug: 'first-steps', description: 'Complete your first study session', icon: null, category: 'milestone', rarity: 'common', is_secret: false }, earned_at: daysAgo(30), is_featured: false },
  ],
  available: [
    { id: 'ach2', name: 'Bookworm', slug: 'bookworm', description: 'Upload 10 documents', icon: null, category: 'activity', rarity: 'uncommon', is_secret: false },
    { id: 'ach3', name: 'On Fire', slug: 'on-fire', description: 'Reach a 7-day streak', icon: null, category: 'milestone', rarity: 'rare', is_secret: false },
  ],
};

const LOCAL_SESSIONS = [
  { id: 's1', topic: 'Integration by Parts', mode: 'socratic', course_id: 'c1', started_at: daysAgo(0), ended_at: null, message_count: 4, is_active: true },
  { id: 's2', topic: 'Binary Trees', mode: 'expository', course_id: 'c3', started_at: daysAgo(1), ended_at: daysAgo(1), message_count: 8, is_active: false },
];

const LOCAL_ROOMS = [{ id: 'r1', name: 'CS Study Group', invite_code: 'ABC123', member_count: 3 }];

export function handleLocalRequest(path: string, options?: RequestInit): unknown {
  const route = path.split('?')[0];

  if (route.match(/^\/api\/graph\/[^/]+$/)) return { nodes: LOCAL_NODES, edges: LOCAL_EDGES, stats: LOCAL_STATS };
  if (route.match(/^\/api\/graph\/[^/]+\/recommendations$/)) return { recommendations: LOCAL_RECOMMENDATIONS };
  if (route.match(/^\/api\/graph\/[^/]+\/courses$/) && (!options?.method || options.method === 'GET')) return { courses: LOCAL_COURSES };
  if (route.match(/^\/api\/graph\/[^/]+\/courses$/) && options?.method === 'POST') return { course_id: 'c-new', already_existed: false };
  if (route.match(/^\/api\/graph\/[^/]+\/courses\/[^/]+\/color$/)) return { updated: true };
  if (route.match(/^\/api\/graph\/[^/]+\/courses\/[^/]+$/) && options?.method === 'DELETE') return { deleted: true };

  if (route.match(/^\/api\/calendar\/upcoming\//)) return { assignments: LOCAL_ASSIGNMENTS };
  if (route.match(/^\/api\/calendar\/all\//)) return { assignments: LOCAL_ASSIGNMENTS };
  if (route.match(/^\/api\/calendar\/status\//)) return { connected: false };
  if (route.match(/^\/api\/calendar\/save$/) && options?.method === 'POST') return { saved_count: 0 };
  if (route.match(/^\/api\/calendar\/assignments\/[^/]+$/) && options?.method === 'PATCH') return { updated: true };
  if (route.match(/^\/api\/calendar\/assignments\/[^/]+$/) && options?.method === 'DELETE') return { deleted: true };

  if (route.match(/^\/api\/documents\/user\//)) return { documents: LOCAL_DOCUMENTS };
  if (route.match(/^\/api\/documents\/doc\//) && options?.method === 'DELETE') return { deleted: true };

  if (route.match(/^\/api\/flashcards\/user\//)) return { flashcards: LOCAL_FLASHCARDS };
  if (route.match(/^\/api\/flashcards\/generate$/) && options?.method === 'POST') return {
    flashcards: LOCAL_FLASHCARDS.slice(0, 2),
    context_used: { documents_found: LOCAL_DOCUMENTS.length, weak_concepts_found: 0 },
  };
  if (route.match(/^\/api\/flashcards\/rate$/)) return { ok: true };
  if (route.match(/^\/api\/flashcards\/[^/]+$/) && options?.method === 'DELETE') return { ok: true };
  if (route.match(/^\/api\/calendar\/import\//)) return { events: [], count: 0 };

  if (route.match(/^\/api\/study-guide\/[^/]+\/cached$/)) return { guides: [] };
  if (route.match(/^\/api\/study-guide\/[^/]+\/exams$/)) return {
    exams: LOCAL_ASSIGNMENTS.filter(a => a.assignment_type === 'exam' || a.assignment_type === 'quiz'),
  };
  if (route.match(/^\/api\/study-guide\/[^/]+\/guide$/)) return {
    guide: {
      exam: 'Midterm Exam',
      due_date: daysFromNow(5),
      overview: 'Local mode — connect the backend to generate a real study guide.',
      topics: [
        { name: 'Sample topic', importance: 'Placeholder importance line.', concepts: ['Concept one', 'Concept two'] },
      ],
    },
    generated_at: new Date().toISOString(),
    cached: true,
  };
  if (route.match(/^\/api\/study-guide\/regenerate$/) && options?.method === 'POST') return {
    success: true,
    guide: {
      exam: 'Midterm Exam',
      due_date: daysFromNow(5),
      overview: 'Regenerated placeholder guide (local mode).',
      topics: [
        { name: 'Refreshed topic', importance: 'Placeholder importance.', concepts: ['New concept A', 'New concept B'] },
      ],
    },
    generated_at: new Date().toISOString(),
  };

  if (route.match(/^\/api\/learn\/sessions\/[^/]+$/) && options?.method === 'DELETE') return { deleted: true };
  if (route.match(/^\/api\/learn\/sessions\/[^/]+\/resume$/)) return { session: { id: 'local-session', user_id: LOCAL_USER.id, topic: 'Local session', mode: 'socratic', course_id: null, started_at: new Date().toISOString(), ended_at: null }, messages: [] };
  if (route.match(/^\/api\/learn\/sessions\/[^/]+$/)) return { sessions: LOCAL_SESSIONS };
  if (route.match(/^\/api\/learn\/start-session$/) && options?.method === 'POST') return { session_id: 'local-session', initial_message: "Welcome! Local mode is active — AI chat is stubbed.", graph_state: {} };
  if (route.match(/^\/api\/learn\/chat$/) && options?.method === 'POST') return { reply: 'Local mode is active — AI chat is unavailable. Connect to the backend to use this feature.', graph_update: { new_nodes: [], updated_nodes: [], new_edges: [], recommended_next: [] }, mastery_changes: [] };
  if (route.match(/^\/api\/learn\/end-session$/) && options?.method === 'POST') return { summary: { concepts_covered: [], mastery_changes: [], new_connections: [], time_spent_minutes: 0, recommended_next: [] } };
  if (route.match(/^\/api\/learn\/action$/) && options?.method === 'POST') return { reply: 'Local mode — action noted.', graph_update: { new_nodes: [], updated_nodes: [], new_edges: [], recommended_next: [] } };
  if (route.match(/^\/api\/learn\/mode-switch$/) && options?.method === 'POST') return { reply: 'Local mode — mode switched.' };

  if (route.match(/^\/api\/social\/rooms\/[^/]+$/)) return { rooms: LOCAL_ROOMS };
  if (route.match(/^\/api\/social\/students$/)) return { students: [] };
  if (route.match(/^\/api\/social\/school-match$/) && options?.method === 'POST') return { matches: [] };

  if (route.match(/^\/api\/profile\/username\/check/)) return { available: true };
  if (route.match(/^\/api\/profile\/[^/]+\/featured-achievements/)) return { updated: true };
  if (route.match(/^\/api\/profile\/[^/]+\/settings/)) return LOCAL_SETTINGS;
  if (route.match(/^\/api\/profile\/[^/]+\/achievements$/)) return LOCAL_ACHIEVEMENTS;
  if (route.match(/^\/api\/profile\/[^/]+\/cosmetics\/catalog/)) return { catalog: { avatar_frame: [], banner: [], name_color: [], title: [] } };
  if (route.match(/^\/api\/profile\/[^/]+\/cosmetics/)) return { cosmetics: { avatar_frame: [], banner: [], name_color: [], title: [] }, equipped: {} };
  if (route.match(/^\/api\/profile\/[^/]+\/roles$/)) return { roles: [] };
  if (route.match(/^\/api\/profile\/[^/]+\/export/) && options?.method === 'POST') return { profile: LOCAL_PROFILE, settings: LOCAL_SETTINGS };
  if (route.match(/^\/api\/profile\/[^/]+\/equip/)) return { equipped: true };
  if (route.match(/^\/api\/profile\/[^/]+\/featured/)) return { updated: true };
  if (route.match(/^\/api\/profile\/[^/]+$/) && options?.method === 'PATCH') return { updated: true };
  if (route.match(/^\/api\/profile\/[^/]+$/)) return LOCAL_PROFILE;

  if (route.match(/^\/api\/admin\/roles$/) && (!options?.method || options.method === 'GET')) {
    return { roles: [...localRoles].sort((a, b) => b.display_priority - a.display_priority) };
  }
  if (route.match(/^\/api\/admin\/roles$/) && options?.method === 'POST') {
    const b = parseBody<Partial<Role>>(options);
    const role: Role = {
      id: randId('role'),
      name: String(b.name ?? 'Unnamed'),
      slug: String(b.slug ?? randId('slug')),
      color: String(b.color ?? '#8a7bc4'),
      icon: (b.icon as string | null | undefined) ?? null,
      description: (b.description as string | null | undefined) ?? null,
      is_staff_assigned: b.is_staff_assigned ?? true,
      is_earnable: b.is_earnable ?? false,
      display_priority: b.display_priority ?? 0,
    };
    localRoles.push(role);
    return { role };
  }
  {
    const m = route.match(/^\/api\/admin\/roles\/([^/]+)$/);
    if (m && options?.method === 'DELETE') {
      const idx = localRoles.findIndex(r => r.id === m[1]);
      if (idx >= 0) localRoles.splice(idx, 1);
      return { deleted: true };
    }
  }
  if (route.match(/^\/api\/admin\/achievements$/) && (!options?.method || options.method === 'GET')) {
    return { achievements: [...localAchievements] };
  }
  if (route.match(/^\/api\/admin\/achievements$/) && options?.method === 'POST') {
    const b = parseBody<Partial<Achievement>>(options);
    const achievement: Achievement = {
      id: randId('ach'),
      name: String(b.name ?? 'Unnamed'),
      slug: String(b.slug ?? randId('slug')),
      description: (b.description as string | null | undefined) ?? null,
      icon: (b.icon as string | null | undefined) ?? null,
      category: (b.category as AchievementCategory) ?? 'milestone',
      rarity: (b.rarity as RarityTier) ?? 'common',
      is_secret: b.is_secret ?? false,
    };
    localAchievements.push(achievement);
    return { achievement };
  }
  {
    const m = route.match(/^\/api\/admin\/achievements\/([^/]+)$/);
    if (m && options?.method === 'DELETE') {
      const idx = localAchievements.findIndex(a => a.id === m[1]);
      if (idx >= 0) localAchievements.splice(idx, 1);
      return { deleted: true };
    }
  }
  if (route.match(/^\/api\/admin\/achievements\/grant$/) && options?.method === 'POST') return { granted: true };
  if (route.match(/^\/api\/admin\/cosmetics$/) && (!options?.method || options.method === 'GET')) {
    return { cosmetics: [...localCosmetics] };
  }
  if (route.match(/^\/api\/admin\/cosmetics$/) && options?.method === 'POST') {
    const b = parseBody<Partial<Cosmetic>>(options);
    const cosmetic: Cosmetic = {
      id: randId('cos'),
      type: (b.type as CosmeticType) ?? 'avatar_frame',
      name: String(b.name ?? 'Unnamed'),
      slug: String(b.slug ?? randId('slug')),
      ...(b.asset_url ? { asset_url: String(b.asset_url) } : {}),
      ...(b.css_value ? { css_value: String(b.css_value) } : {}),
      rarity: (b.rarity as RarityTier) ?? 'common',
    };
    localCosmetics.push(cosmetic);
    return { cosmetic };
  }
  {
    const m = route.match(/^\/api\/admin\/cosmetics\/([^/]+)$/);
    if (m && options?.method === 'DELETE') {
      const idx = localCosmetics.findIndex(c => c.id === m[1]);
      if (idx >= 0) localCosmetics.splice(idx, 1);
      return { deleted: true };
    }
  }

  if (route.match(/^\/api\/auth\/me$/)) return { id: LOCAL_USER.id, name: LOCAL_USER.name, is_approved: true, is_admin: true, username: 'localdev', roles: [], equipped_cosmetics: {}, onboarding_completed: true };
  if (route.match(/^\/api\/users$/)) return { users: [{ id: LOCAL_USER.id, name: LOCAL_USER.name, room_id: null }] };

  if (route.match(/^\/api\/feedback$/)) return { ok: true };
  if (route.match(/^\/api\/issue-reports$/)) return { ok: true };

  if (route.match(/^\/api\/onboarding\/courses$/)) return {
    courses: [
      { id: 'c1', course_code: 'MATH 242', course_name: 'Linear Algebra' },
      { id: 'c2', course_code: 'CS 131', course_name: 'Algorithms' },
      { id: 'c3', course_code: 'BIO 108', course_name: 'Molecular Biology' },
      { id: 'c4', course_code: 'PHIL 150', course_name: 'Intro to Philosophy' },
      { id: 'c5', course_code: 'ECON 101', course_name: 'Microeconomics' },
    ],
  };
  if (route.match(/^\/api\/onboarding\/profile$/) && options?.method === 'POST') return { user_id: LOCAL_USER.id, courses_linked: [] };

  if (route.match(/^\/api\/quiz\/generate$/) && options?.method === 'POST') return { quiz_id: 'local-quiz', questions: [{ id: 1, question: 'Sample question (local mode)', options: [{ label: 'A', text: 'Answer A', correct: true }, { label: 'B', text: 'Answer B', correct: false }], explanation: 'Local mode placeholder', concept_tested: 'Sample', difficulty: 'medium' }] };
  if (route.match(/^\/api\/quiz\/submit$/)) return { score: 1, total: 1, mastery_before: 0.5, mastery_after: 0.6, results: [] };

  console.warn(`[local-mode] Unhandled route: ${options?.method ?? 'GET'} ${path}`);
  return {};
}

function slugify(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

function daysFromNow(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().split('T')[0];
}
