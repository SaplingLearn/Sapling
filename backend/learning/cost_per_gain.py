"""What the learning loop cost, against what it measurably taught (spec §13 A137).

Joins the loop's model spend (`llm_usage` rows of the loop's tasks, check-item
drafting included) to the A112 learning-gain pairs, overall and per course:

  • $ per active student-month, against §3.5's target (≈ $0.36 per
    student-month, which prices the routed TUTOR plan only; the tutor's own
    share is reported beside the whole);
  • $ per session (the cost of the rows that carry a session id);
  • $ per matched pre/post pair and $ per gain point, per post-test window.

Every figure carries its n, and every rate is None when its n is 0 — never a
zero that reads as a result. A gain point is one pair's (post − pre): a concept
answered right at the post-test that was answered wrong at the pretest is +1,
the reverse −1, so a window's gain points are improved − worse. $ per gain point
is None when they are not positive: there is no cost per gain without a gain.
$ per pair and per gain point carry a student-cluster bootstrap interval (each
student's cost and pairs resampled together, as the learning-gain report
resamples a student's pairs; the cost of rows with no student — background
drafting — is added to every resample), with the learning-gain report's level,
resample count and seed. Below two students there is no interval. A resample
with no pair, or no positive gain, has no finite ratio: an upper bound that
lands there is None (unbounded), never a number.

Read it over ranges much longer than the windows. The cost is what the range
spent; its post-tests measure sessions 7 to 28 days and more before, so a short
range divides one period's spend by another period's learning.

A row is attributed to a course by its own `course_id` (A137: the drafting,
grading and decision run sites record it), else by its session's course; a row
with neither is counted in `unattributed` and in the overall block only. A row
with no `cost_usd` (an unpriced model) adds no dollars and is counted in
`unpriced_rows`. The pairs follow learning/learning_gain.py exactly: an
unassisted post-test outcome with a pretest, and nothing graded against an item
staff retired (A123's one void rule). Pure: stdlib and learning.*; a report that
never gates and never writes.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from learning.evidence_void import pose_is_void
from learning.learning_gain import posttest_outcome
from learning.params import (
    LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    LEARNING_GAIN_BOOTSTRAP_SEED,
    LEARNING_GAIN_CI_LEVEL,
    LOOP_COST_TARGET_USD_PER_STUDENT_MONTH,
    POSTTEST_WINDOWS_DAYS,
)

#: The loop's three tutor tiers: what §3.5's per-student-month target prices.
TUTOR_TASKS = ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep")
#: Check-item drafting and the checks every drafted item passes (A119, A124):
#: course assets, not one student's spend.
DRAFTING_TASKS = ("check_items", "check_items_verify", "check_items_solve")
#: Every llm_usage task the loop bills: its evidence slots (agents/_providers.py
#: EVIDENCE_SLOTS) and the Jev rows of its typed decisions (A98: a shadow, and a
#: billed served attempt that fell back).
LOOP_TASKS = (
    *TUTOR_TASKS,
    *DRAFTING_TASKS,
    "grader",
    "grader_second",
    "learning_decision",
    "decision_shadow",
    "decision_jev_extra",
    "session_close",
)
#: An average calendar month, for "per active student-month" over any range.
DAYS_PER_MONTH = 365.25 / 12


def _cost(row: Mapping[str, Any]) -> float | None:
    """The row's dollars; None when the model was not priced (or unreadable)."""
    value = row.get("cost_usd")
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def course_of(row: Mapping[str, Any], session_courses: Mapping[str, str]) -> str | None:
    """The course a usage row belongs to: its own course_id, else its session's."""
    return _text(row.get("course_id")) or _text(session_courses.get(row.get("session_id") or ""))


def pairs_of(
    poses: Iterable[Mapping[str, Any]],
    pretests: Mapping[str, bool],
    *,
    retired: Collection[tuple[str, str]] = frozenset(),
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
) -> list[dict]:
    """The matched pre/post pairs, as learning_gain.learning_gain counts them:
    {user_id, course_id, window_days, pre, post} per answered pose with an
    unassisted outcome, a bool pretest, a window in `windows`, and no retired
    item."""
    out = []
    for pose in poses:
        window = pose.get("window_days")
        if isinstance(window, bool) or window not in windows:
            continue
        post = posttest_outcome(pose)
        if post is None or pose_is_void(pose, retired):
            continue
        pre = pretests.get(pose.get("anchor_event_id"))
        if not isinstance(pre, bool):
            continue
        out.append(
            {
                "user_id": pose.get("user_id"),
                "course_id": _text(pose.get("course_id")),
                "window_days": window,
                "pre": pre,
                "post": post,
            }
        )
    return out


def _quantile(ordered: Sequence[float], q: float) -> float:
    """The q-quantile of sorted values, linear between order statistics (an
    infinite neighbour makes it infinite)."""
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    if math.isinf(ordered[lo]) or math.isinf(ordered[hi]):
        return math.inf
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _bound(value: float) -> float | None:
    return None if math.isinf(value) else value


def ratio_ci(
    clusters: Mapping[str, tuple[float, int, int]],
    fixed_cost: float,
    *,
    resamples: int,
    seed: str,
    level: float,
) -> tuple[list[float | None] | None, list[float | None] | None]:
    """Student-cluster bootstrap intervals of (Σ cost + fixed) / Σ pairs and of
    (Σ cost + fixed) / Σ gain points. `clusters`: student → (their cost, their
    pairs, their gain points). Students are ordered by id first, so the input
    order never matters; deterministic per `seed`. A resample with no pair (or
    no positive gain) has an infinite ratio; a bound that lands on it is None.
    Fewer than two students → (None, None)."""
    rows = [clusters[s] for s in sorted(clusters)]
    k = len(rows)
    if k < 2 or resamples < 1:
        return None, None
    rng = random.Random(seed)
    per_pair, per_gain = [], []
    for _ in range(resamples):
        cost, pairs, gain = fixed_cost, 0, 0
        for c_cost, c_pairs, c_gain in rng.choices(rows, k=k):
            cost += c_cost
            pairs += c_pairs
            gain += c_gain
        per_pair.append(cost / pairs if pairs > 0 else math.inf)
        per_gain.append(cost / gain if gain > 0 else math.inf)
    alpha = (1.0 - level) / 2.0
    per_pair.sort()
    per_gain.sort()

    def interval(values: list[float]) -> list[float | None]:
        return [_bound(_quantile(values, alpha)), _bound(_quantile(values, 1.0 - alpha))]

    return interval(per_pair), interval(per_gain)


def _block(
    course_id: str | None,
    usage: list[Mapping[str, Any]],
    pairs: list[dict],
    *,
    range_days: float | None,
    windows: Sequence[int],
    resamples: int,
    seed: str,
    level: float,
) -> dict:
    cost = tutor = drafting = session_cost = fixed = 0.0
    unpriced = 0
    students: dict[str, float] = defaultdict(float)
    sessions: set[str] = set()
    for row in usage:
        usd = _cost(row)
        if usd is None:
            unpriced += 1
            usd = 0.0
        cost += usd
        task = row.get("task")
        if task in TUTOR_TASKS:
            tutor += usd
        elif task in DRAFTING_TASKS:
            drafting += usd
        session = _text(row.get("session_id"))
        if session is not None:
            sessions.add(session)
            session_cost += usd
        user = _text(row.get("user_id"))
        if user is None:
            fixed += usd
        else:
            students[user] += usd
    active = len(students)
    months = range_days / DAYS_PER_MONTH if range_days and range_days > 0 else None
    per_student_month = cost / active / months if active and months else None
    tutor_per_student_month = tutor / active / months if active and months else None
    target = LOOP_COST_TARGET_USD_PER_STUDENT_MONTH
    window_blocks = []
    for w in windows:
        mine = [p for p in pairs if p["window_days"] == w]
        n = len(mine)
        gain = sum(int(p["post"]) - int(p["pre"]) for p in mine)
        clusters: dict[str, list] = {s: [usd, 0, 0] for s, usd in students.items()}
        for p in mine:
            row = clusters.setdefault(str(p["user_id"]), [0.0, 0, 0])
            row[1] += 1
            row[2] += int(p["post"]) - int(p["pre"])
        pair_ci, gain_ci = ratio_ci(
            {s: tuple(v) for s, v in clusters.items()},
            fixed,
            resamples=resamples,
            seed=f"{seed}:cost:{course_id or 'all'}:{w}",
            level=level,
        )
        window_blocks.append(
            {
                "window_days": w,
                "pairs": n,
                "students": len({str(p["user_id"]) for p in mine}),
                "gain_points": gain,
                "per_pair": cost / n if n else None,
                "per_pair_ci": pair_ci if n else None,
                "per_gain_point": cost / gain if gain > 0 else None,
                "per_gain_point_ci": gain_ci if gain > 0 else None,
            }
        )
    return {
        "course_id": course_id,
        "cost_usd": cost,
        "tutor_usd": tutor,
        "drafting_usd": drafting,
        "rows": len(usage),
        "unpriced_rows": unpriced,
        "active_students": active,
        "per_active_student_month": per_student_month,
        "tutor_per_active_student_month": tutor_per_student_month,
        "target_ratio": per_student_month / target if per_student_month is not None and target else None,
        "sessions": len(sessions),
        "per_session": session_cost / len(sessions) if sessions else None,
        "windows": window_blocks,
    }


def cost_per_gain(
    usage: Iterable[Mapping[str, Any]],
    session_courses: Mapping[str, str],
    poses: Iterable[Mapping[str, Any]],
    pretests: Mapping[str, bool],
    *,
    range_days: float | None,
    retired: Collection[tuple[str, str]] = frozenset(),
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    resamples: int = LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    seed: str = LEARNING_GAIN_BOOTSTRAP_SEED,
    level: float = LEARNING_GAIN_CI_LEVEL,
) -> dict:
    """`usage`: the range's llm_usage rows (task, cost_usd, user_id, session_id,
    course_id when recorded); rows of a task outside LOOP_TASKS are ignored.
    `session_courses`: session id → course id for rows that carry no course.
    `poses` / `pretests` / `retired`: the learning-gain report's inputs (the
    post-tests answered in the range). `range_days`: the range's length, for
    the per-student-month rate (None or ≤ 0 → no rate). Returns the overall
    block, one block per course that spent or measured anything (by course
    id), and the unattributed spend."""
    loop = [row for row in usage if row.get("task") in LOOP_TASKS]
    pairs = pairs_of(poses, pretests, retired=retired, windows=windows)
    by_course: dict[str, list] = defaultdict(list)
    unattributed = []
    for row in loop:
        course = course_of(row, session_courses)
        (by_course[course] if course is not None else unattributed).append(row)
    pair_courses = {p["course_id"] for p in pairs if p["course_id"] is not None}
    kwargs = {
        "range_days": range_days,
        "windows": windows,
        "resamples": resamples,
        "seed": seed,
        "level": level,
    }
    return {
        "target_usd_per_student_month": LOOP_COST_TARGET_USD_PER_STUDENT_MONTH,
        "range_days": range_days,
        "ci": {
            "method": "student_cluster_bootstrap_percentile",
            "level": level,
            "resamples": resamples,
            "seed": seed,
        },
        "overall": _block(None, loop, pairs, **kwargs),
        "courses": [
            _block(
                course,
                by_course.get(course, []),
                [p for p in pairs if p["course_id"] == course],
                **kwargs,
            )
            for course in sorted(set(by_course) | pair_courses)
        ],
        "unattributed": {
            "cost_usd": sum(_cost(row) or 0.0 for row in unattributed),
            "rows": len(unattributed),
        },
    }
