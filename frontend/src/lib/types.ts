export interface GraphNode {
  id: string;
  concept_name: string;
  mastery_score: number;
  mastery_tier: 'mastered' | 'learning' | 'struggling' | 'unexplored' | 'subject_root';
  times_studied: number;
  last_studied_at: string | null;
  subject: string;
  description?: string | null;
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
  course_id: string | null;
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
  unlock_source?: string | null;
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
  // "Drop the N lowest graded assignments before averaging." 0 = no drops.
  drop_lowest: number;
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
  // Bell curve fields — null when no curve applied
  curve_class_mean: number | null;
  curve_class_sd: number | null;
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
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
  // Credit-weighted GPA for the requested term; null until something is graded.
  gpa: number | null;
  semester: string;
}

// One enrollment row of GET /api/gradebook/gpa. `grade_points` is null while
// the course has no graded percent yet (rendered as in-progress, excluded
// from GPA math); `credits` is null when the offering doesn't declare any.
export interface GpaCourseRow {
  course_id: string;
  course_code: string;
  semester: string;
  credits: number | null;
  percent: number | null;
  letter: string | null;
  grade_points: number | null;
}

export interface GpaReport {
  gpa: number | null;
  courses: GpaCourseRow[];
  semester: string | null;
  scope: "semester" | "cumulative";
}

export interface GradebookCourse {
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  percent: number | null;
  letter: string | null;
  letter_scale: LetterScaleTier[] | null;
  curve_mode: "raw" | "curved";
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  // Server-flattened list of currently-dropped assignment IDs across all
  // categories. Used by the UI to render a "dropped" badge in the list.
  dropped_assignment_ids: string[];
}

export interface ExtractedSyllabusCategory {
  name: string;
  weight: number;
}

// ── Admin portal ─────────────────────────────────────────────────────────────

export interface AllowlistEmail {
  id: string;
  email: string;
  created_at: string;
  approved_at: string | null;
}

export interface AchievementTrigger {
  id: string;
  achievement_id: string;
  trigger_type: string;
  trigger_threshold: number;
}

export interface AdminAuditEntry {
  id: string;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AnalyticsTotals {
  users: number;
  approved: number;
  pending: number;
  admins: number;
}

export interface AnalyticsDayPoint {
  date: string;     // YYYY-MM-DD
  count: number;
}

export interface AnalyticsRoleCount {
  slug: string;
  name: string;
  color: string;
  count: number;
}

export interface AnalyticsOverview {
  totals: AnalyticsTotals;
  signups_by_day: AnalyticsDayPoint[];
  approvals_by_day: AnalyticsDayPoint[];
  role_counts: AnalyticsRoleCount[];
}

export interface AdminUserListItem {
  id: string;
  name: string;
  email: string;
  is_approved: boolean;
  is_admin?: boolean;
  last_sign_in_at: string | null;
  created_at: string;
  roles: Role[];
}

export interface PaginatedUsers {
  users: AdminUserListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface LinkedConcept {
  id: string;
  concept_name: string;
  mastery_tier: 'mastered' | 'learning' | 'struggling' | 'unexplored' | 'subject_root';
  mastery_score: number;
  course_id: string | null;
}

export interface Note {
  id: string;
  user_id: string;
  course_id: string;
  title: string;
  body: string;
  tags: string[];
  last_summary: string | null;
  last_summary_at: string | null;
  created_at: string;
  updated_at: string;
}

// ── Admin analytics (#121) ───────────────────────────────────────────────────
// Mirrors backend/routes/admin_analytics.py's response models (issue #120 plus
// the #121 bucket/series addition). Distinct names from the legacy
// AnalyticsOverview family above, which belongs to /admin/analytics/overview.
// `range` uses the wire key "from" (the backend serializes its `from_` field
// with an alias); `series` is present only when the request set `bucket=day`
// and is sparse — days with no rows are omitted, the client zero-fills.

export type LlmCostGroupBy = 'user' | 'feature' | 'model';
export type AnalyticsBucket = 'day';

export interface AnalyticsRange {
  from: string;
  to: string;
}

export interface UsageDayPoint {
  date: string; // YYYY-MM-DD, UTC
  count: number;
}

export interface CostDayPoint {
  date: string; // YYYY-MM-DD, UTC
  calls: number;
  total_tokens: number;
  cost_usd: number;
}

export interface EventTypeCount {
  event_type: string;
  count: number;
}

export interface UsageSummaryData {
  range: AnalyticsRange;
  total_events: number;
  distinct_active_users: number;
  by_event_type: EventTypeCount[];
  truncated: boolean;
  series: UsageDayPoint[] | null;
}

export interface UserUsageRow {
  user_id: string;
  event_count: number;
  by_category: Record<string, number>;
  llm_cost_usd: number;
  total_tokens: number;
}

export interface UsageByUserData {
  range: AnalyticsRange;
  total_users: number;
  limit: number;
  offset: number;
  users: UserUsageRow[];
  truncated: boolean;
}

export interface LlmCostRow {
  key: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface LlmCostTotals {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface LlmCostData {
  range: AnalyticsRange;
  group_by: LlmCostGroupBy;
  rows: LlmCostRow[];
  totals: LlmCostTotals;
  truncated: boolean;
  series: CostDayPoint[] | null;
}

export interface ErrorEventRow {
  created_at: string | null;
  event_type: string;
  request_id: string | null;
  user_id: string | null;
  path: string | null;
  method: string | null;
  status_code: number | null;
  duration_ms: number | null;
}

export interface ErrorsPageData {
  range: AnalyticsRange;
  total: number;
  limit: number;
  offset: number;
  errors: ErrorEventRow[];
  // Refers to the bucket series' scan (the feed itself is paginated).
  truncated: boolean;
  series: UsageDayPoint[] | null;
}
