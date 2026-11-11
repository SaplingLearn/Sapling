"""
backend/services/admin/analytics/learning_models.py — the response models of
GET /api/admin/analytics/learning-loop (learning-loop PKG-14, spec §10; moved
out of routes/admin_analytics.py with the #118 layout, spec §13 A149).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from services.admin.analytics.models import Range

TrendDirection = Literal["falling", "flat", "rising", "insufficient"]


class WeekPoint(BaseModel):
    week_start: str  # the Monday of the ISO week, YYYY-MM-DD (UTC)
    mean_rung: float  # mean max_rung_used over the week's correct steps
    steps: int


class ConceptTrend(BaseModel):
    concept_id: str
    weeks: list[WeekPoint]
    direction: TrendDirection


class CeilingCompliance(BaseModel):
    steps: int
    compliant: int
    rate: float | None


class NextSessionSuccess(BaseModel):
    sessions: int
    successes: int
    rate: float | None
    # spec §13 A106 (review m2): quiz-ask sessions (probe-less) left out of the rate
    quiz_ask_excluded: int = 0


class EarnestRevise(BaseModel):
    """Spec §10's earnest-revise gate (A109): graded check steps whose /hint was
    denied at the ceiling or the H6 gate after a genuine attempt."""

    graded_steps: int  # check steps carrying the earnest_blocked bool
    earnest_blocked: int
    unmeasured_steps: int  # check steps written before A109 (no key): not counted
    rate: float | None
    gate: Literal["pass", "fail", "inconclusive"]


class Gates(BaseModel):
    zero_leaks: bool
    ceiling_compliance_ok: bool
    # A109: None = inconclusive (no graded step carries the signal), never a pass
    earnest_revise_ok: bool | None


class CalibrationBin(BaseModel):
    lo: float
    hi: float
    n: int
    mean_predicted: float | None
    observed: float | None


class CalibrationReport(BaseModel):
    """BKT's predicted P(correct) vs observed outcomes on independent
    (strong-channel, unassisted, rung-0, full-weight) evidence
    (learning/calibration.py). None rates mean nothing to judge."""

    n: int
    brier: float | None
    mean_predicted: float | None
    observed_rate: float | None
    ece: float | None
    bins: list[CalibrationBin]


class Calibration(BaseModel):
    all: CalibrationReport
    posttest: CalibrationReport  # rung 3: fresh reserve item, tool-free, delayed
    # spec §13 A123: independent observations left out because they were
    # graded against an item staff retired (void evidence) — the drop, visible
    excluded_void: int = 0


class ConfidenceLevel(BaseModel):
    """One stated-confidence level (learning/calibration.py, spec §13 A127)."""

    level: str | None  # a STUDENT_CONFIDENCE_LEVELS label; None = a value no label names
    stated: float  # the level's value on the 0..1 scale
    n: int
    correct: int
    observed: float | None  # None when n = 0, never a zero


class ConfidenceReport(BaseModel):
    """The student's stated confidence against correctness (metacognitive
    calibration, spec §13 A127). None rates mean nothing to judge."""

    n: int
    mean_stated: float | None
    observed_rate: float | None
    overconfidence: float | None  # mean stated − observed; above 0 = surer than right
    brier: float | None
    levels: list[ConfidenceLevel]


class ChannelConfidenceReport(ConfidenceReport):
    channel: str


class ConfidenceCalibration(BaseModel):
    all: ConfidenceReport
    channels: list[ChannelConfidenceReport]  # only channels with a stated confidence


class GainSummary(BaseModel):
    """Pre/post outcomes over (student, concept) pairs (learning/learning_gain.py,
    spec §13 A112): the probe's unassisted pretest against the unassisted
    post-test. Observed outcomes only — never p_known. None rates: n = 0."""

    n: int
    pre_correct_rate: float | None
    post_correct_rate: float | None
    paired_difference: float | None  # mean(post − pre) over the pairs, in [−1, 1]
    improved: int  # pretest wrong → post-test right
    same: int
    worse: int  # pretest right → post-test wrong


class GainWindow(GainSummary):
    window_days: int  # a POSTTEST_WINDOWS_DAYS window
    posttests: int  # unassisted post-test outcomes in the window, paired or not
    # unassisted outcomes left out because staff retired their item (A113/A123:
    # retired as broken, so the outcome is void evidence) — the drop, visible
    excluded_retired: int
    # A126: the students behind the pairs, and the student-cluster bootstrap
    # percentile intervals ([lo, hi]; None below two students)
    students: int
    post_correct_ci: list[float] | None
    paired_difference_ci: list[float] | None
    delayed: GainSummary  # the pairs with no evidence for ≥ delayed_min_days before the pose
    # A126: the pairs whose page was hidden while the item was on screen (nothing
    # is excluded for it), and the outcomes with no visibility record
    visibility_loss: GainSummary
    visibility_unreported: int


class GainCi(BaseModel):
    """How the intervals were computed (A126) — enough to reproduce them."""

    method: str
    level: float
    resamples: int
    seed: str


class DelayBin(GainSummary):
    """Every window's pairs by the days from the anchor to the answer (A126)."""

    lo_days: int
    hi_days: int | None  # None: open-ended
    posttests: int


class FunnelWindow(BaseModel):
    """What happened to the windows that opened in the range (A126): every due
    window is answered, expired, open, skipped (by reason) or never opened;
    `still_open` counts the unanswered ones whose window has not closed."""

    window_days: int
    due: int
    opened: int
    answered: int
    unassisted: int
    excluded_retired: int  # answered on an item staff retired (A123): void
    expired: int
    open: int
    skipped: int
    skip_reasons: dict[str, int]
    not_opened: int
    still_open: int


class LearningGain(BaseModel):
    """Post-tests answered in the range, per fixed window (A112), with their
    uncertainty, actual delay and visibility (A126), and the funnel of the
    windows that opened in the range (None: the anchors could not be read)."""

    delayed_min_days: int
    ci: GainCi
    windows: list[GainWindow]
    delay_bins: list[DelayBin]
    delay_unknown: int
    delay_out_of_range: int
    funnel: list[FunnelWindow] | None


class CostWindow(BaseModel):
    """One post-test window's pairs against the range's loop spend (A137).
    Intervals are [lo, hi] with hi None when unbounded; None below two students."""

    window_days: int
    pairs: int
    students: int
    gain_points: int  # improved − worse: Σ(post − pre) over the pairs
    per_pair: float | None
    per_pair_ci: list[float | None] | None
    per_gain_point: float | None  # None unless gain_points > 0
    per_gain_point_ci: list[float | None] | None


class CostBlock(BaseModel):
    """The loop's spend, overall (course_id None) or for one course (A137)."""

    course_id: str | None
    cost_usd: float
    tutor_usd: float  # the tutor tiers: what §3.5's target prices
    drafting_usd: float  # check-item drafting and its checks (course assets)
    rows: int
    unpriced_rows: int  # rows with no cost_usd (an unpriced model): no dollars added
    active_students: int
    per_active_student_month: float | None
    tutor_per_active_student_month: float | None
    target_ratio: float | None  # per_active_student_month ÷ the §3.5 target
    sessions: int
    per_session: float | None  # the rows that carry a session, per session
    windows: list[CostWindow]


class CostUnattributed(BaseModel):
    cost_usd: float
    rows: int


class CostPerGain(BaseModel):
    """What the loop cost against what it measurably taught (spec §13 A137,
    learning/cost_per_gain.py): the loop tasks' llm_usage spend in the range,
    check-item drafting included, beside the learning-gain pairs answered in
    it, overall and per course. Every figure has its n; None means nothing to
    divide by, never zero. A row with no course of its own and no session is
    `unattributed` (overall only)."""

    target_usd_per_student_month: float
    range_days: float | None
    ci: GainCi
    overall: CostBlock
    courses: list[CostBlock]
    unattributed: CostUnattributed


class SlotWarning(BaseModel):
    """Spec §13 A128: an evidence-producing model slot this API process runs
    outside its evaluated set (`unevaluated`: reason pending_claude_eval |
    not_evaluated), or resolved to the model it must be independent of
    (`not_independent`: A22's second opinion, A124's key solve). The process's
    CURRENT configuration, not the date range: warnings are about now."""

    kind: Literal["unevaluated", "not_independent"]
    slot: str
    model: str
    reason: str | None = None
    independent_of: str | None = None
    rule: str | None = None


class HelpMedian(BaseModel):
    n: int
    median: float | None  # seconds; None when n = 0, never a zero


class HelpAttempts(BaseModel):
    """Counted hint-unlocking attempts and their signals (zpd.attempt, A134)."""

    counted: int
    rapid: int  # less than the band's independent time alone with the latest help
    repeat: int  # said nothing a counted attempt on the item had not said
    strict_refused: int  # under the strict gate: refused, though the §3.3 rule counted it


class BottomOutAttempts(BaseModel):
    """The counted attempts that bought a bottom-out's climb (below H5)."""

    measured: int
    unmeasured: int  # no attempt record (a step before A134): never a zero
    held_by_strict: int  # one climb attempt or more the strict rule would not count
    no_strict_attempt: int  # no climb attempt the strict rule would count


class HelpNextOutcome(BaseModel):
    """The next graded opportunity on the concept with another item."""

    graded: int  # steps with a graded, non-void evidence row in the range
    unassisted_correct: int
    other: int
    none: int  # no later opportunity in the range


class HelpAbuseGroup(BaseModel):
    key: str
    steps: int  # loop check items posed (student × session × item)
    bottom_outs: int
    full_solutions: int
    bottom_out_rate: float | None
    time_to_bottom_out_s: HelpMedian
    help_gap_s: HelpMedian
    climb_gap_s: HelpMedian
    attempts: HelpAttempts
    bottom_out_attempts: BottomOutAttempts
    next: dict[str, HelpNextOutcome]  # by the step's help: none / partial / bottom_out


class HelpAbuse(BaseModel):
    """Spec §13 A133: help abuse, measured (learning/help_abuse.py)."""

    bottom_out_rung: int
    overall: HelpAbuseGroup
    by_band: list[HelpAbuseGroup]
    by_gate: list[HelpAbuseGroup]
    by_course: list[HelpAbuseGroup]
    by_student: list[HelpAbuseGroup]
    truncated: bool = False


class SelfExplainNextItem(BaseModel):
    n: int  # prompts with a later graded item on the concept in the range
    unassisted: int
    rate: float | None
    none: int  # prompts with no later graded item in the range


class SelfExplainNext(BaseModel):
    replied: SelfExplainNextItem
    not_replied: SelfExplainNextItem


class SelfExplainChars(BaseModel):
    median: float | None
    n: int


class SelfExplainJuncture(BaseModel):
    juncture: str
    shown: int
    replied: int
    reply_rate: float | None
    next_item: SelfExplainNext


class SelfExplanation(BaseModel):
    """Spec §13 A139: self-explanation prompts — shown, the reply rate, the
    median reply length and next-item unassisted success after replying vs
    not, each with its n (learning/self_explain_report.py)."""

    shown: int
    replied: int
    skipped: int
    open: int
    reply_rate: float | None
    reply_chars: SelfExplainChars
    next_item: SelfExplainNext
    by_juncture: list[SelfExplainJuncture]
    truncated: bool = False
class MultiConceptBlock(BaseModel):
    """Spec §13 A141: one course's (or, course_id None, every course's)
    multi-concept items — stored, served and their outcomes in the range."""

    course_id: str | None
    items: int  # stored multi-concept items (held ones included)
    held: int
    served: int  # learn.multi_concept_served in the range
    answered: int  # graded answers on them in the range (void rows left out)
    correct: int
    unassisted: int
    unassisted_correct: int
    students: int  # distinct students who answered one
    correct_rate: float | None  # correct / answered; None when nothing was answered
    correct_ci_low: float | None  # its Wilson 95% interval
    correct_ci_high: float | None


class MultiConcept(BaseModel):
    """Spec §13 A141 (learning/multi_concept_report.py)."""

    overall: MultiConceptBlock
    courses: list[MultiConceptBlock]


class LearningLoopKpis(BaseModel):
    range: Range
    steps_total: int
    banded_steps: int
    in_band: int
    in_band_share: float | None
    htc_k_trend: list[ConceptTrend]
    unassisted_next_session: NextSessionSuccess
    # m5 (spec §13 A90): zpd.leak is a leak CAUGHT on the active item and
    # redacted before serving; the gate counts solutions actually SERVED
    caught_leaks: int
    served_reveals: int  # open posed items whose answer a served turn stated
    unscanned_turns: int  # served turns whose open items could not be read (fail-closed)
    ceiling_compliance: CeilingCompliance
    earnest_revise: EarnestRevise
    gates: Gates
    calibration: Calibration
    # spec §13 A127: do students know what they know? stated confidence vs correctness
    confidence_calibration: ConfidenceCalibration
    learning_gain: LearningGain
    # A137: the loop's spend against the learning gain; None when the spend
    # could not be read (the rest of the report stands)
    cost_per_gain: CostPerGain | None = None
    # A128: the active evidence-slot warnings ([] when none; never blocking)
    slot_warnings: list[SlotWarning] = Field(default_factory=list)
    # spec §13 A133: help abuse — None when its reads failed (the rest stands)
    help_abuse: HelpAbuse | None = None
    # spec §13 A139: self-explanation prompts — None when its read failed
    self_explanation: SelfExplanation | None = None
    # spec §13 A141: multi-concept items stored, served and their outcomes —
    # None when its reads failed (the rest stands)
    multi_concept: MultiConcept | None = None
    truncated: bool = False
