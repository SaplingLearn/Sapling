/** The learning-loop KPI report's wire types (GET
 *  /api/admin/analytics/learning-loop; spec §10, §13). Moved out of types.ts,
 *  which re-exports every name. */

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

/** One concept's hints-to-criterion trend (spec §10 htc_k): per ISO week
 *  (`week_start`, a Monday, UTC), the mean `max_rung_used` over its correct
 *  steps; `direction` compares the last week with the first. */
export interface LoopConceptTrend { concept_id: string; weeks: { week_start: string; mean_rung: number; steps: number }[]; direction: 'falling' | 'flat' | 'rising' | 'insufficient' }

/** GET /api/admin/analytics/learning-loop — spec §10 KPIs and gates. */
export interface LearningLoopKpisData {
  range: { from: string; to: string };
  steps_total: number;
  banded_steps: number;
  in_band: number;
  in_band_share: number | null;
  /** per concept, the KPI_TREND_WEEKS weeks ending at `range.to` (hints must fall) */
  htc_k_trend: LoopConceptTrend[];
  unassisted_next_session: { sessions: number; successes: number; rate: number | null; quiz_ask_excluded: number };
  caught_leaks: number;
  served_reveals: number;
  unscanned_turns: number;
  ceiling_compliance: { steps: number; compliant: number; rate: number | null };
  earnest_revise: {
    graded_steps: number; earnest_blocked: number; unmeasured_steps: number; rate: number | null;
    gate: 'pass' | 'fail' | 'inconclusive';
  };
  /** a null gate is inconclusive: nothing in the range carries its signal (#866 K56; A109) */
  gates: { zero_leaks: boolean; ceiling_compliance_ok: boolean | null; earnest_revise_ok: boolean | null };
  /** `excluded_void`: independent observations left out, graded against an
   *  item staff retired, so void evidence (spec §13 A123) — the drop, visible */
  calibration: { all: LoopCalibrationReport; posttest: LoopCalibrationReport; excluded_void: number };
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
  /** spec §13 A133: help abuse. null: its reads failed (the rest of the report
   *  stands); absent from a pre-A133 backend. */
  help_abuse?: LoopHelpAbuse | null;
  /** spec §13 A139: the "why does this follow?" prompts. null: its reads failed
   *  (the rest of the report stands); absent from a pre-A139 backend. */
  self_explanation?: LoopSelfExplanation | null;
  /** spec §13 A141: multi-concept items stored, served and their outcomes.
   *  null: its reads failed (the rest stands); absent from a pre-A141 backend. */
  multi_concept?: LoopMultiConcept | null;
  truncated: boolean;
}

/** spec §13 A139: the student's next graded item on the concept after a prompt
 *  (another item than the one it was about). `unassisted`: right with no help;
 *  `n`: prompts with such a next item; `none`: prompts with no later graded item
 *  in the range (never counted in `n`). `rate` is null when n = 0. */
export interface LoopSelfExplainNext {
  n: number;
  unassisted: number;
  rate: number | null;
  none: number;
}

/** After a reply, against after no reply (skipped, or never answered). */
export interface LoopSelfExplainNextPair {
  replied: LoopSelfExplainNext;
  not_replied: LoopSelfExplainNext;
}

/** One juncture's prompts (worked_example / released_solution / first_correct). */
export interface LoopSelfExplainJuncture {
  juncture: string;
  shown: number;
  replied: number;
  /** replied / shown; null when none was shown */
  reply_rate: number | null;
  next_item: LoopSelfExplainNextPair;
}

/** spec §13 A139: self-explanation prompts over the range — diagnosis only:
 *  a reply is never graded, never evidence. */
export interface LoopSelfExplanation {
  shown: number;
  replied: number;
  skipped: number;
  /** shown and never replied to or skipped */
  open: number;
  /** replied / shown (n = shown); null when none was shown */
  reply_rate: number | null;
  /** the replies' length in characters: the median over n replies */
  reply_chars: { median: number | null; n: number };
  next_item: LoopSelfExplainNextPair;
  by_juncture: LoopSelfExplainJuncture[];
  truncated: boolean;
}

/** spec §13 A141: one course's (course_id null: every course's) multi-concept
 *  items — stored and held, served in the range and their graded outcomes in it. */
export interface LoopMultiConceptBlock {
  course_id: string | null;
  items: number;
  held: number;
  served: number;
  answered: number;
  correct: number;
  unassisted: number;
  unassisted_correct: number;
  students: number;
  /** correct / answered, with its Wilson 95% interval; null when nothing was answered */
  correct_rate: number | null;
  correct_ci_low: number | null;
  correct_ci_high: number | null;
}

export interface LoopMultiConcept {
  overall: LoopMultiConceptBlock;
  courses: LoopMultiConceptBlock[];
}

/** spec §13 A133: a median in seconds over n values (null when n = 0, never a zero). */
export interface LoopHelpMedian {
  n: number;
  median: number | null;
}

/** The next graded opportunity on the concept with another item. */
export interface LoopHelpNext {
  /** steps with a graded, non-void evidence row in the range */
  graded: number;
  unassisted_correct: number;
  other: number;
  /** no later opportunity in the range */
  none: number;
}

/** One group of the help-abuse report (overall, a band, a gate, a course, a student). */
export interface LoopHelpAbuseGroup {
  key: string;
  /** loop check items posed (student × session × item) */
  steps: number;
  /** help reached the bottom-out rung (H5) or above */
  bottom_outs: number;
  full_solutions: number;
  bottom_out_rate: number | null;
  time_to_bottom_out_s: LoopHelpMedian;
  /** seconds between consecutive new hint rungs on a step */
  help_gap_s: LoopHelpMedian;
  /** the same, on bottom-out steps, up to the bottom-out */
  climb_gap_s: LoopHelpMedian;
  /** counted hint-unlocking attempts: rapid = less than the band's independent
   *  time alone with the latest hint; repeat = nothing new; strict_refused =
   *  refused by the strict gate though the standard rule counted it */
  attempts: { counted: number; rapid: number; repeat: number; strict_refused: number };
  /** the counted attempts that bought a bottom-out's climb; unmeasured = no
   *  attempt record (a step before A134), never a zero */
  bottom_out_attempts: { measured: number; unmeasured: number; held_by_strict: number; no_strict_attempt: number };
  /** by the step's help: none / partial (H1–H4) / bottom_out (H5–H6) */
  next: Record<"none" | "partial" | "bottom_out", LoopHelpNext>;
}

/** spec §13 A133: help abuse on the loop's hint ladder, over the range. */
export interface LoopHelpAbuse {
  bottom_out_rung: number;
  overall: LoopHelpAbuseGroup;
  by_band: LoopHelpAbuseGroup[];
  /** standard / strict (the help_gate_strict flag, A134) / none (no hint attempt) */
  by_gate: LoopHelpAbuseGroup[];
  by_course: LoopHelpAbuseGroup[];
  /** most bottom-outs first */
  by_student: LoopHelpAbuseGroup[];
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
