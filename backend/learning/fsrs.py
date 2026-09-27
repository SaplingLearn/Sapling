"""FSRS-6 scheduler for the learning loop (spec §3.2). Pure: no I/O, no DB, no LLM.

Stability ``S`` is in days (the time for retrievability to fall to 0.9),
difficulty ``D`` is in [1, 10], retrievability ``R`` is in (0, 1]. Every
formula below is the spec's over the weights ``params.FSRS_W``, plus the
FSRS-6 reference guards (py-fsrs 6.3.2, same weights) that the spec's
transcription omits; each is marked where it applies (HANDOFF-02 Deviations).
Ratings are the FSRS grades 1 Again / 2 Hard / 3 Good / 4 Easy; v1 never
emits Easy (``rating_for`` returns at most Good).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Iterable, Mapping, Sequence

from learning.params import (
    CHANNELS,
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_STABILITY_MIN,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_ORDER_THRESHOLD,
    REVIEW_SECONDS_PER_CHECK,
    RUNG_ASSISTED_MAX,
    SR_INITIAL_CRITERION,
    SR_RELEARN_SESSIONS,
)

W = FSRS_W
_DECAY = W[20]
_STABILITY_R = 0.9  # R(t = S) by the definition of stability (spec §3.2)
FACTOR = _STABILITY_R ** (-1 / _DECAY) - 1
_D_MIN, _D_MAX = 1.0, 10.0
_SAME_DAY_PASS_SINC_MIN = 1.0  # FSRS-6: a same-day Hard/Good/Easy never shrinks S
_SECONDS_PER_DAY = 86_400.0
_SECONDS_PER_MINUTE = 60


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


# Channels rating_for accepts: the spec §5 Evidence.channel names, which are
# the params.CHANNELS rows. §13 A1: there is no "idk" channel; an explicit "I
# don't know" is idk=True on the item's channel. PKG-03's Evidence Literal must
# equal this set (its test asserts it).
RATING_CHANNELS = frozenset(CHANNELS)
STRONG_GOOD_CHANNELS = frozenset({"free_response", "teachback_llm", "mc_reasoned"})


# --- curves -----------------------------------------------------------------


def _check_days(days: float) -> None:
    # `not days >= 0` also rejects NaN; +inf is allowed (R → 0, the limit).
    if not days >= 0:
        raise ValueError(f"days must be >= 0, got {days}")


def _check_stability(stability: float) -> None:
    if not (math.isfinite(stability) and stability > 0):
        raise ValueError(f"stability must be finite and > 0, got {stability}")


def retrievability(days: float, stability: float) -> float:
    """R(t, S) = (1 + factor·t/S)^(−w20). R(0, S) = 1; R(S, S) = 0.9."""
    _check_days(days)
    _check_stability(stability)
    return (1 + FACTOR * days / stability) ** (-_DECAY)


def interval(retention: float, stability: float) -> float:
    """I(r, S) = (S/factor)·(r^(−1/w20) − 1): days until R falls to ``retention``."""
    if not 0 < retention <= 1:
        raise ValueError(f"retention must be in (0, 1], got {retention}")
    _check_stability(stability)
    return (stability / FACTOR) * (retention ** (-1 / _DECAY) - 1)


def _check_count(name: str, value: Any) -> int:
    """``value`` as an int >= 0; NaN, ±inf, 2.5, "3" and None raise ValueError."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be an integer >= 0, got {value!r}") from None
    if n != value or n < 0:
        raise ValueError(f"{name} must be an integer >= 0, got {value!r}")
    return n


def retention_target(n_scheduled: int, exam_within_days: int | None = None) -> float:
    """Desired retention: exam window wins, then large set, else default (spec §3.2).

    Both arguments are whole counts >= 0 (``exam_within_days`` is
    ``exam_proximity.days_until_next_exam``: 0 = today, None = no exam).
    """
    n_scheduled = _check_count("n_scheduled", n_scheduled)
    if exam_within_days is not None:
        exam_within_days = _check_count("exam_within_days", exam_within_days)
        if exam_within_days <= FSRS_EXAM_WINDOW_DAYS:
            return FSRS_RETENTION_EXAM
    if n_scheduled > FSRS_LARGE_SET_CONCEPTS:
        return FSRS_RETENTION_LARGE_SET
    return FSRS_RETENTION_DEFAULT


# --- state transition -------------------------------------------------------


def _clamp_d(d: float) -> float:
    return min(_D_MAX, max(_D_MIN, d))


def _check_rating(rating: int) -> int:
    try:
        g = int(rating)
    except (TypeError, ValueError):
        raise ValueError(f"rating must be 1..4, got {rating!r}") from None
    if g != rating or g not in (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY):
        raise ValueError(f"rating must be 1..4, got {rating!r}")
    return g


def _check_difficulty(d: float) -> None:
    # `not a <= d <= b` also rejects NaN.
    if not _D_MIN <= d <= _D_MAX:
        raise ValueError(f"difficulty must be in [{_D_MIN}, {_D_MAX}], got {d}")


def initial_stability(rating: int) -> float:
    """S0(G) = w[G−1]."""
    return W[_check_rating(rating) - 1]


def _raw_initial_difficulty(g: int) -> float:
    """w4 − e^(w5·(G−1)) + 1, unclamped (D0(4) = −4.7716)."""
    return W[4] - math.exp(W[5] * (g - 1)) + 1


def initial_difficulty(rating: int) -> float:
    """D0(G) = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)."""
    return _clamp_d(_raw_initial_difficulty(_check_rating(rating)))


# FSRS-6 mean-reversion target: the UNCLAMPED D0(4) (py-fsrs 6.3.2
# ``_next_difficulty`` uses clamp=False). Spec §3.2 writes D0(4), whose clamp
# makes it 1.0; the ≈0.006-per-update drift is not the model FSRS_W was
# fitted under. HANDOFF-02 Deviations.
_D_REVERSION_TARGET = _raw_initial_difficulty(Rating.EASY)


def _next_difficulty(d: float, g: int) -> float:
    """ΔD = −w6·(G−3); D' = D + ΔD·(10−D)/9; D'' = clamp(w7·D0raw(4) + (1−w7)·D', 1, 10)."""
    delta = -W[6] * (g - Rating.GOOD)
    d_prime = d + delta * (_D_MAX - d) / (_D_MAX - _D_MIN)
    d_pp = W[7] * _D_REVERSION_TARGET + (1 - W[7]) * d_prime
    return _clamp_d(d_pp)


def _stability_recall(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == Rating.HARD else 1.0
    easy = W[16] if g == Rating.EASY else 1.0
    growth = (
        math.exp(W[8])
        * (_D_MAX + 1 - d)
        * s ** (-W[9])
        * (math.exp(W[10] * (1 - r)) - 1)
        * hard
        * easy
    )
    return s * (growth + 1)


def _stability_lapse(d: float, s: float, r: float) -> float:
    """min(w11·D^(−w12)·((S+1)^w13 − 1)·e^(w14·(1−R)), S / e^(w17·w18)).

    The cap is FSRS-6's (py-fsrs 6.3.2 ``_next_forget_stability``); spec
    §3.2's transcription omits it, and without it an Again at low D, tiny S
    and a long gap raised S. HANDOFF-02 Deviations.
    """
    long_term = W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
    return min(long_term, s / math.exp(W[17] * W[18]))


def _stability_same_day(s: float, g: int) -> float:
    """S·SInc, SInc = e^(w17·(G−3+w18))·S^(−w19), floored at 1 for G ≥ Hard.

    The floor is FSRS-6's (py-fsrs 6.3.2 ``_short_term_stability``, same
    weights); spec §3.2's transcription omits it, and without it a correct
    same-day answer lowers S for any S above ~2.1 days (Good) or at every
    realistic S (Hard). HANDOFF-02 Deviations.
    """
    sinc = math.exp(W[17] * (g - Rating.GOOD + W[18])) * s ** (-W[19])
    if g >= Rating.HARD:
        sinc = max(sinc, _SAME_DAY_PASS_SINC_MIN)
    return s * sinc


def next_state(
    d: float | None,
    s: float | None,
    rating: int,
    days_since: float,
    *,
    same_day: bool = False,
    mc_unassisted: bool = False,
) -> tuple[float, float]:
    """(D', S') after one rating. ``d``/``s`` None → first rating (D0, S0).

    ``same_day`` selects S_same_day; otherwise Again selects S_lapse and
    Hard/Good/Easy select S_recall, all at R = retrievability(days_since, s).
    ``mc_unassisted`` caps S' at S·MC_STABILITY_GAIN_CAP (spec §3.2 rating map).
    Last, S' is floored at FSRS_STABILITY_MIN (FSRS-6, py-fsrs 6.3.2
    ``_clamp_stability``; the spec's transcription omits it, HANDOFF-02
    Deviations). py-fsrs floors inside each stability function and has no MC
    cap; flooring after the cap is identical whenever S >= FSRS_STABILITY_MIN/2
    (the cap only binds above 2·S) and keeps S' >= the floor unconditionally.
    The difficulty update runs for every non-first rating. Nothing is scheduled
    here: the caller turns S' into a due date with ``interval``.
    """
    g = _check_rating(rating)
    if d is None or s is None:
        return initial_difficulty(g), initial_stability(g)
    _check_difficulty(d)
    r = retrievability(days_since, s)  # validates days_since and s
    new_d = _next_difficulty(d, g)
    if same_day:
        new_s = _stability_same_day(s, g)
    elif g == Rating.AGAIN:
        new_s = _stability_lapse(d, s, r)
    else:
        new_s = _stability_recall(d, s, r, g)
    if mc_unassisted:
        new_s = min(new_s, s * MC_STABILITY_GAIN_CAP)
    return new_d, max(new_s, FSRS_STABILITY_MIN)


# --- rating map -------------------------------------------------------------


def _check_rating_inputs(channel: str, max_rung: int) -> int:
    """Shared domain of ``rating_for`` and ``mc_cap_applies``: a known channel
    and a whole rung >= 0. Returns the rung as an int."""
    if not isinstance(channel, str) or channel not in RATING_CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    return _check_count("max_rung", max_rung)


def rating_for(channel: str, correct: bool, max_rung: int, *, idk: bool = False) -> int:
    """Spec §3.2 rating map. Wrong, or ``idk`` (§13 A1), → Again; unassisted
    correct → Good (chat_turn → Hard, §13 A7 †); correct after
    H1..H{RUNG_ASSISTED_MAX} → Hard; correct after a higher rung → Again.
    Never Easy."""
    max_rung = _check_rating_inputs(channel, max_rung)
    if idk or not correct:
        return int(Rating.AGAIN)
    if max_rung == 0:
        if channel in STRONG_GOOD_CHANNELS or channel == "mc":
            return int(Rating.GOOD)
        return int(Rating.HARD)  # chat_turn †
    if max_rung <= RUNG_ASSISTED_MAX:
        return int(Rating.HARD)
    return int(Rating.AGAIN)


def mc_cap_applies(channel: str, correct: bool, max_rung: int, *, idk: bool = False) -> bool:
    """True exactly when the rating came from an unassisted correct ``mc`` check.
    Raises on the inputs ``rating_for`` raises on."""
    max_rung = _check_rating_inputs(channel, max_rung)
    return channel == "mc" and bool(correct) and not idk and max_rung == 0


# --- due ordering + budget --------------------------------------------------


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def item_retrievability(
    item: Mapping[str, Any],
    now: datetime | str,
    *,
    stability_key: str = "fsrs_s",
    last_review_key: str = "fsrs_last_review_at",
) -> float:
    """R now for one row; a row with no FSRS state has R = 1.0 (never reviewed).

    A last review later than ``now`` (clock skew) counts as zero elapsed days.
    """
    s = item.get(stability_key)
    last = item.get(last_review_key)
    if s is None or last is None:
        return 1.0
    elapsed = (_as_datetime(now) - _as_datetime(last)).total_seconds()
    days = max(0.0, elapsed / _SECONDS_PER_DAY)
    return retrievability(days, float(s))


def order_due(
    items: Iterable[Mapping[str, Any]],
    now: datetime | str,
    *,
    stability_key: str = "fsrs_s",
    last_review_key: str = "fsrs_last_review_at",
) -> list:
    """Stable sort by |R − REVIEW_ORDER_THRESHOLD| ascending (DASH threshold).

    Returns a new list; the input is not reordered. Rows with no FSRS state
    (R = 1.0) sort last.
    """
    rows = list(items)
    return sorted(
        rows,
        key=lambda it: abs(
            item_retrievability(
                it, now, stability_key=stability_key, last_review_key=last_review_key
            )
            - REVIEW_ORDER_THRESHOLD
        ),
    )


def budget_items(
    budget_min: float = REVIEW_DAILY_BUDGET_MIN,
    seconds_per: float = REVIEW_SECONDS_PER_CHECK,
) -> int:
    """How many checks fit in ``budget_min`` minutes at ``seconds_per`` each."""
    if not (math.isfinite(seconds_per) and seconds_per > 0):
        raise ValueError(f"seconds_per must be finite and > 0, got {seconds_per}")
    if not math.isfinite(budget_min):
        raise ValueError(f"budget_min must be finite, got {budget_min}")
    if budget_min <= 0:
        return 0
    return int(budget_min * _SECONDS_PER_MINUTE // seconds_per)


def budget_select(
    items: Sequence[Any],
    budget_min: float = REVIEW_DAILY_BUDGET_MIN,
    seconds_per: float = REVIEW_SECONDS_PER_CHECK,
) -> list:
    """First ``budget_items()`` of an already-ordered list; never more."""
    return list(items)[: budget_items(budget_min, seconds_per)]


# --- successive relearning --------------------------------------------------

SR_ACQUISITION = "acquisition"
SR_RELEARN = "relearn"
SR_DONE = "done"
_SR_PHASES = (SR_ACQUISITION, SR_RELEARN, SR_DONE)


@dataclass(frozen=True)
class SuccessiveRelearning:
    """Rawson & Dunlosky protocol: SR_INITIAL_CRITERION correct recalls in the
    acquisition session, then SR_RELEARN_SESSIONS later sessions each to one
    correct recall. Immutable; ``advance`` returns the next state."""

    phase: str = SR_ACQUISITION
    correct_in_acquisition: int = 0
    relearn_sessions_done: int = 0
    credited_session: str | None = None

    def __post_init__(self) -> None:
        if self.phase not in _SR_PHASES:
            raise ValueError(f"phase must be one of {_SR_PHASES}, got {self.phase!r}")
        # Validate, then store the int (a stored 2.0 comes back as 2).
        for name in ("correct_in_acquisition", "relearn_sessions_done"):
            object.__setattr__(self, name, _check_count(name, getattr(self, name)))

    def advance(self, correct: bool, *, session_id: str) -> SuccessiveRelearning:
        if self.phase == SR_DONE:
            return self
        if self.phase == SR_ACQUISITION:
            if not correct:
                return self
            n = self.correct_in_acquisition + 1
            if n >= SR_INITIAL_CRITERION:
                return replace(
                    self,
                    phase=SR_RELEARN,
                    correct_in_acquisition=n,
                    credited_session=session_id,
                )
            return replace(self, correct_in_acquisition=n)
        # relearn: one credit per session, never the session that met the criterion
        if not correct or session_id == self.credited_session:
            return self
        done = self.relearn_sessions_done + 1
        return replace(
            self,
            phase=SR_DONE if done >= SR_RELEARN_SESSIONS else SR_RELEARN,
            relearn_sessions_done=done,
            credited_session=session_id,
        )

    @property
    def complete(self) -> bool:
        return self.phase == SR_DONE

    def as_dict(self) -> dict:
        return {
            "phase": self.phase,
            "correct_in_acquisition": self.correct_in_acquisition,
            "relearn_sessions_done": self.relearn_sessions_done,
            "credited_session": self.credited_session,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SuccessiveRelearning:
        """Inverse of ``as_dict``; None or {} is a fresh state. A stored state
        with an unknown phase or a counter that is not a whole number >= 0
        raises ValueError. Values pass through uncoerced: ``__post_init__``
        validates them (``int()`` here would truncate 2.7 and parse "2")."""
        if not data:
            return cls()
        return cls(
            phase=data.get("phase", SR_ACQUISITION),
            correct_in_acquisition=data.get("correct_in_acquisition", 0),
            relearn_sessions_done=data.get("relearn_sessions_done", 0),
            credited_session=data.get("credited_session"),
        )
