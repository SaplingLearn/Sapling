/** The admin check-item wire types (spec §13 A113, A124, A131;
 *  backend/routes/admin_check_items.py). Moved out of lib/api.ts, which
 *  re-exports every name beside the calls that return them. */
import type { LoopReportReason } from '@/lib/api';

// Admin — learning-loop check-item review queue (spec §13 A113;
// backend/routes/admin_check_items.py). Items the item-flaw linter flagged,
// the alignment check changed (A119: rubric_unasked_dropped, concept_retagged),
// a hold withdraws (A124's key holds: key_disputed … key_audit_ambiguous;
// A123's staff holds: reports_threshold — its reporters quarantined it —
// and staff_retired), drafted without sources (A128: unsourced — provenance,
// no hold) or students reported; the text comes decrypted for the first
// `page_size` only. In the backend's QUEUE_FLAGS order (the staff holds last,
// where the database's trigger stores them).
export type CheckItemLintFlag =
  | 'correct_longest'
  | 'correct_repeats_stem'
  | 'all_or_none_of_above'
  | 'duplicate_options'
  | 'negative_stem'
  | 'rubric_unasked_dropped'
  | 'concept_retagged'
  | 'key_disputed'
  | 'key_unsolved'
  | 'key_audit_wrong'
  | 'key_audit_ambiguous'
  | 'unsourced'
  | 'reports_threshold'
  | 'staff_retired';
/** What staff judge an item's key by (decrypted by the server for admins only). */
export interface AdminCheckItemText {
  prompt: string | null;
  options: { letter: string; text: string; correct: boolean }[] | null;
  final_answer: string | null;
  reference_answer: string | null;
  /** A124: a numeric item's key value and tolerance (what the A22 gate grades with). */
  canonical_answer: string | null;
  tolerance: number | null;
}
export interface AdminCheckItemEntry extends AdminCheckItemText {
  id: string;
  course_id: string;
  concept_key: string;
  question_hash: string;
  format: 'free' | 'teachback' | 'mc_reason';
  difficulty: number;
  lint_flags: CheckItemLintFlag[];
  reports: Record<LoopReportReason, number> & { total: number };
  last_reported_at: string | null;
  status: 'approved' | 'quarantined' | 'retired' | null;
  reviewed_at: string | null;
  /** The retire was decided but did not finish (its results not all voided, or
   *  the question still stored): retire it again. */
  retire_pending: boolean;
  /** A hold withdraws it from every student until it is approved or retired:
   *  a key hold (A124) or a staff hold (A123: `reports_threshold` — enough
   *  students reported it, status 'quarantined'; nothing is deleted). */
  held: boolean;
  /** spec §13 A141: a multi-concept item's concept keys, apex first (absent
   *  on a single-concept item, whose concept is `concept_key`). */
  components?: string[];
}
export interface AdminCheckItemQueue {
  items: AdminCheckItemEntry[];
  count: number;
  page_size: number;
  /** distinct reporters that quarantine a question (spec §13 A123) */
  quarantine_min_reporters: number;
}

// Admin — the human audit of check-item keys (spec §13 A124): a stratified
// sample (format × difficulty × concept) staff judge correct / wrong /
// ambiguous, and the course's key-error rate with a Wilson 95% interval.
export type CheckItemAuditVerdict = 'correct' | 'wrong' | 'ambiguous';
/** The key's status when it was (first) audited. */
export type CheckItemKeyStatus = 'verified' | 'held' | 'unverified';
export interface AuditRate {
  rate: number | null;
  ci_low: number | null;
  ci_high: number | null;
}
export interface AuditCounts {
  audited: number;
  correct: number;
  wrong: number;
  ambiguous: number;
  key_error: AuditRate;
  key_error_or_ambiguous: AuditRate;
}
export interface AuditSummary extends AuditCounts {
  by_key_status: Record<CheckItemKeyStatus, AuditCounts>;
}
export interface AdminAuditItem extends AdminCheckItemText {
  id: string;
  course_id: string;
  concept_key: string;
  question_hash: string;
  format: 'free' | 'teachback' | 'mc_reason';
  difficulty: number;
  key_status: CheckItemKeyStatus;
  verdict: CheckItemAuditVerdict | null;
  audited_at: string | null;
}
export interface AdminAuditSample {
  course_id: string;
  seed: string;
  /** Stored items the sample was drawn from. */
  population: number;
  items: AdminAuditItem[];
  summary: AuditSummary;
}

// Admin — empirical item statistics (spec §13 A131;
// backend/learning/item_stats.py): classical item analysis of one course's
// check items over students' FIRST unassisted attempts. A flag asks staff to
// look; nothing is written to the item.
export type ItemStatsFlag = 'too_easy' | 'too_hard' | 'low_discrimination' | 'negative_discrimination';
export interface ItemStats {
  /** Students whose first attempt on the question was unassisted. */
  n: number;
  correct: number;
  /** correct / n — the share who got it right (high = easy); null at n = 0. */
  p_value: number | null;
  p_ci_low: number | null;
  p_ci_high: number | null;
  /** The corrected item–rest point-biserial over the students who also
   *  answered another question of the concept; null when either side is constant. */
  discrimination: number | null;
  discrimination_n: number;
  flags: ItemStatsFlag[];
  /** When its numbers last changed (an attempt they count, or a retire that
   *  voided one); an approval at or after it hides the item from "Flagged by data". */
  numbers_changed_at: string | null;
}
export interface AdminItemStatsRow extends ItemStats {
  id: string;
  concept_key: string;
  question_hash: string;
  format: 'free' | 'teachback' | 'mc_reason';
  difficulty: number;
}
export interface AdminItemStatsFlagged extends AdminCheckItemEntry {
  stats: ItemStats;
}
export interface AdminItemStatsReport {
  course_id: string;
  /** Students a statistic needs before it may flag (ITEM_STATS_MIN_N). */
  min_n: number;
  easy_p: number;
  hard_p: number;
  low_discrimination: number;
  rows_scanned: number;
  /** The read hit its scan cap: the newest attempts are not counted. */
  truncated: boolean;
  /** Every stored question of the course. */
  items: AdminItemStatsRow[];
  /** The questions the data flags (worst first), the first `page_size` with their text. */
  flagged: AdminItemStatsFlagged[];
  flagged_count: number;
  page_size: number;
}
