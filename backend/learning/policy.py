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
from learning.ladder import Rung

Band = Literal["novice", "develop", "profic"]
Tier = Literal["lite", "standard", "deep", "none"]  # "none" = no model call (template or pause)
TurnPhase = Literal["opener", "teach", "check_pose", "hint", "feedback_correct", "feedback_wrong"]
ContextPhase = Literal["teach", "check", "hint", "feedback"]
BudgetLevel = Literal["normal", "soft", "hard"]
ToolChoice = Literal["auto", "none"]
LOOP_STATE_VERSION = 1
WINDOW_KEEP = params.BAND_WINDOW * params.BAND_CONTROL_STOP_WINDOWS
_BANDS = get_args(Band)


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
    DEVELOP = "develop"
    DEVELOP_H6 = "develop_h6"
    NOVICE_PREREQ_OK = "novice_prereq_ok"
    NOVICE_WORKED_FIRST = "novice_worked_first"
    NOVICE_PREREQ_GAP = "novice_prereq_gap"
    SHOWED_WORK_FLOOR = "showed_work_floor"


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


def ceiling_with_reason(learner: LearnerView, step: StepState) -> tuple[Rung, CeilingReason]:
    """Highest rung this turn may reach, first-match over the §3.3 table.

    While a step is open every recorded genuine attempt is a failed one (a
    correct attempt closes the step), so `genuine_attempts` is the table's
    failed-attempt count. The shown-work floor comes last and never applies in
    exam mode: exam mode is the strictest row and wins (A4)."""
    fails = step.genuine_attempts
    if fails < 0:
        raise ValueError(f"genuine_attempts must be >= 0, got {fails}")
    if learner.band not in _BANDS:
        raise ValueError(f"unknown band {learner.band!r}")
    if step.exam_mode:
        return Rung.H1, CeilingReason.EXAM
    if learner.band == "profic":
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
    if step.showed_work and rung < Rung.H3:
        return Rung.H3, CeilingReason.SHOWED_WORK_FLOOR
    return rung, reason


def ceiling(learner: LearnerView, step: StepState) -> Rung:
    return ceiling_with_reason(learner, step)[0]


def attempt_first(learner: LearnerView) -> bool:
    """False only for a novice without the prerequisite: worked example first."""
    return not (learner.band == "novice" and not learner.prereq_proficient)


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
    each above BAND_CONTROL_HI; a partial window never counts."""
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
        malformed PKG-06 unit starts fresh on its own (a step that fails
        validation is dropped; a bad `current` / `checks_since_rating` takes
        its default) and every key PKG-06 does not own survives in `extra`, so
        the next save never erases a later package's state ("revealed", "plan",
        the session request counters). A non-object document keeps nothing."""
        if not isinstance(data, dict):
            return cls()
        steps: dict[str, StepState] = {}
        raw_steps = data.get("steps")
        for qh, raw in raw_steps.items() if isinstance(raw_steps, dict) else ():
            try:
                steps[str(qh)] = _step_from_json(str(qh), raw)
            except (ValueError, TypeError):
                continue
        current = data.get("current")
        try:
            checks = _count(data.get("checks_since_rating", 0), "checks_since_rating")
        except ValueError:
            checks = 0
        return cls(
            steps=steps,
            current=current if isinstance(current, str) else None,
            checks_since_rating=checks,
            extra=_foreign_keys(data),
        )


def _foreign_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in data.items() if k not in _TOP_KEYS}
