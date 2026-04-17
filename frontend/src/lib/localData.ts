/**
 * Local mode mock data — returned by api.ts when NEXT_PUBLIC_LOCAL_MODE=true.
 * Allows the frontend to run without the backend.
 */

import type {
  GraphNode, GraphEdge, GraphStats, Recommendation, Assignment,
  UserProfile, UserSettings, UserRole, UserAchievement, Achievement,
  UserCosmetic, Document,
} from '@/lib/types';

export const LOCAL_USER = {
  id: 'local-user-001',
  name: 'Local Dev',
  avatar: '',
};

// ── Graph ────────────────────────────────────────────────────────────────────

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
      id: rootId,
      concept_name: course.name,
      mastery_score: 0,
      mastery_tier: 'subject_root',
      times_studied: 0,
      last_studied_at: null,
      subject: course.name,
      is_subject_root: true,
      course_color: course.color,
    });

    for (const c of concepts[course.name] ?? []) {
      nodes.push({
        id: `node-${slugify(c.name)}`,
        concept_name: c.name,
        mastery_score: c.mastery,
        mastery_tier: c.tier,
        times_studied: Math.floor(c.mastery * 10),
        last_studied_at: c.studied,
        subject: course.name,
        course_color: course.color,
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

const LOCAL_RECOMMENDATIONS: Recommendation[] = [
  { concept_name: 'Polar Coordinates', reason: 'Low mastery — review recommended' },
  { concept_name: 'Memory & Encoding', reason: 'Hasn\'t been studied recently' },
  { concept_name: 'Graph Algorithms', reason: 'Prerequisite for Dynamic Programming' },
];

// ── Assignments ──────────────────────────────────────────────────────────────

const LOCAL_ASSIGNMENTS: Assignment[] = [
  { id: 'a1', title: 'Problem Set 7 — Series', course_name: 'Calculus II', course_id: 'c1', due_date: daysFromNow(2), assignment_type: 'homework' },
  { id: 'a2', title: 'Midterm Exam', course_name: 'Intro to Psychology', course_id: 'c2', due_date: daysFromNow(5), assignment_type: 'exam' },
  { id: 'a3', title: 'BST Implementation', course_name: 'Data Structures', course_id: 'c3', due_date: daysFromNow(3), assignment_type: 'project' },
  { id: 'a4', title: 'Reading: Chapter 12', course_name: 'Intro to Psychology', course_id: 'c2', due_date: daysFromNow(1), assignment_type: 'reading' },
  { id: 'a5', title: 'Integration Quiz', course_name: 'Calculus II', course_id: 'c1', due_date: daysFromNow(7), assignment_type: 'quiz' },
];

// ── Courses ──────────────────────────────────────────────────────────────────

const LOCAL_COURSES = COURSES.map((c, i) => ({
  enrollment_id: `enr-${i}`,
  course_id: `c${i + 1}`,
  course_code: '',
  course_name: c.name,
  school: 'Local University',
  department: '',
  color: c.color,
  nickname: null,
  node_count: LOCAL_NODES.filter(n => n.subject === c.name && !n.is_subject_root).length,
  enrolled_at: daysAgo(30),
}));

// ── Documents ────────────────────────────────────────────────────────────────

const LOCAL_DOCUMENTS: Document[] = [
  { id: 'd1', user_id: LOCAL_USER.id, course_id: 'c1', file_name: 'Calc2_Syllabus.pdf', category: 'syllabus', summary: 'Course syllabus for Calculus II covering integration, series, and polar coordinates.', key_takeaways: ['Integration techniques', 'Series convergence tests'], flashcards: null, created_at: daysAgo(20), processed_at: daysAgo(20) },
  { id: 'd2', user_id: LOCAL_USER.id, course_id: 'c3', file_name: 'Trees_Lecture.pdf', category: 'lecture_notes', summary: 'Lecture notes on binary trees and traversals.', key_takeaways: ['Inorder traversal', 'Tree balancing'], flashcards: null, created_at: daysAgo(5), processed_at: daysAgo(5) },
];

// ── Flashcards ───────────────────────────────────────────────────────────────

const LOCAL_FLASHCARDS = [
  { id: 'f1', user_id: LOCAL_USER.id, topic: 'Integration by Parts', front: 'What is the formula for integration by parts?', back: '\\int u\\,dv = uv - \\int v\\,du', rating: 4, created_at: daysAgo(3) },
  { id: 'f2', user_id: LOCAL_USER.id, topic: 'Binary Trees', front: 'What is the time complexity of search in a balanced BST?', back: 'O(log n)', rating: 5, created_at: daysAgo(2) },
  { id: 'f3', user_id: LOCAL_USER.id, topic: 'Classical Conditioning', front: 'Who is known for classical conditioning experiments?', back: 'Ivan Pavlov', rating: 3, created_at: daysAgo(1) },
];

// ── Profile / Settings / Achievements ────────────────────────────────────────

const LOCAL_PROFILE: UserProfile = {
  id: LOCAL_USER.id,
  name: LOCAL_USER.name,
  username: 'localdev',
  bio: 'A local development user for testing.',
  location: 'localhost',
  website: null,
  avatar_url: null,
  created_at: daysAgo(60),
  year: 'Junior',
  majors: ['Computer Science'],
  minors: ['Mathematics'],
  school: 'Local University',
  roles: [],
  featured_achievements: [],
  equipped_cosmetics: {},
  stats: { streak_count: 4, session_count: 12, documents_count: 2, achievements_count: 1 },
};

const LOCAL_SETTINGS: UserSettings = {
  display_name: LOCAL_USER.name,
  username: 'localdev',
  bio: 'A local development user for testing.',
  location: 'localhost',
  website: null,
  notification_email: true,
  notification_push: false,
  notification_in_app: true,
  theme: 'light',
  font_size: 'medium',
  accent_color: '#1a5c2a',
  profile_visibility: 'public',
  activity_status_visible: true,
};

const LOCAL_ACHIEVEMENTS: { earned: UserAchievement[]; available: Achievement[] } = {
  earned: [
    {
      achievement: { id: 'ach1', name: 'First Steps', slug: 'first-steps', description: 'Complete your first study session', icon: null, category: 'milestone', rarity: 'common', is_secret: false },
      earned_at: daysAgo(30),
      is_featured: false,
    },
  ],
  available: [
    { id: 'ach2', name: 'Bookworm', slug: 'bookworm', description: 'Upload 10 documents', icon: null, category: 'activity', rarity: 'uncommon', is_secret: false },
    { id: 'ach3', name: 'On Fire', slug: 'on-fire', description: 'Reach a 7-day streak', icon: null, category: 'milestone', rarity: 'rare', is_secret: false },
  ],
};

// ── Sessions ─────────────────────────────────────────────────────────────────

const LOCAL_SESSIONS = [
  { id: 's1', topic: 'Integration by Parts', mode: 'socratic', course_id: 'c1', started_at: daysAgo(0), ended_at: null, message_count: 4, is_active: true },
  { id: 's2', topic: 'Binary Trees', mode: 'expository', course_id: 'c3', started_at: daysAgo(1), ended_at: daysAgo(1), message_count: 8, is_active: false },
];

// ── Social ───────────────────────────────────────────────────────────────────

const LOCAL_ROOMS = [
  { id: 'r1', name: 'CS Study Group', invite_code: 'ABC123', member_count: 3 },
];

// ── Route handler ────────────────────────────────────────────────────────────

export function handleLocalRequest(path: string, options?: RequestInit): unknown {
  // Strip query params for matching
  const route = path.split('?')[0];

  // Graph
  if (route.match(/^\/api\/graph\/[^/]+$/))
    return { nodes: LOCAL_NODES, edges: LOCAL_EDGES, stats: LOCAL_STATS };
  if (route.match(/^\/api\/graph\/[^/]+\/recommendations$/))
    return { recommendations: LOCAL_RECOMMENDATIONS };
  if (route.match(/^\/api\/graph\/[^/]+\/courses$/) && (!options?.method || options.method === 'GET'))
    return { courses: LOCAL_COURSES };
  if (route.match(/^\/api\/graph\/[^/]+\/courses$/) && options?.method === 'POST')
    return { course_id: 'c-new', already_existed: false };
  if (route.match(/^\/api\/graph\/[^/]+\/courses\/[^/]+\/color$/) && options?.method === 'PATCH')
    return { updated: true };
  if (route.match(/^\/api\/graph\/[^/]+\/courses\/[^/]+$/) && options?.method === 'DELETE')
    return { deleted: true };

  // Calendar / Assignments
  if (route.match(/^\/api\/calendar\/upcoming\//))
    return { assignments: LOCAL_ASSIGNMENTS };
  if (route.match(/^\/api\/calendar\/all\//))
    return { assignments: LOCAL_ASSIGNMENTS };
  if (route.match(/^\/api\/calendar\/status\//))
    return { connected: false };
  if (route.match(/^\/api\/calendar\/save$/) && options?.method === 'POST')
    return { saved_count: 0 };

  // Documents
  if (route.match(/^\/api\/documents\/user\//))
    return { documents: LOCAL_DOCUMENTS };
  if (route.match(/^\/api\/documents\/doc\//) && options?.method === 'DELETE')
    return { deleted: true };

  // Flashcards
  if (route.match(/^\/api\/flashcards\/user\//))
    return { flashcards: LOCAL_FLASHCARDS };
  if (route.match(/^\/api\/flashcards\/generate$/) && options?.method === 'POST')
    return { flashcards: LOCAL_FLASHCARDS.slice(0, 2) };
  if (route.match(/^\/api\/flashcards\/rate$/) && options?.method === 'POST')
    return { ok: true };

  // Learn / Sessions
  if (route.match(/^\/api\/learn\/sessions\/[^/]+$/) && (!options?.method || options.method === 'GET'))
    return { sessions: LOCAL_SESSIONS };
  if (route.match(/^\/api\/learn\/start-session$/) && options?.method === 'POST')
    return { session_id: 'local-session', initial_message: 'Welcome! What would you like to study today? (Local mode — AI chat is unavailable)', graph_state: {} };
  if (route.match(/^\/api\/learn\/chat$/) && options?.method === 'POST')
    return { reply: 'Local mode is active — AI chat is unavailable. Connect to the backend to use this feature.', graph_update: { new_nodes: [], updated_nodes: [], new_edges: [], recommended_next: [] }, mastery_changes: [] };
  if (route.match(/^\/api\/learn\/end-session$/) && options?.method === 'POST')
    return { summary: { concepts_covered: [], mastery_changes: [], new_connections: [], time_spent_minutes: 0, recommended_next: [] } };

  // Social
  if (route.match(/^\/api\/social\/rooms\/[^/]+$/) && (!options?.method || options.method === 'GET'))
    return { rooms: LOCAL_ROOMS };
  if (route.match(/^\/api\/social\/students$/))
    return { students: [] };
  if (route.match(/^\/api\/social\/school-match$/) && options?.method === 'POST')
    return { matches: [] };

  // Profile
  if (route.match(/^\/api\/profile\/[^/]+\/settings/) && options?.method === 'PATCH')
    return LOCAL_SETTINGS;
  if (route.match(/^\/api\/profile\/[^/]+\/settings/))
    return LOCAL_SETTINGS;
  if (route.match(/^\/api\/profile\/[^/]+\/achievements$/))
    return LOCAL_ACHIEVEMENTS;
  if (route.match(/^\/api\/profile\/[^/]+\/cosmetics/))
    return { cosmetics: { avatar_frame: [], banner: [], name_color: [], title: [] }, equipped: {} };
  if (route.match(/^\/api\/profile\/[^/]+\/roles$/))
    return { roles: [] };
  if (route.match(/^\/api\/profile\/[^/]+\/export/) && options?.method === 'POST')
    return { profile: LOCAL_PROFILE, settings: LOCAL_SETTINGS };
  if (route.match(/^\/api\/profile\/[^/]+\/equip/) && options?.method === 'POST')
    return { equipped: true };
  if (route.match(/^\/api\/profile\/[^/]+\/featured/) && options?.method === 'POST')
    return { updated: true };
  if (route.match(/^\/api\/profile\/[^/]+$/) && options?.method === 'PATCH')
    return { updated: true };
  if (route.match(/^\/api\/profile\/[^/]+$/))
    return LOCAL_PROFILE;

  // Auth
  if (route.match(/^\/api\/auth\/me$/))
    return { id: LOCAL_USER.id, name: LOCAL_USER.name, is_approved: true, is_admin: true, username: 'localdev', roles: [], equipped_cosmetics: {} };
  if (route.match(/^\/api\/users$/))
    return { users: [{ id: LOCAL_USER.id, name: LOCAL_USER.name, room_id: null }] };

  // Feedback / issues
  if (route.match(/^\/api\/feedback$/) && options?.method === 'POST')
    return { ok: true };
  if (route.match(/^\/api\/issue-reports$/) && options?.method === 'POST')
    return { ok: true };

  // Quiz
  if (route.match(/^\/api\/quiz\/generate$/) && options?.method === 'POST')
    return {
      quiz_id: 'local-quiz',
      questions: [
        { id: 1, question: 'Sample question (local mode)', options: [{ label: 'A', text: 'Answer A', correct: true }, { label: 'B', text: 'Answer B', correct: false }], explanation: 'Local mode placeholder', concept_tested: 'Sample', difficulty: 'medium' },
      ],
    };
  if (route.match(/^\/api\/quiz\/submit$/) && options?.method === 'POST')
    return { score: 1, total: 1, mastery_before: 0.5, mastery_after: 0.6, results: [] };

  // Fallback — return empty object so the app doesn't crash
  console.warn(`[local-mode] Unhandled route: ${options?.method ?? 'GET'} ${path}`);
  return {};
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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
