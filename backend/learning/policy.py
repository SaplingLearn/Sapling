"""ZPD policy (spec §3.3) plus the loop tutor's tier and context routing
(spec §3.5, §13 A15/A18). Pure and typed: inputs are learner state and step
state, never student text (invariant 4). Timestamps are float Unix seconds.

Every threshold is a `params` name; the only bare numerals are identities
(0/1) and `Rung` members. Nothing here reads the database, config, budgets or
the clock: callers pass the state in (PKG-07 wires it).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, NamedTuple, Sequence, get_args

from learning import params
from learning.arms import Variant
from learning.ladder import ItemLike, Rung

Band = Literal["novice", "develop", "profic"]
Tier = Literal["lite", "standard", "deep", "none"]  # "none" = no model call (template or pause)
TurnPhase = Literal["opener", "teach", "check_pose", "hint", "feedback_correct", "feedback_wrong"]
ContextPhase = Literal["teach", "check", "hint", "feedback"]
BudgetLevel = Literal["normal", "soft", "hard"]
ToolChoice = Literal["auto", "none"]
LOOP_STATE_VERSION = 1
WINDOW_KEEP = params.BAND_WINDOW * params.BAND_CONTROL_STOP_WINDOWS
_BANDS = get_args(Band)
# spec §13 A122: the band-control ceiling moves §3.3 states ("ceiling −1 / +1 rung")
_CEILING_DELTAS = frozenset(
    {-params.BAND_CONTROL_CEILING_STEP, 0, params.BAND_CONTROL_CEILING_STEP}
)


class BandAction(str, Enum):
    STOP_PRACTICE = "stop_practice"
    HARDER = "harder"
    HOLD = "hold"
    EASIER_CHECK_PREREQS = "easier_check_prereqs"
    WHEELSPIN = "wheelspin"


class CeilingReason(str, Enum):
    EXAM = "exam"
    PROFIC = "profic"
    PROFIC_ESCALATED = "profic_escalated"
    # A110 (c): profic belief with no strong unassisted observation behind it
    PROFIC_UNCONFIRMED = "profic_unconfirmed"
    DEVELOP = "develop"
    DEVELOP_H6 = "develop_h6"
    NOVICE_PREREQ_OK = "novice_prereq_ok"
    NOVICE_WORKED_FIRST = "novice_worked_first"
    NOVICE_PREREQ_GAP = "novice_prereq_gap"
    SHOWED_WORK_FLOOR = "showed_work_floor"
    # PKG-14 (A85): a teach-phase genuine attempt (a reasoned claim) raised it
    TEACH_ATTEMPT = "teach_attempt"
    # PKG-14 (spec §10 rung 3): the tool-removed post-test forces H0
    POSTTEST = "posttest"
    # spec §13 A122: band control's ceiling clause moved the band's row a rung
    BAND_CONTROL = "band_control"


@dataclass
class StepState:
    question_hash: str
    rung: Rung = Rung.H0
    genuine_attempts: int = 0  # failed genuine attempts while the step is open
    first_shown_at: float = 0.0
    last_rung_at: float | None = None
    attempted_at: list[float] = field(default_factory=list)  # genuine attempts only
    showed_work: bool = False
    exam_mode: bool = False
    # step keys PKG-06 does not own (a later package's per-item fields), carried
    # through a load/save untouched
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LearnerView:
    p_known: float
    band: Band
    prereq_proficient: bool
    unassisted_next: float | None
    opps: int
    streak_unassisted: int
    # Strong-channel unassisted observations behind the belief (learner_state).
    # None = the caller did not supply it: the profic row applies unchanged.
    n_strong_unassisted: int | None = None


class RungEvidence(NamedTuple):
    weight: float
    counts_toward_streak: bool
    fsrs_rating: int


class ContextPolicy(NamedTuple):
    rag_k: int
    graph_block: bool
    source_chunks: int  # how many of the item's source_chunk_ids the caller resolves
    catalog: bool
    tool_choice: ToolChoice  # "none" -> ModelSettings(tool_choice='none'); declarations unchanged


# ── ceiling (spec §3.3 CEILING; §13 A4) ──────────────────────────────────────


#: PKG-14 (A85): the highest ceiling a teach attempt may raise a band to — what
#: the band allows after attempts (profic escalated H3, develop H6, novice H5).
TEACH_ATTEMPT_CEILING_CAP: dict[str, Rung] = {
    "profic": Rung.H3,
    "develop": Rung.H6,
    "novice": Rung.H5,
}


def ceiling_with_reason(
    learner: LearnerView, step: StepState, *, teach_attempt: bool = False, band_delta: int = 0
) -> tuple[Rung, CeilingReason]:
    """Highest rung this turn may reach, first-match over the §3.3 table.

    `teach_attempt` (PKG-14, A85): the caller judged THIS teach-phase message a
    genuine attempt (gates.teach_turn_ceiling — a reasoned claim); the ceiling
    rises TEACH_ATTEMPT_CEILING_RAISE rung (TEACH_ATTEMPT_CEILING_RAISE_PROFIC for
    the profic band, owner decision 2026-10-01), capped at TEACH_ATTEMPT_CEILING_CAP
    for the band, never in exam mode. It moves no evidence and no state.

    `band_delta` (spec §13 A122): band control's ceiling clause for the concept
    (`ceiling_delta`: −1 after HARDER, +1 after EASIER_CHECK_PREREQS, 0 else)
    moves the band's row that many rungs, clamped to the ladder (H0..H6); the
    reason is then BAND_CONTROL. It changes the band's ceiling only: exam mode
    still returns H1, the shown-work floor and the teach-attempt cap apply after
    it, and every gate — the attempt/dwell gate, the H6 item predicates (A32),
    the help floor, the leak checks — runs where it always ran.

    While a step is open every recorded genuine attempt is a failed one (a
    correct attempt closes the step), so `genuine_attempts` is the table's
    failed-attempt count. The shown-work floor comes last and never applies in
    exam mode: exam mode is the strictest row and wins (A4)."""
    fails = step.genuine_attempts
    if fails < 0:
        raise ValueError(f"genuine_attempts must be >= 0, got {fails}")
    if learner.band not in _BANDS:
        raise ValueError(f"unknown band {learner.band!r}")
    if isinstance(band_delta, bool) or band_delta not in _CEILING_DELTAS:
        raise ValueError(f"band_delta must be one of {sorted(_CEILING_DELTAS)}, got {band_delta!r}")
    if step.exam_mode:
        return Rung.H1, CeilingReason.EXAM
    unconfirmed = (
        learner.band == "profic"
        and learner.n_strong_unassisted is not None
        and learner.n_strong_unassisted < params.CEILING_PROFIC_CONFIRM_MIN_STRONG
    )
    if unconfirmed:
        # A110 (c): a profic belief that no strong unassisted answer has confirmed
        # (it rests on quiz mc, propagation or assisted work) gets the develop
        # row. Help is asymmetric (Tetzlaff et al. 2025): withholding it from a
        # novice who only looks proficient costs more than offering it to an
        # expert, so uncertainty resolves toward help.
        if fails >= params.CEILING_DEVELOP_H6_FAILS:
            rung = Rung.H6
        else:
            rung = Rung(min(int(Rung.H3) + fails, int(Rung.H6)))
        reason = CeilingReason.PROFIC_UNCONFIRMED
    elif learner.band == "profic":
        if fails >= params.CEILING_PROFIC_ESCALATE_FAILS:
            rung, reason = Rung.H3, CeilingReason.PROFIC_ESCALATED
        else:
            rung, reason = Rung.H1, CeilingReason.PROFIC
    elif learner.band == "develop":
        if fails >= params.CEILING_DEVELOP_H6_FAILS:
            rung, reason = Rung.H6, CeilingReason.DEVELOP_H6
        else:
            rung = Rung(min(int(Rung.H3) + fails, int(Rung.H6)))
            reason = CeilingReason.DEVELOP
    elif learner.prereq_proficient:
        rung, reason = Rung.H5, CeilingReason.NOVICE_PREREQ_OK
    elif fails == 0:
        rung, reason = Rung.H4, CeilingReason.NOVICE_WORKED_FIRST
    else:
        rung, reason = Rung.H5, CeilingReason.NOVICE_PREREQ_GAP
    if band_delta:
        moved = Rung(min(max(int(rung) + band_delta, int(Rung.H0)), int(Rung.H6)))
        if moved != rung:
            rung, reason = moved, CeilingReason.BAND_CONTROL
    if step.showed_work and rung < Rung.H3:
        return Rung.H3, CeilingReason.SHOWED_WORK_FLOOR
    if teach_attempt:
        cap = TEACH_ATTEMPT_CEILING_CAP[learner.band]
        step_up = (
            params.TEACH_ATTEMPT_CEILING_RAISE_PROFIC
            if learner.band == "profic"
            else params.TEACH_ATTEMPT_CEILING_RAISE
        )
        raised = Rung(min(int(rung) + step_up, int(cap)))
        if raised > rung:
            return raised, CeilingReason.TEACH_ATTEMPT
    return rung, reason


def ceiling(learner: LearnerView, step: StepState, *, band_delta: int = 0) -> Rung:
    return ceiling_with_reason(learner, step, band_delta=band_delta)[0]


def attempt_first(learner: LearnerView) -> bool:
    """False only for a novice without the prerequisite: worked example first.

    The ONE decision point for the §3.3 novice rows (spec §13 A122): the
    route's band format (agents.loop_tutor.phase_prefix), which item opens on
    the worked example (`opens_on_worked_example`) and the first hint's rung
    (`worked_example_rung`) all read it. `prereq_proficient` is False for a
    prerequisite status that is NOT_PROFICIENT or UNKNOWN (no prerequisite
    edge): "not known" is the row (`prerequisite_status`)."""
    return not (learner.band == "novice" and not learner.prereq_proficient)


def opens_on_worked_example(learner: LearnerView, *, shown_on_concept: bool) -> bool:
    """Spec §3.3 "novice and prerequisite not known → worked example FIRST (H4),
    then H5, then near-transfer" (§13 A122): a newly posed item opens on the
    worked example when `attempt_first` says no and no worked example was shown
    on its concept earlier in the session. The item after that one is the
    near-transfer: posed attempt-first, its hints climbing the ladder as usual."""
    return not attempt_first(learner) and not shown_on_concept


def worked_example_rung(
    learner: LearnerView, step: StepState, *, worked_first: bool, band_delta: int = 0
) -> Rung | None:
    """The rung the next hint on an item that opens on the worked example
    unlocks (§13 A122): H4 — with no genuine attempt and no dwell before it,
    since the example comes FIRST — while the step is below H4, `attempt_first`
    still says no and the step's ceiling (band control's `band_delta` applied)
    admits H4 (exam mode's H1 does not). None: the ordinary ladder
    (gates.rung_unlock, one rung at a time). H5 and every later rung keep the
    attempt + dwell gate."""
    if not worked_first or attempt_first(learner) or step.rung >= Rung.H4:
        return None
    return Rung.H4 if ceiling(learner, step, band_delta=band_delta) >= Rung.H4 else None


# ── evidence mapping (spec §3.3 EVIDENCE MAPPING) ────────────────────────────


def evidence_for_rung(correct: bool, max_rung: Rung, same_session: bool = False) -> RungEvidence:
    """BKT weight, streak credit and FSRS rating for one graded answer.

    Weight 0.0 (correct after H4..H6) is the "no upward BKT evidence" signal
    PKG-07 turns into an isomorph re-ask. The rung bounds are PKG-03's
    (`RUNG_ASSISTED_MIN`, `RUNG_NO_CREDIT_MIN`), so this agrees with
    `evidence.evidence_weight` and `fsrs.rating_for`. A same-session re-check
    is weighted by WEIGHT_SAME_SESSION_RECHECK and is not a first attempt, so it
    never extends the unassisted streak (as `apply_graph_update` counts it)."""
    rung = Rung(max_rung)
    if not correct:
        weight, streak, rating = 1.0, False, params.FSRS_RATING_AGAIN
    elif rung >= params.RUNG_NO_CREDIT_MIN:
        weight, streak, rating = 0.0, False, params.FSRS_RATING_AGAIN
    elif rung >= params.RUNG_ASSISTED_MIN:
        weight, streak, rating = params.WEIGHT_ASSISTED, False, params.FSRS_RATING_HARD
    else:
        weight, streak, rating = 1.0, not same_session, params.FSRS_RATING_GOOD
    if same_session:
        weight *= params.WEIGHT_SAME_SESSION_RECHECK
    return RungEvidence(weight, streak, rating)


# ── band control + wheel-spin (spec §3.3 BAND CONTROL) ───────────────────────


def _rate(window: Sequence[bool]) -> float:
    return sum(1 for hit in window if hit) / len(window)


def unassisted_rate(window: Sequence[bool]) -> float | None:
    """Mean of the newest BAND_WINDOW unassisted first-attempt outcomes."""
    recent = list(window)[-params.BAND_WINDOW :]
    return _rate(recent) if recent else None


def band_control(
    window: Sequence[bool], p_known: float, stable: bool, *, wheelspin: bool = False
) -> BandAction:
    """`window` is ONE concept's unassisted first-attempt outcomes (user x
    node, across sessions; newest last), built by the caller from that
    concept's evidence rows, and `p_known` is that concept's (spec §3.3; the ZPD
    report's STATE block). Never a per-session or cross-concept list: loop_state
    keeps no window. STOP_PRACTICE needs BAND_CONTROL_STOP_WINDOWS FULL windows
    each above BAND_CONTROL_HI; a partial window never counts. HARDER needs at
    least BAND_CONTROL_HARDER_MIN_ATTEMPTS outcomes in the window (owner
    decision A38 06(m): one correct answer is not evidence to move up); a
    shorter high window HOLDs. EASIER_CHECK_PREREQS acts on any window."""
    if wheelspin:
        return BandAction.WHEELSPIN
    outcomes = list(window)[-WINDOW_KEEP:]
    rate = unassisted_rate(outcomes)
    if rate is None:
        return BandAction.HOLD
    if rate > params.BAND_CONTROL_HI:
        size, n = params.BAND_WINDOW, len(outcomes)
        all_high = n >= size * params.BAND_CONTROL_STOP_WINDOWS and all(
            _rate(outcomes[n - (k + 1) * size : n - k * size]) > params.BAND_CONTROL_HI
            for k in range(params.BAND_CONTROL_STOP_WINDOWS)
        )
        if all_high and p_known >= params.BKT_PROFICIENT and stable:
            return BandAction.STOP_PRACTICE
        if len(outcomes[-params.BAND_WINDOW :]) < params.BAND_CONTROL_HARDER_MIN_ATTEMPTS:
            return BandAction.HOLD
        return BandAction.HARDER
    if rate < params.PRACTICE_TARGET_LO:
        return BandAction.EASIER_CHECK_PREREQS
    return BandAction.HOLD


def wheelspin(opps: int, ever_streak3: bool, unassisted_next: float | None) -> bool:
    """`ever_streak3` = learner_state.max_streak_unassisted ≥ BKT_MASTERED_MIN_STRONG
    (A3); the caller computes it. `unassisted_next is None` never satisfies the
    second clause."""
    if opps >= params.WHEELSPIN_OPPS and not ever_streak3:
        return True
    return (
        unassisted_next is not None
        and opps >= params.WHEELSPIN_OPPS_EARLY
        and unassisted_next < params.WHEELSPIN_UNASSISTED_MAX
    )


# ── the controller after a graded check (spec §3.3, §13 A122) ────────────────
# The route reads the concept's evidence window and learner state after the
# check's evidence is flushed, asks `band_verdict`, stores the verdict on the
# graded step, and applies it when the feedback turn is served: the next item's
# difficulty (`next_difficulty`), the plan cursor (`cursor_move`) and the
# prerequisite repair (`repair_target`). It chooses WHAT is posed next — never
# how much help: the ceiling, the gates and the leak guards are untouched.

BandTrigger = Literal["high", "stable_high", "low", "wheelspin"]

#: zpd.band_adjust's `trigger` for each verdict that adjusts something (spec §6).
BAND_TRIGGERS: dict[BandAction, BandTrigger] = {
    BandAction.HARDER: "high",
    BandAction.STOP_PRACTICE: "stable_high",
    BandAction.EASIER_CHECK_PREREQS: "low",
    BandAction.WHEELSPIN: "wheelspin",
}


class Opportunity(NamedTuple):
    """One graded opportunity on a concept: a node_mastery_events evidence row
    that names its item (a question_hash) — the rows the nightly
    scripts/derive_zpd_metrics.py derives unassisted_next and htc_k from."""

    correct: bool
    assisted: bool
    max_rung: int
    p_before: float | None = None
    p_after: float | None = None


def unassisted_first(op: Opportunity) -> bool:
    """The outcome §3.3's window holds (the ZPD report's STATE block:
    "first-attempt correct with zero hints"): correct, unassisted, at H0 —
    the nightly metric's `_unassisted_zero`, so the live rate and the stored
    learner_state.unassisted_next read one definition."""
    return op.correct and not op.assisted and op.max_rung == Rung.H0


def hints_to_criterion(opportunities: Sequence[Opportunity]) -> float | None:
    """htc_k (the ZPD report's STATE block): the mean max_rung over the CORRECT
    opportunities among the newest HTC_K_WINDOW, None when none is correct —
    derive_zpd_metrics.compute's definition, on the live window."""
    recent = list(opportunities)[-params.HTC_K_WINDOW :]
    rungs = [op.max_rung for op in recent if op.correct]
    return sum(rungs) / len(rungs) if rungs else None


def stable_belief(opportunities: Sequence[Opportunity]) -> bool:
    """§3.3 STOP_PRACTICE's "belief stable": the newest opportunity moved the
    concept's p_known by less than BAND_CONTROL_STABLE_DELTA. No opportunity,
    or a newest one without both posteriors, is not stable (fail closed:
    practice is never stopped on an unknown)."""
    if not opportunities:
        return False
    newest = opportunities[-1]
    if newest.p_before is None or newest.p_after is None:
        return False
    return abs(newest.p_after - newest.p_before) < params.BAND_CONTROL_STABLE_DELTA


class BandVerdict(NamedTuple):
    action: BandAction
    rate: float | None  # unassisted_next: the newest BAND_WINDOW's unassisted share
    n: int  # outcomes in that window
    full_windows: int  # complete BAND_WINDOWs read (≤ BAND_CONTROL_STOP_WINDOWS)
    stable: bool
    wheelspin: bool
    htc_k: float | None


def band_verdict(
    opportunities: Sequence[Opportunity],
    *,
    p_known: float,
    opps: int,
    max_streak_unassisted: int,
) -> BandVerdict:
    """The §3.3 band controller after a graded check, on typed state only.

    `opportunities` is ONE concept's newest-last window (only the newest
    WINDOW_KEEP are read), `p_known` its decayed belief after the check, `opps`
    and `max_streak_unassisted` its learner_state counters (A3: ever_streak3 =
    max_streak_unassisted ≥ BKT_MASTERED_MIN_STRONG). wheelspin's
    unassisted_next is the window's LIVE rate — the number band_control acts
    on — never the nightly column, which lags by up to a day."""
    ops = list(opportunities)[-WINDOW_KEEP:]
    window = [unassisted_first(op) for op in ops]
    rate = unassisted_rate(window)
    ever_streak3 = max_streak_unassisted >= params.BKT_MASTERED_MIN_STRONG
    spinning = wheelspin(opps, ever_streak3, rate)
    stable = stable_belief(ops)
    return BandVerdict(
        action=band_control(window, p_known, stable, wheelspin=spinning),
        rate=rate,
        n=len(window[-params.BAND_WINDOW :]),
        full_windows=len(window) // params.BAND_WINDOW,
        stable=stable,
        wheelspin=spinning,
        htc_k=hints_to_criterion(ops),
    )


def next_difficulty(action: BandAction, difficulty: int) -> int | None:
    """The target difficulty of the concept's next item after a verdict on an
    item of `difficulty` (§3.3): HARDER one BAND_CONTROL_DIFFICULTY_STEP up,
    EASIER_CHECK_PREREQS one step down — "down freely": nothing gates it,
    whereas HARDER needs BAND_CONTROL_HARDER_MIN_ATTEMPTS outcomes, so
    consecutive low verdicts walk it down to the easiest — clamped to
    CHECK_ITEM_DIFFICULTIES. None for every other verdict: the target stands."""
    levels = params.CHECK_ITEM_DIFFICULTIES
    if action is BandAction.HARDER:
        step = params.BAND_CONTROL_DIFFICULTY_STEP
    elif action is BandAction.EASIER_CHECK_PREREQS:
        step = -params.BAND_CONTROL_DIFFICULTY_STEP
    else:
        return None
    return min(max(difficulty + step, min(levels)), max(levels))


def ceiling_delta(action: BandAction) -> int:
    """§3.3's ceiling clause for a verdict (spec §13 A122): HARDER "ceiling −1
    rung", EASIER_CHECK_PREREQS "ceiling +1 rung" (BAND_CONTROL_CEILING_STEP);
    0 for every other verdict. The concept's delta is the last nonzero one
    (HOLD holds it, as it holds the difficulty); `ceiling_with_reason` applies
    it to the band's row only, clamped, never past a gate."""
    if action is BandAction.HARDER:
        return -params.BAND_CONTROL_CEILING_STEP
    if action is BandAction.EASIER_CHECK_PREREQS:
        return params.BAND_CONTROL_CEILING_STEP
    return 0


class PrerequisiteStatus(str, Enum):
    PROFICIENT = "proficient"
    NOT_PROFICIENT = "not_proficient"
    UNKNOWN = "unknown"


class Prerequisite(NamedTuple):
    """One prerequisite parent of a concept (a `prerequisite` graph edge,
    oriented by EDGE_PREREQ_SOURCE_IS_PREREQ) and its decayed belief."""

    node_id: str
    p_known: float


def prerequisite_status(prerequisites: Sequence[Prerequisite]) -> PrerequisiteStatus:
    """The §3.3 ceiling's prerequisite input (spec §13 A122). PROFICIENT when
    every parent is in the profic band (p_known ≥ BAND_DEVELOP_MAX, the band the
    ceiling table reads); NOT_PROFICIENT when one is below it; UNKNOWN when the
    concept has no prerequisite edge — no edge is no evidence either way (a
    course graph without prerequisite edges, or a concept whose prerequisites
    the graph does not hold), so it never reads as proficient. UNKNOWN takes the
    "prerequisite not known" row: `LearnerView.prereq_proficient` is True only
    for PROFICIENT."""
    if not prerequisites:
        return PrerequisiteStatus.UNKNOWN
    if all(p.p_known >= params.BAND_DEVELOP_MAX for p in prerequisites):
        return PrerequisiteStatus.PROFICIENT
    return PrerequisiteStatus.NOT_PROFICIENT


def repair_target(prerequisites: Sequence[Prerequisite]) -> Prerequisite | None:
    """§3.3 prerequisite repair: the WEAKEST unproficient prerequisite parent
    (the lowest p_known below BAND_DEVELOP_MAX; ties by node id), else None —
    every parent is proficient, or the concept has none (UNKNOWN repairs
    nothing: there is no edge to follow)."""
    weak = [p for p in prerequisites if p.p_known < params.BAND_DEVELOP_MAX]
    return min(weak, key=lambda p: (p.p_known, p.node_id)) if weak else None


class CursorMove(str, Enum):
    STAY = "stay"  # the concept keeps its plan slot; LOOP_CHECKS_PER_CONCEPT decides
    ADVANCE = "advance"  # the concept leaves the session now
    REPAIR_RETURN = "repair_return"  # the prerequisite first, then the concept again
    REPAIR_REPLACE = "repair_replace"  # the prerequisite instead; the concept does not return


def cursor_move(action: BandAction, *, repair_available: bool) -> CursorMove:
    """What a verdict does to the plan cursor (§3.3 band control, §13 A122).
    STOP_PRACTICE: stop practice, hand the concept to the scheduler (FSRS
    already holds it) → ADVANCE. WHEELSPIN: stop more-of-the-same — no more
    checks on the concept this session — and repair the weakest prerequisite in
    its place when there is one (REPAIR_REPLACE), else ADVANCE. "Flag
    instructor" is the zpd.wheelspin error event: there is no instructor role.
    EASIER_CHECK_PREREQS: check prerequisites — a weak one is taught first and
    the concept comes back after it (REPAIR_RETURN), else the easier next item
    is the whole adjustment (STAY). HARDER and HOLD: STAY. `repair_available`:
    a repair target exists and this concept has not sent the student to it
    already this session."""
    if action is BandAction.STOP_PRACTICE:
        return CursorMove.ADVANCE
    if action is BandAction.WHEELSPIN:
        return CursorMove.REPAIR_REPLACE if repair_available else CursorMove.ADVANCE
    if action is BandAction.EASIER_CHECK_PREREQS and repair_available:
        return CursorMove.REPAIR_RETURN
    return CursorMove.STAY


# ── tutor tier routing (spec §3.5 LOOP_MODEL_TIER, §13 A15) ──────────────────


def _base_tier(
    phase: TurnPhase,
    band: Band,
    rung: Rung,
    failed_genuine_attempts: int,
    misconception_active: bool,
    deterministic_payload: bool,
) -> Tier:
    """LOOP_MODEL_TIER rows 2-5 (spec §3.5), first match wins."""
    hint = phase == "hint"
    if (
        phase == "check_pose"
        or (hint and rung == Rung.H6)
        or (hint and rung in (Rung.H2, Rung.H4) and deterministic_payload)
    ):
        return "none"
    if phase == "feedback_correct" or (hint and rung == Rung.H0 and band == "profic"):
        return "lite"
    if (
        (phase == "teach" and band == "novice")
        or (hint and rung in (Rung.H4, Rung.H5))
        or misconception_active
        or failed_genuine_attempts >= params.LOOP_TIER_DEEP_MIN_FAILS
    ):
        return "deep"
    # opener, develop/profic teach, H1/H3, feedback_wrong; † any turn the table does not name
    return "standard"


def model_tier(
    phase: TurnPhase,
    band: Band,
    rung: Rung,
    failed_genuine_attempts: int,
    misconception_active: bool,
    *,
    deterministic_payload: bool = False,
    budget_level: BudgetLevel = "normal",
    deep_cap_reached: bool = False,
    novice_deep_cap_reached: bool = False,
    arm_session: bool = False,
) -> Tier:
    """Tutor tier for one turn (spec §3.5 LOOP_MODEL_TIER, §13 A15). Typed state in,
    tier out; never the student's text (invariant 4). Adjustments only lower deep.

    `deterministic_payload` is True only when the caller already holds a
    leak-clean payload for this rung (ladder.deterministic_content +
    leak.detect_leak). The two cap booleans are the caller's comparisons with
    PKG-06b's LOOP_SESSION_MAX_DEEP_REQUESTS(_NOVICE); this function never reads
    a budget. `loop_arm` sessions are never downgraded; they pause at hard."""
    if budget_level == "hard":
        return "none"
    tier = _base_tier(
        phase,
        band,
        Rung(rung),
        failed_genuine_attempts,
        misconception_active,
        deterministic_payload,
    )
    if tier != "deep" or arm_session:
        return tier
    if band == "novice":
        # the $-based soft level never downgrades novice deep turns; only the novice cap does
        return "standard" if novice_deep_cap_reached else "deep"
    return "standard" if (budget_level == "soft" or deep_cap_reached) else "deep"


# ── context and tool policy by phase (spec §13 A18) ──────────────────────────


def context_policy(
    phase: ContextPhase, *, opener: bool, budget_level: BudgetLevel
) -> ContextPolicy:
    """What context a loop run gets. teach: RAG + the graph block, tools on only
    at the normal level; hint/feedback: the item's own source chunks (resolved by
    PKG-07 through the visibility-aware reader), no tools; check: nothing. The
    catalog rides the opener only. `hard` returns the soft policy: no model runs
    at hard (model_tier gives "none"), so it matters only to a caller that
    ignores model_tier."""
    constrained = budget_level != "normal"
    if phase == "teach":
        return ContextPolicy(
            params.LOOP_RAG_K_TEACH_SOFT if constrained else params.LOOP_RAG_K_TEACH,
            True,
            0,
            opener,
            "none" if constrained else "auto",
        )
    if phase in ("hint", "feedback"):
        return ContextPolicy(0, False, params.LOOP_SOURCE_CHUNKS_MAX, opener, "none")
    return ContextPolicy(0, False, 0, opener, "none")


# ── sessions.loop_state document (spec §4, §9) ───────────────────────────────

_STEP_KEYS = (
    "rung",
    "attempts",
    "first_shown_at",
    "last_rung_at",
    "attempted_at",
    "showed_work",
    "exam_mode",
)
_TOP_KEYS = ("v", "current", "checks_since_rating", "steps")


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"loop_state: {what} must be an int >= 0, got {value!r}")
    return value


def _flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"loop_state: {what} must be a bool, got {value!r}")
    return value


def _step_from_json(question_hash: str, raw: object) -> StepState:
    if not isinstance(raw, dict):
        raise ValueError(f"loop_state: step {question_hash!r} is not an object")
    first = raw.get("first_shown_at")
    if not _is_number(first):
        raise ValueError(f"loop_state: step {question_hash!r} lacks a numeric first_shown_at")
    last = raw.get("last_rung_at")
    if last is not None and not _is_number(last):
        raise ValueError(f"loop_state: step {question_hash!r} last_rung_at must be a number")
    attempted = raw.get("attempted_at", [])
    if not isinstance(attempted, list) or not all(_is_number(t) for t in attempted):
        raise ValueError(f"loop_state: step {question_hash!r} attempted_at must be numbers")
    return StepState(
        question_hash=question_hash,
        rung=Rung(_count(raw.get("rung", 0), "rung")),
        genuine_attempts=_count(raw.get("attempts", 0), "attempts"),
        first_shown_at=float(first),
        last_rung_at=None if last is None else float(last),
        attempted_at=[float(t) for t in attempted],
        showed_work=_flag(raw.get("showed_work", False), "showed_work"),
        exam_mode=_flag(raw.get("exam_mode", False), "exam_mode"),
        extra={k: copy.deepcopy(v) for k, v in raw.items() if k not in _STEP_KEYS},
    )


@dataclass
class LoopState:
    """The typed view of `sessions.loop_state`: ids, numbers and bools only.

    `extra` carries every top-level key this package does not own ("revealed",
    "plan", "probe", "sr", "review", … added by PKG-07+), and `StepState.extra`
    every step key it does not own, uninterpreted, so a load/save round trip
    never drops a later package's state. The typed keys win over a same-named
    extra."""

    steps: dict[str, StepState] = field(default_factory=dict)
    current: str | None = None
    checks_since_rating: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def rating_due(self) -> bool:
        return self.checks_since_rating >= params.ZPD_RATING_EVERY_N_CHECKS

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = copy.deepcopy(self.extra)
        doc.update(
            {
                "v": LOOP_STATE_VERSION,
                "current": self.current,
                "checks_since_rating": self.checks_since_rating,
                "steps": {
                    qh: {
                        **copy.deepcopy(s.extra),
                        "rung": int(s.rung),
                        "attempts": s.genuine_attempts,
                        "first_shown_at": s.first_shown_at,
                        "last_rung_at": s.last_rung_at,
                        "attempted_at": list(s.attempted_at),
                        "showed_work": s.showed_work,
                        "exam_mode": s.exam_mode,
                    }
                    for qh, s in self.steps.items()
                },
            }
        )
        return doc

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LoopState:
        """Parse a stored document; `{}` is a fresh state. Raises ValueError on
        a malformed PKG-06 key (the store turns that into a fresh state)."""
        if not isinstance(data, dict):
            raise ValueError("loop_state: document is not an object")
        steps_raw = data.get("steps", {})
        if not isinstance(steps_raw, dict):
            raise ValueError("loop_state: steps must be an object")
        current = data.get("current")
        if current is not None and not isinstance(current, str):
            raise ValueError("loop_state: current must be a question_hash or null")
        return cls(
            steps={str(qh): _step_from_json(str(qh), raw) for qh, raw in steps_raw.items()},
            current=current,
            checks_since_rating=_count(data.get("checks_since_rating", 0), "checks_since_rating"),
            extra=_foreign_keys(data),
        )

    @classmethod
    def recover(cls, data: object) -> LoopState:
        """The store's fallback when from_json rejects a stored document. Each
        malformed PKG-06 unit starts fresh on its own and every key PKG-06 does
        not own survives, at the top level in `extra` and on a step in its
        `StepState.extra`, so the next save never erases a later package's
        state ("revealed", "plan", the session request counters, a step's
        check_item_id / taught). A step that fails validation restarts with
        its PKG-06 fields at their defaults (a finite first_shown_at kept, and
        exam mode unless the stored exam_mode is absent or False); a
        non-object step, or every step when `steps` is not an object, is
        dropped, and `current` naming a dropped step is cleared; a bad
        `current` / `checks_since_rating` takes its default. A non-object
        document keeps nothing."""
        if not isinstance(data, dict):
            return cls()
        steps: dict[str, StepState] = {}
        raw_steps = data.get("steps", {})
        dropped = not isinstance(raw_steps, dict)
        for qh, raw in raw_steps.items() if isinstance(raw_steps, dict) else ():
            try:
                steps[str(qh)] = _step_from_json(str(qh), raw)
            except (ValueError, TypeError):
                steps.update(_fresh_step(str(qh), raw))
        current = data.get("current")
        if not isinstance(current, str) or (
            current not in steps and (dropped or current in raw_steps)
        ):
            current = None
        try:
            checks = _count(data.get("checks_since_rating", 0), "checks_since_rating")
        except ValueError:
            checks = 0
        return cls(
            steps=steps,
            current=current,
            checks_since_rating=checks,
            extra=_foreign_keys(data),
        )


def _fresh_step(question_hash: str, raw: object) -> dict[str, StepState]:
    """A malformed step restarted: PKG-06 fields at their defaults (a finite
    first_shown_at kept), every other key kept in `extra`; {} for a non-object
    step, which has nothing to keep. Every default fails closed except
    exam_mode's, so the exam flag is kept: a stored `exam_mode` other than
    False (True, or a malformed value) is exam mode, never a lost H1 cap."""
    if not isinstance(raw, dict):
        return {}
    first = raw.get("first_shown_at")
    return {
        question_hash: StepState(
            question_hash=question_hash,
            first_shown_at=float(first) if _is_number(first) else 0.0,
            exam_mode=raw.get("exam_mode", False) is not False,
            extra={k: copy.deepcopy(v) for k, v in raw.items() if k not in _STEP_KEYS},
        )
    }


def _foreign_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in data.items() if k not in _TOP_KEYS}


def next_isomorph(item: ItemLike, items: Sequence[ItemLike]) -> ItemLike | None:
    """PKG-10 (spec §3.3 "re-ask an isomorph"; §13 A27: used inside PKG-07's
    `_activate_next_item`). The first check item in `items` that re-asks
    `item` in a different surface: same concept_key, same format, same
    difficulty, different question_hash (items are course assets keyed on
    concept_key, A2). None when there is none. Pure. `items` is already
    filtered by the caller (revealed hashes, the post-test reserve — A23 —
    and only servable items, A34); this never widens it."""
    for cand in items:
        if (
            cand.concept_key == item.concept_key
            and cand.format == item.format
            and cand.difficulty == item.difficulty
            and cand.question_hash != item.question_hash
        ):
            return cand
    return None


# ── within-student arms (PKG-14; spec §3.3, §10 rung 2) ─────────────────────
# `variant_for` (ids + the arm label in, variant out) lives in learning/arms.py:
# invariant 4 holds this module to typed, text-free parameters.


def independent_gate(band: Band, variant: Variant) -> str:
    """The name of the `GATE_*` independent-time constant for a band and the
    concept's variant (a name, so `params.gate_seconds` applies the A5 time
    scale to it). Variant B changes only the develop/profic gate; novice keeps
    GATE_INDEPENDENT_MIN_S_NOVICE for both."""
    if variant not in get_args(Variant):
        raise ValueError(f"unknown variant {variant!r}")
    if band == "novice":
        return "GATE_INDEPENDENT_MIN_S_NOVICE"
    return "GATE_INDEPENDENT_MIN_S_VARIANT_B" if variant == "B" else "GATE_INDEPENDENT_MIN_S"


def independent_min_s(band: Band, variant: Variant) -> int:
    """Seconds of independent work before an attempt is genuine (spec §3.3),
    unscaled, for a band and the concept's variant."""
    return getattr(params, independent_gate(band, variant))
