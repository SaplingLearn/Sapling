"""Pre/post learning gain at the fixed post-test windows (spec §13 A112;
docs/research/learning-loop/2026-11-07-direction-audit.md rec. 2 "add a pretest
form", and the 2026-10-18 foundation audit: "do not use rising p_known as the
primary learning outcome"). Pure: stdlib, learning.params and learning.probe.

A PAIR is one (student, concept) in one post-test window that has BOTH

  • a pretest — the concept's FIRST graded evidence (the post-test anchor,
    A112) when that evidence is a PROBE grade with an independent planning
    observation (no help, a fresh item, no re-check, no synthetic idk) bound to
    its journal row — `probe.is_probe_row`, the rule the session close (A117)
    counts check-in answers by, plus the independence. Planning provenance
    alone cannot say "probe": the loop's in-session checks are tagged too, so
    the caller passes the question hashes of the row's session's probe history
    (`probe.probe_history_hashes` of `sessions.loop_state.probe.history`).
    A concept graded first by anything else (a check after teaching, review, a
    quiz) has no pretest: it was exposed before it was diagnosed; and
  • an unassisted post-test outcome in that window — the pose was answered and
    graded at rung 0 (no help, nothing revealed, no evidence since the pose:
    A88/A89/A93). A no-credit or assisted grade is not a delayed unaided outcome.

Per window: n pairs, the pre and post correct rates, the paired difference (the
mean of post − pre over the pairs, in [−1, 1]) and the improved / same / worse
counts — and the same over the "delayed" stratum, the pairs whose concept had
no evidence for at least POSTTEST_DELAYED_MIN_DAYS before the pose (practice
no longer postpones a window, so a pose may follow recent practice).

An outcome graded against an item STAFF retired is void evidence (spec §13
A123, the one rule learning/evidence_void.py states for every evidence read:
the item was retired as broken, so no outcome on it measures the student) — so
it is left out of its window (its post-tests, its pairs and the delayed
stratum) and counted in the window's `excluded_retired`, which keeps the drop
visible; the caller applies the same rule to the pretest anchors. The caller
passes the retired course items as (course_id, question_hash) keys read from
that structured record (`check_item_reviews`, status 'retired' — since A123
only staff set it; students' reports only quarantine an item). An item row
merely gone is no retire — A23's consent withdrawal deletes items too, and
those outcomes stand — and neither is a quarantine, a report or an approval.

Only observed outcomes are read — never p_known or any other belief. Every rate
is None when n = 0, never a zero that reads as a result. A report: it never
gates and never writes.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from learning.evidence_void import pose_is_void
from learning.params import POSTTEST_DELAYED_MIN_DAYS, POSTTEST_WINDOWS_DAYS
from learning.probe import is_probe_row


def pretest_outcome(row: Mapping[str, Any] | None, probe_hashes: Collection[str]) -> bool | None:
    """The concept's pretest from its anchor row (its first evidence row): the
    observed outcome when the row is a probe grade — `probe.is_probe_row`, the
    one rule the session close counts check-in answers by (A117): a session's
    row, its question in `probe_hashes` (that session's probe history), its
    planning_observation bound to it — whose observation is, on top of that,
    independent; else None (no usable pretest: a check, review, quiz or
    post-test row, a helped or seen probe item, a legacy row without
    provenance — unknown, never inferred)."""
    if not is_probe_row(row, probe_hashes):
        return None
    if row["planning_observation"].get("independent") is not True:
        return None
    correct = row.get("correct")
    return correct if isinstance(correct, bool) else None


def posttest_outcome(pose: Mapping[str, Any]) -> bool | None:
    """An answered pose's unassisted outcome: its recorded `correct` when it was
    graded at rung 0, else None (unanswered, a legacy pose with no recorded
    outcome, or a grade that carried help or no credit)."""
    correct, rung = pose.get("correct"), pose.get("max_rung")
    if not pose.get("answered_at") or not isinstance(correct, bool):
        return None
    if isinstance(rung, bool) or not isinstance(rung, int) or rung != 0:
        return None
    return correct


def summarize(pairs: Iterable[tuple[bool, bool]]) -> dict:
    """(pretest, post-test) pairs → n, both correct rates, the paired difference
    and the transition counts. Rates are None when n = 0."""
    pairs = list(pairs)
    n = len(pairs)
    pre = sum(1 for p, _ in pairs if p)
    post = sum(1 for _, q in pairs if q)
    improved = sum(1 for p, q in pairs if q and not p)
    worse = sum(1 for p, q in pairs if p and not q)
    return {
        "n": n,
        "pre_correct_rate": pre / n if n else None,
        "post_correct_rate": post / n if n else None,
        "paired_difference": (post - pre) / n if n else None,
        "improved": improved,
        "same": n - improved - worse,
        "worse": worse,
    }


def pose_item(pose: Mapping[str, Any]) -> tuple[str, str] | None:
    """The course item a pose asked: (course_id, question_hash) — the key A113's
    review records a retire under. None when either is missing."""
    course, question_hash = pose.get("course_id"), pose.get("question_hash")
    if isinstance(course, str) and course and isinstance(question_hash, str) and question_hash:
        return course, question_hash
    return None


def _delayed(days: Any, min_days: float) -> bool:
    """At least `min_days` since the concept's last evidence; an unknown delay
    (a pose from before A112) is never counted as delayed."""
    return isinstance(days, (int, float)) and not isinstance(days, bool) and days >= min_days


def learning_gain(
    poses: Iterable[Mapping[str, Any]],
    pretests: Mapping[str, bool],
    *,
    retired: Collection[tuple[str, str]] = frozenset(),
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    delayed_min_days: int = POSTTEST_DELAYED_MIN_DAYS,
) -> dict:
    """`poses`: answered posttest_poses rows (window_days, correct, max_rung,
    anchor_event_id, days_since_evidence, answered_at, course_id,
    question_hash); `pretests`: anchor event id → the concept's pretest outcome
    (pretest_outcome over the caller's reads); `retired`: the (course_id,
    question_hash) items A113's review path retired. One block per window in
    `windows` order — a window with no outcome is still reported, with None
    rates; `posttests` counts its unassisted outcomes, paired or not, and
    `excluded_retired` the unassisted outcomes left out because their item is
    in `retired`. A pose of a window outside `windows` is ignored."""
    buckets = {
        w: {"posttests": 0, "excluded_retired": 0, "pairs": [], "delayed": []} for w in windows
    }
    for pose in poses:
        window = pose.get("window_days")
        if isinstance(window, bool) or window not in buckets:
            continue
        post = posttest_outcome(pose)
        if post is None:
            continue
        bucket = buckets[window]
        if pose_is_void(pose, retired):  # retired as broken: void evidence (A113, A123)
            bucket["excluded_retired"] += 1
            continue
        bucket["posttests"] += 1
        pre = pretests.get(pose.get("anchor_event_id"))
        if not isinstance(pre, bool):
            continue
        bucket["pairs"].append((pre, post))
        if _delayed(pose.get("days_since_evidence"), delayed_min_days):
            bucket["delayed"].append((pre, post))
    return {
        "delayed_min_days": delayed_min_days,
        "windows": [
            {
                "window_days": w,
                "posttests": b["posttests"],
                "excluded_retired": b["excluded_retired"],
                **summarize(b["pairs"]),
                "delayed": summarize(b["delayed"]),
            }
            for w, b in buckets.items()
        ],
    }
