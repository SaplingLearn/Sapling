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

/** PKG-14b: the tutor writes only new concepts and edges — no tutor tool moves
 *  mastery (the retired `updated_nodes` / `recommended_next` fields are gone). */
export interface GraphUpdate {
  new_nodes: { concept_name: string; subject: string; initial_mastery: number }[];
  new_edges: { source: string; target: string; strength: number }[];
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
  time_spent_minutes: number;
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
  room: {
    id: string; name: string; invite_code: string; created_by: string;
    // #405: real ownership, distinct from the immutable creator record.
    // Optional so rows predating the 0038 backfill still typecheck.
    owner_id?: string | null;
  };
  members: RoomMember[];
  ai_summary: string;
}

export interface RoomMessageRow {
  id: string;
  user_id: string;
  user_name: string;
  text: string | null;
  image_url: string | null;
  /** Intrinsic size of image_url; null on messages sent before #315. */
  image_width?: number | null;
  image_height?: number | null;
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
  xp_reward: number;
  icon_url: string | null;
  sort_order: number;
  status: 'draft' | 'live';
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
  // Product-analytics opt-out (PostHog), account-wide: governs the browser's
  // pageviews AND the backend's mirror (#677). The backend always sends it;
  // it stays optional only so a response without it is handled explicitly:
  // lib/analytics.ts treats it as `unset` — nothing starts in the browser,
  // the Settings switch stays usable (shown off), and it is not re-read.
  analytics_opt_out?: boolean;
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
  /** Set at the first approved sign-in with this email (routes/auth.py). */
  joined_at: string | null;
  joined_user_id: string | null;
  /** Delivery state of the "you're in" email to this address; null = never sent. */
  invite_status: InviteStatus | null;
}

/** "skipped" = Resend not configured; "suppressed" = the address unsubscribed. */
export type InviteStatus = "queued" | "sent" | "skipped" | "failed" | "suppressed";

/** GET /api/admin/email/status. When `configured` is false, emails are recorded but not sent. */
/** One personalization variable an admin can write in a broadcast as
 *  `{{key}}` or `{{key|fallback}}` (backend services/email_variables.py). */
export interface EmailVariable {
  key: string;
  label: string;
  /** Used when the recipient has no value and the admin gave none; may be "". */
  fallback: string;
  example: string;
  /** Link variables only: the default label. Alone on its line the link
   *  renders as a button with this label; `{{key|Label}}` overrides it. */
  button?: string;
}

export interface EmailStatus {
  configured: boolean;
  from_address: string;
  /** In display order. Optional so an older backend's response still types. */
  variables?: EmailVariable[];
}

export type EmailAudienceKey =
  | "waitlist_all"
  | "waitlist_pending"
  | "waitlist_approved_not_joined"
  | "users_all";

export interface EmailAudience {
  key: EmailAudienceKey;
  label: string;
  count: number;
}

export interface EmailBroadcast {
  id: string;
  subject: string;
  audience: string;
  /** partial = some sent, some failed (or the run died part-way); skipped = nothing sent, nothing failed. */
  status: "sending" | "sent" | "partial" | "skipped" | "failed";
  recipient_count: number;
  sent_count: number;
  skipped_count: number;
  failed_count: number;
  created_at: string;
  sent_at: string | null;
  created_by: string | null;
  heartbeat_at?: string | null;
  /** `sending` with no heartbeat for a while: the run is dead and can be resumed. */
  stale?: boolean;
  /** Stale, failed or partial: `POST /broadcasts/{id}/resume` will re-run it. */
  resumable?: boolean;
}

/** POST /api/admin/email/broadcasts/preview: the real server-rendered email (a full HTML document). Sends nothing. */
export interface EmailBroadcastPreview {
  /** The subject with the calling admin's variable values filled in. */
  subject: string;
  html: string;
  /** Variable names used in the draft that aren't real variables (left as
   *  typed in the render; a send with any of them 422s). */
  unknown_variables?: string[];
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
  /** null when the stored value can't be decrypted (see `undecryptable`). */
  email: string | null;
  /** The row's email/name are sealed under a different ENCRYPTION_KEY. */
  undecryptable?: boolean;
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

/** One reliability bin of the BKT calibration report (learning/calibration.py). */
export interface LoopCalibrationBin {
  lo: number;
  hi: number;
  n: number;
  mean_predicted: number | null;
  observed: number | null;
}

/** BKT's predicted P(correct) against observed outcomes on independent
 *  evidence (strong channel, unassisted, rung 0, full weight). Null rates mean
 *  nothing to judge — never zeros (spec §13 A110). */
export interface LoopCalibrationReport {
  n: number;
  brier: number | null;
  mean_predicted: number | null;
  observed_rate: number | null;
  ece: number | null;
  bins: LoopCalibrationBin[];
}

/** One stated-confidence level of the students' calibration report (spec §13
 *  A127, learning/calibration.py): `level` is guessing / fairly_sure / sure, or
 *  null for a value the current mapping no longer names. Null `observed` = n 0. */
export interface LoopConfidenceLevel {
  level: string | null;
  stated: number;
  n: number;
  correct: number;
  observed: number | null;
}

/** The students' stated confidence against correctness (metacognitive
 *  calibration). `overconfidence` = mean stated − observed; above 0, students
 *  were surer than right. Null rates mean nothing to judge — never zeros. */
export interface LoopConfidenceReport {
  n: number;
  mean_stated: number | null;
  observed_rate: number | null;
  overconfidence: number | null;
  brier: number | null;
  levels: LoopConfidenceLevel[];
}

export interface LoopChannelConfidenceReport extends LoopConfidenceReport {
  channel: string;
}

/** Pre/post outcomes over (student, concept) pairs: the concept's probe
 *  pretest against its unassisted delayed post-test (spec §13 A112). Observed
 *  answers only, never p_known; null rates mean n = 0 — never zeros. */
export interface LoopGainSummary {
  n: number;
  pre_correct_rate: number | null;
  post_correct_rate: number | null;
  /** mean(post − pre) over the pairs, in [−1, 1] */
  paired_difference: number | null;
  improved: number;
  same: number;
  worse: number;
}

/** One fixed post-test window (backend POSTTEST_WINDOWS_DAYS). */
export interface LoopGainWindow extends LoopGainSummary {
  window_days: number;
  /** unassisted post-test outcomes in the window, paired with a pretest or not */
  posttests: number;
  /** unassisted outcomes left out of the window: their item was later retired
   *  through spec §13 A113's review path (retired as broken — no valid measurement) */
  excluded_retired: number;
  /** spec §13 A126: the students behind the pairs, and the student-cluster
   *  bootstrap intervals [lo, hi] (null below two students) */
  students: number;
  post_correct_ci: [number, number] | null;
  paired_difference_ci: [number, number] | null;
  /** the pairs whose concept had no evidence for ≥ delayed_min_days before the pose */
  delayed: LoopGainSummary;
  /** A126: the pairs whose page was hidden while the item was on screen (a
   *  stratum: nothing is excluded for it), and the outcomes with no record */
  visibility_loss: LoopGainSummary;
  visibility_unreported: number;
}

/** A126: every window's pairs by the days from the concept's first graded
 *  evidence to the answer — the delay the outcome actually had. */
export interface LoopDelayBin extends LoopGainSummary {
  lo_days: number;
  /** null: open-ended */
  hi_days: number | null;
  posttests: number;
}

/** A126: what happened to the post-test windows that OPENED in the range —
 *  every due window is answered, expired, open, skipped or never opened. */
export interface LoopFunnelWindow {
  window_days: number;
  due: number;
  opened: number;
  answered: number;
  /** answered with no help (the outcomes the gain report can use) */
  unassisted: number;
  /** answered on a question staff retired: void evidence (spec §13 A123), never
   *  counted as answered; absent from a backend before the A123 × A126 merge */
  excluded_retired?: number;
  expired: number;
  open: number;
  skipped: number;
  /** no_items | exhausted | reported */
  skip_reasons: Record<string, number>;
  not_opened: number;
  /** unanswered windows not closed yet: their state can still change */
  still_open: number;
}

/** The learning-gain report (spec §13 A112, A126). */
export interface LoopLearningGain {
  delayed_min_days: number;
  ci: { method: string; level: number; resamples: number; seed: string };
  windows: LoopGainWindow[];
  delay_bins: LoopDelayBin[];
  delay_unknown: number;
  delay_out_of_range: number;
  /** null: the windows' anchors could not be read (unknown — never zeros) */
  funnel: LoopFunnelWindow[] | null;
}

/** spec §13 A137: one post-test window's pairs against the range's loop spend.
 *  Intervals are [lo, hi]; hi null = unbounded (a resample with no pair or no
 *  gain); the whole interval is null below two students. */
export interface LoopCostWindow {
  window_days: number;
  pairs: number;
  students: number;
  /** improved − worse: Σ(post − pre) over the pairs */
  gain_points: number;
  per_pair: number | null;
  per_pair_ci: [number | null, number | null] | null;
  /** null unless gain_points > 0: no cost per gain without a gain */
  per_gain_point: number | null;
  per_gain_point_ci: [number | null, number | null] | null;
}

/** The loop's spend overall (course_id null) or for one course (A137). */
export interface LoopCostBlock {
  course_id: string | null;
  cost_usd: number;
  /** the tutor tiers: what spec §3.5's target prices */
  tutor_usd: number;
  /** check-item drafting and its checks (course assets) */
  drafting_usd: number;
  rows: number;
  /** rows with no cost_usd (an unpriced model): no dollars added */
  unpriced_rows: number;
  active_students: number;
  per_active_student_month: number | null;
  tutor_per_active_student_month: number | null;
  /** per_active_student_month ÷ the §3.5 target */
  target_ratio: number | null;
  sessions: number;
  per_session: number | null;
  windows: LoopCostWindow[];
}

/** spec §13 A137: what the loop cost against what it measurably taught. */
export interface LoopCostPerGain {
  target_usd_per_student_month: number;
  range_days: number | null;
  ci: { method: string; level: number; resamples: number; seed: string };
  overall: LoopCostBlock;
  courses: LoopCostBlock[];
  /** spend with no course of its own and no session (overall only) */
  unattributed: { cost_usd: number; rows: number };
}

/** GET /api/admin/analytics/learning-loop — spec §10 KPIs and gates. */
export interface LearningLoopKpisData {
  range: { from: string; to: string };
  steps_total: number;
  banded_steps: number;
  in_band: number;
  in_band_share: number | null;
  unassisted_next_session: { sessions: number; successes: number; rate: number | null; quiz_ask_excluded: number };
  caught_leaks: number;
  served_reveals: number;
  unscanned_turns: number;
  ceiling_compliance: { steps: number; compliant: number; rate: number | null };
  earnest_revise: {
    graded_steps: number;
    earnest_blocked: number;
    unmeasured_steps: number;
    rate: number | null;
    gate: 'pass' | 'fail' | 'inconclusive';
  };
  gates: { zero_leaks: boolean; ceiling_compliance_ok: boolean; earnest_revise_ok: boolean | null };
  calibration: {
    all: LoopCalibrationReport;
    posttest: LoopCalibrationReport;
    /** independent observations left out: graded against an item staff
     *  retired, so void evidence (spec §13 A123) — the drop, visible */
    excluded_void: number;
  };
  /** the students' own calibration: stated confidence vs correctness, per
   *  channel (spec §13 A127; void evidence left out, A123); only channels with
   *  a stated confidence are listed */
  confidence_calibration: { all: LoopConfidenceReport; channels: LoopChannelConfidenceReport[] };
  /** post-tests answered in the range, per fixed window (spec §13 A112), and
   *  the funnel of the windows that opened in it (A126) */
  learning_gain: LoopLearningGain;
  /** spec §13 A137: the loop's spend against the learning gain; null when the
   *  spend could not be read, absent from a pre-A137 backend. */
  cost_per_gain?: LoopCostPerGain | null;
  /** spec §13 A128: the API process's active evidence-slot warnings (its current
   *  configuration, not the range); absent from a pre-A128 backend. */
  slot_warnings?: LoopSlotWarning[];
  truncated: boolean;
}

/** An evidence-producing model slot run outside its evaluated set, or resolved
 *  to the model it must be independent of (A22's second opinion, A124's key solve). */
export interface LoopSlotWarning {
  kind: 'unevaluated' | 'not_independent';
  slot: string;
  model: string;
  /** unevaluated: pending_claude_eval | not_evaluated */
  reason?: string | null;
  /** not_independent: the slot whose model it shares, and the spec rule */
  independent_of?: string | null;
  rule?: string | null;
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

// ── Public rooms (#405) ──────────────────────────────────────────────────────
// The invite-less discovery payload; deliberately carries NO invite_code.
export interface PublicRoom {
  id: string;
  name: string;
  topic: string | null;
  course: string | null;
  owner_id: string;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  is_public: true;
  member_count: number;
}

// ── Gamification (XP / achievements / growth) ────────────────────────────────

export interface GrowthStage {
  slug: string;
  name: string;
  blurb: string;
}

export interface GamificationMe {
  level: number;
  next_level: number;
  stage: GrowthStage;
  total_xp: number;
  xp_into_level: number;
  xp_for_level: number;
  level_pct: number;
  streak: number;
  longest_streak: number;
  daily_goal_xp: number;
  today_xp: number;
  earned_count: number;
  total_count: number;
}

export interface LeaderboardRow {
  rank: number;
  user_id: string;
  name: string;
  level: number;
  stage: string;
  total_xp: number;
  week_xp: number;
  streak: number;
  is_you: boolean;
}

export interface ActivityData {
  week: { day: string; date: string; xp: number }[];
  trend: { label: string; xp: number }[];
  daily_goal_xp: number;
  tiles: {
    week_total: number;
    daily_avg: number;
    best_day: number;
    best_day_label: string;
    streak: number;
  };
}

export interface Friend {
  user_id: string;
  name: string;
  level: number;
  total_xp: number;
}
