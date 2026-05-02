export interface GraphNode {
  id: string;
  concept_name: string;
  mastery_score: number;
  mastery_tier: 'mastered' | 'learning' | 'struggling' | 'unexplored' | 'subject_root';
  times_studied: number;
  last_studied_at: string | null;
  subject: string;
  course_id?: string | null;
  course_color?: string | null;
  color?: string | null;
  is_subject_root?: boolean;
  x?: number;
  y?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  strength: number;
}

export interface KnowledgeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphStats {
  total_nodes: number;
  mastered: number;
  learning: number;
  struggling: number;
  unexplored: number;
  streak: number;
}

export interface GraphUpdate {
  new_nodes: { concept_name: string; subject: string; initial_mastery: number }[];
  updated_nodes: { concept_name: string; mastery_delta: number; reason: string }[];
  new_edges: { source: string; target: string; strength: number }[];
  recommended_next: string[];
}

export interface MasteryChange {
  concept: string;
  before: number;
  after: number;
}

export type TeachingMode = 'socratic' | 'expository' | 'teachback';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface ChatResponse {
  reply: string;
  graph_update: GraphUpdate;
  mastery_changes: MasteryChange[];
}

export interface SessionSummary {
  concepts_covered: string[];
  mastery_changes: MasteryChange[];
  new_connections: { source: string; target: string }[];
  time_spent_minutes: number;
  recommended_next: string[];
}

export interface QuizQuestion {
  id: number;
  question: string;
  options: { label: string; text: string; correct: boolean }[];
  explanation: string;
  concept_tested: string;
  difficulty: string;
}

export interface QuizResult {
  question_id: number;
  selected: string;
  correct: boolean;
  correct_answer: string;
  explanation: string;
}

export interface Assignment {
  id: string;
  title: string;
  course_name?: string;
  course_code?: string;
  course_id?: string;
  due_date: string;
  assignment_type?: string;
  notes?: string | null;
  google_event_id?: string | null;
}

export interface Room {
  id: string;
  name: string;
  invite_code: string;
  member_count: number;
  members?: RoomMember[];
}

export interface RoomMember {
  user_id: string;
  name: string;
  graph: KnowledgeGraph & { stats?: GraphStats };
}

export interface RoomOverviewData {
  room: { id: string; name: string; invite_code: string; created_by: string };
  members: RoomMember[];
  ai_summary: string;
}

export interface RoomMessageRow {
  id: string;
  user_id: string;
  user_name: string;
  text: string | null;
  image_url: string | null;
  created_at: string;
  reply_to_id: string | null;
  is_deleted: boolean;
  edited_at: string | null;
  reply_to: { id: string; user_name: string; text: string | null } | null;
  reactions: { emoji: string; user_ids: string[] }[];
}

export interface ConceptNote {
  name: string;
  description: string;
}

export interface Document {
  id: string;
  user_id: string;
  course_id: string;
  file_name: string;
  category: 'syllabus' | 'lecture_notes' | 'slides' | 'reading' | 'assignment' | 'study_guide' | 'other';
  summary: string | null;
  concept_notes: ConceptNote[] | null;
  created_at: string;
  processed_at: string | null;
}

export type RarityTier = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary';
export type CosmeticType = 'avatar_frame' | 'banner' | 'name_color' | 'title';
export type AchievementCategory = 'activity' | 'social' | 'milestone' | 'special';

export interface Role {
  id: string;
  name: string;
  slug: string;
  color: string;
  icon: string | null;
  description: string | null;
  is_staff_assigned: boolean;
  is_earnable: boolean;
  display_priority: number;
}

export interface UserRole {
  role: Role;
  granted_at: string;
}

export interface AchievementProgress {
  current: number;
  target: number;
}

export interface Achievement {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  category: AchievementCategory;
  rarity: RarityTier;
  is_secret: boolean;
  progress?: AchievementProgress | null;
}

export interface UserAchievement {
  achievement: Achievement;
  earned_at: string;
  is_featured: boolean;
}

export interface Cosmetic {
  id: string;
  type: CosmeticType;
  name: string;
  slug: string;
  asset_url?: string;
  css_value?: string;
  rarity: RarityTier;
}

export interface UserCosmetic {
  cosmetic: Cosmetic;
  unlocked_at: string;
}

export interface EquippedCosmetics {
  avatar_frame?: Cosmetic;
  banner?: Cosmetic;
  name_color?: Cosmetic;
  title?: Cosmetic;
  featured_role?: Role;
}

export interface UserStats {
  streak_count: number;
  session_count: number;
  documents_count: number;
  achievements_count: number;
}

export interface UserProfile {
  id: string;
  name: string;
  username: string | null;
  bio: string | null;
  location: string | null;
  website: string | null;
  avatar_url: string | null;
  created_at: string | null;
  year: string | null;
  majors: string[];
  minors: string[];
  school: string | null;
  roles: UserRole[];
  featured_achievements: UserAchievement[];
  equipped_cosmetics: EquippedCosmetics;
  stats: UserStats;
}

export interface UserSettings {
  display_name: string | null;
  username: string | null;
  bio: string | null;
  location: string | null;
  website: string | null;
  notification_email: boolean;
  notification_push: boolean;
  notification_in_app: boolean;
  theme: string;
  font_size: string;
  accent_color: string | null;
  profile_visibility: string;
  activity_status_visible: boolean;
}

// ── Gradebook ────────────────────────────────────────────────────────────────

export interface LetterScaleTier {
  min: number;
  letter: string;
}

export interface GradeCategory {
  id: string;
  name: string;
  weight: number;
  sort_order: number;
  category_grade?: number | null;  // 0–1, server-computed; only on detail
}

export interface GradedAssignment {
  id: string;
  title: string;
  course_id: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
  source: "manual" | "syllabus" | "gradescope";
}

export interface GradebookCourseSummary {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  graded_count: number;
  total_count: number;
}

export interface GradebookSummary {
  courses: GradebookCourseSummary[];
}

export interface GradebookCourse {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  letter_scale: LetterScaleTier[] | null;
  categories: GradeCategory[];
  assignments: GradedAssignment[];
}

export interface ExtractedSyllabusCategory {
  name: string;
  weight: number;
}
