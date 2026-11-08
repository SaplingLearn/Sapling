"""Pre/post learning gain at the fixed post-test windows (spec §13 A112;
docs/research/learning-loop/2026-11-07-direction-audit.md rec. 2 "add a pretest
form", and the 2026-10-18 foundation audit: "do not use rising p_known as the
primary learning outcome"), with what a learning claim needs around it (A126):
the windows' close, the measurement funnel, uncertainty and the delay actually
observed. Pure: stdlib, learning.params and learning.probe.

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
no longer postpones a window, so a pose may follow recent practice), and over
the "visibility-loss" stratum (A126), the pairs whose answer page was hidden
at least once while the item was on screen. Nothing is excluded for it: the
stratum is reported beside the whole, and outcomes with no visibility record
(an older client, a pre-A126 row) are counted in `visibility_unreported`.

Uncertainty (A126): per window, a student-cluster bootstrap percentile interval
(LEARNING_GAIN_CI_LEVEL) for the post-test correct rate and for the paired
difference — a student's pairs are resampled together, since one student's
concepts are not independent observations — with
LEARNING_GAIN_BOOTSTRAP_RESAMPLES resamples from a seed fixed by
LEARNING_GAIN_BOOTSTRAP_SEED and the window, so the same rows always give the
same interval. Fewer than two students → no interval (a single cluster has no
between-student spread to resample). Delay bins pool every window's pairs by
the days from the anchor to the answer (POSTTEST_DELAY_BIN_EDGES_DAYS) — the
delay the outcome actually had, not its window's label.

An outcome graded against an item STAFF retired is void evidence (spec §13
A123, the one rule learning/evidence_void.py states for every evidence read:
the item was retired as broken, so no outcome on it measures the student) — so
it is left out of its window (its post-tests, its pairs and every
stratum) and counted in the window's `excluded_retired`, which keeps the drop
visible; the caller applies the same rule to the pretest anchors. The caller
passes the retired course items as (course_id, question_hash) keys read from
that structured record (`check_item_reviews`, status 'retired' — since A123
only staff set it; students' reports only quarantine an item). An item row
merely gone is no retire — A23's consent withdrawal deletes items too, and
those outcomes stand — and neither is a quarantine, a report or an approval.

The FUNNEL (A126) counts what happened to every window that came due: due
(the window opened), opened (a pose was created), answered, expired (a pose
left unanswered past its TTL), open (a pose still answerable), skipped (no
fresh item could be posed — recorded with its reason when it happened) and
not opened (the student never came while it was open), plus `still_open`, the
due windows not yet answered whose window has not closed (their state can
still change). Missing outcomes are reported, never imputed.

Only observed outcomes are read — never p_known or any other belief. Every rate
is None when n = 0, never a zero that reads as a result. A report: it never
gates and never writes.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from learning.evidence_void import pose_is_void
from learning.params import (
    LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    LEARNING_GAIN_BOOTSTRAP_SEED,
    LEARNING_GAIN_CI_LEVEL,
    POSTTEST_DELAY_BIN_EDGES_DAYS,
    POSTTEST_DELAYED_MIN_DAYS,
    POSTTEST_HIDDEN_COUNT_MAX,
    POSTTEST_LAST_WINDOW_CLOSE_DAYS,
    POSTTEST_POSE_TTL_HOURS,
    POSTTEST_SKIP_REASONS,
    POSTTEST_WINDOWS_DAYS,
)
from learning.probe import is_probe_row

_ONE_DAY = timedelta(days=1)


# ── the windows (A112; the last one's close, A126) ───────────────────────────


def window_bounds(
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    close_days: int = POSTTEST_LAST_WINDOW_CLOSE_DAYS,
) -> tuple[tuple[int, int, int], ...]:
    """(window, opens, closes) in days after the anchor, per window: a window
    runs until the next one opens, and the last closes `close_days` after the
    anchor (A126) — never "stays open"."""
    windows = list(windows)
    return tuple(
        (w, w, windows[i + 1] if i + 1 < len(windows) else close_days)
        for i, w in enumerate(windows)
    )


def window_at(
    anchor: datetime,
    now: datetime,
    *,
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    close_days: int = POSTTEST_LAST_WINDOW_CLOSE_DAYS,
) -> int | None:
    """The window `now` falls in, counted from the concept's anchor (its FIRST
    graded evidence: practice cannot move it, A112): w when anchor + opens ≤ now
    < anchor + closes. None before the first window opens and once the last has
    closed (A126)."""
    for window, opens, closes in window_bounds(windows, close_days):
        if anchor + timedelta(days=opens) <= now < anchor + timedelta(days=closes):
            return window
    return None


# ── one pair ─────────────────────────────────────────────────────────────────


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


def _ts(raw: Any) -> datetime | None:
    """A stored timestamp (datetime or ISO text) as an aware UTC datetime; None
    when absent or unreadable — unknown, never guessed."""
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


# ── what the pose row records about the answer (A126) ────────────────────────


def _number(value: Any) -> float | None:
    """A finite real number, else None (a bool, a string, NaN or ±inf is not one)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def clamp_visibility(
    hidden_count: Any, hidden_s: Any, open_s: float | None
) -> tuple[int | None, float | None]:
    """The page-hidden telemetry a retention answer carries, as the pose row
    records it. UNTRUSTED client input — clamped, never rejected, never read by
    grading: a count of hidden periods in [0, POSTTEST_HIDDEN_COUNT_MAX] and
    hidden seconds in [0, open_s] (the item cannot have been hidden for longer
    than it was on screen, by the server's own clock; no bound when `open_s` is
    unknown). Neither value usable → (None, None): not reported. One usable →
    the other 0. Hidden seconds with no hidden period counted → one period."""
    count, seconds = _number(hidden_count), _number(hidden_s)
    if count is None and seconds is None:
        return None, None
    count = min(POSTTEST_HIDDEN_COUNT_MAX, max(0, round(count or 0.0)))
    seconds = max(0.0, seconds or 0.0)
    bound = _number(open_s)
    if bound is not None:
        seconds = min(seconds, max(0.0, bound))
    if seconds > 0 and count == 0:
        count = 1
    return int(count), seconds


def answer_latency_s(served_at: Any, answered_at: Any) -> float | None:
    """Seconds from the item's first display (`served_at`, stamped by the
    server when the client shows it) to the answer; None when either time is
    unknown — never the pose's opening time standing in for the display."""
    served, answered = _ts(served_at), _ts(answered_at)
    if served is None or answered is None:
        return None
    return max(0.0, (answered - served).total_seconds())


def _visibility_lost(pose: Mapping[str, Any]) -> bool | None:
    """True: the page was hidden at least once while the item was on screen;
    False: reported and never hidden; None: no visibility record."""
    count, seconds = _number(pose.get("hidden_count")), _number(pose.get("hidden_s"))
    if count is None and seconds is None:
        return None
    return (count or 0) > 0 or (seconds or 0) > 0


# ── uncertainty: a student-cluster bootstrap (A126) ──────────────────────────


def _quantile(ordered: Sequence[float], q: float) -> float:
    """The q-quantile of sorted values, linear between order statistics."""
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def bootstrap_ci(
    triples: Iterable[tuple[Any, bool, bool]],
    *,
    resamples: int = LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    seed: str = LEARNING_GAIN_BOOTSTRAP_SEED,
    level: float = LEARNING_GAIN_CI_LEVEL,
) -> dict:
    """(student, pretest, post-test) triples → the number of students and the
    percentile interval at `level` of the post-test correct rate and of the
    paired difference, each over `resamples` student-cluster resamples: draw
    as many students as there are, with replacement, and pool every pair of
    each drawn student. Deterministic per `seed`; the students are ordered by
    their id first, so the input order never matters. Fewer than two students
    → None intervals."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # n, pre, post
    for student, pre, post in triples:
        row = totals[str(student)]
        row[0] += 1
        row[1] += int(bool(pre))
        row[2] += int(bool(post))
    clusters = [tuple(totals[s]) for s in sorted(totals)]
    k = len(clusters)
    if k < 2 or resamples < 1:
        return {"students": k, "post_correct_ci": None, "paired_difference_ci": None}
    rng = random.Random(seed)
    post_rates, differences = [], []
    for _ in range(resamples):
        n = pre = post = 0
        for c_n, c_pre, c_post in rng.choices(clusters, k=k):
            n += c_n
            pre += c_pre
            post += c_post
        post_rates.append(post / n)
        differences.append((post - pre) / n)
    alpha = (1.0 - level) / 2.0
    post_rates.sort()
    differences.sort()
    return {
        "students": k,
        "post_correct_ci": [_quantile(post_rates, alpha), _quantile(post_rates, 1.0 - alpha)],
        "paired_difference_ci": [_quantile(differences, alpha), _quantile(differences, 1.0 - alpha)],
    }


# ── the actual delay (A126) ───────────────────────────────────────────────────


def delay_days(pose: Mapping[str, Any]) -> float | None:
    """Days from the concept's anchor to the answer; None when either is unknown
    (a pose from before A112 has no anchor_at)."""
    anchor, answered = _ts(pose.get("anchor_at")), _ts(pose.get("answered_at"))
    if anchor is None or answered is None:
        return None
    return (answered - anchor) / _ONE_DAY


def _delay_bin(days: float, edges: Sequence[int]) -> int | None:
    """The bin index of `days` (bin i is [edges[i], edges[i+1]), the last one
    open-ended); None below the first edge."""
    found = None
    for i, edge in enumerate(edges):
        if days >= edge:
            found = i
    return found


# ── the report ───────────────────────────────────────────────────────────────


def learning_gain(
    poses: Iterable[Mapping[str, Any]],
    pretests: Mapping[str, bool],
    *,
    retired: Collection[tuple[str, str]] = frozenset(),
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    delayed_min_days: int = POSTTEST_DELAYED_MIN_DAYS,
    delay_edges: Sequence[int] = POSTTEST_DELAY_BIN_EDGES_DAYS,
    resamples: int = LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    seed: str = LEARNING_GAIN_BOOTSTRAP_SEED,
    level: float = LEARNING_GAIN_CI_LEVEL,
) -> dict:
    """`poses`: answered posttest_poses rows (user_id, window_days, correct,
    max_rung, anchor_event_id, anchor_at, days_since_evidence, answered_at,
    course_id, question_hash, hidden_count, hidden_s); `pretests`: anchor event
    id → the concept's pretest outcome (pretest_outcome over the caller's
    reads); `retired`: the (course_id, question_hash) items A113's review path
    retired. One block per window in `windows` order — a window with no outcome
    is still reported, with None rates; `posttests` counts its unassisted
    outcomes, paired or not, and `excluded_retired` the unassisted outcomes left
    out because their item is in `retired`. A pose of a window outside
    `windows` is ignored. `delay_bins` pools every window by the actual delay;
    `delay_unknown` counts the outcomes with no anchor time and
    `delay_out_of_range` those answered before the first edge."""
    buckets = {
        w: {
            "posttests": 0,
            "excluded_retired": 0,
            "pairs": [],
            "triples": [],
            "delayed": [],
            "visibility_loss": [],
            "visibility_unreported": 0,
        }
        for w in windows
    }
    bins: list[dict] = [{"posttests": 0, "pairs": []} for _ in delay_edges]
    delay_unknown = delay_out_of_range = 0
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
        lost = _visibility_lost(pose)
        if lost is None:
            bucket["visibility_unreported"] += 1
        days = delay_days(pose)
        index = _delay_bin(days, delay_edges) if days is not None else None
        if days is None:
            delay_unknown += 1
        elif index is None:
            delay_out_of_range += 1
        else:
            bins[index]["posttests"] += 1
        pre = pretests.get(pose.get("anchor_event_id"))
        if not isinstance(pre, bool):
            continue
        bucket["pairs"].append((pre, post))
        bucket["triples"].append((pose.get("user_id"), pre, post))
        if _delayed(pose.get("days_since_evidence"), delayed_min_days):
            bucket["delayed"].append((pre, post))
        if lost:
            bucket["visibility_loss"].append((pre, post))
        if index is not None:
            bins[index]["pairs"].append((pre, post))
    return {
        "delayed_min_days": delayed_min_days,
        "ci": {
            "method": "student_cluster_bootstrap_percentile",
            "level": level,
            "resamples": resamples,
            "seed": seed,
        },
        "windows": [
            {
                "window_days": w,
                "posttests": b["posttests"],
                "excluded_retired": b["excluded_retired"],
                **summarize(b["pairs"]),
                **bootstrap_ci(b["triples"], resamples=resamples, seed=f"{seed}:{w}", level=level),
                "delayed": summarize(b["delayed"]),
                "visibility_loss": summarize(b["visibility_loss"]),
                "visibility_unreported": b["visibility_unreported"],
            }
            for w, b in buckets.items()
        ],
        "delay_bins": [
            {
                "lo_days": lo,
                "hi_days": delay_edges[i + 1] if i + 1 < len(delay_edges) else None,
                "posttests": bins[i]["posttests"],
                **summarize(bins[i]["pairs"]),
            }
            for i, lo in enumerate(delay_edges)
        ],
        "delay_unknown": delay_unknown,
        "delay_out_of_range": delay_out_of_range,
    }


# ── the funnel (A126) ────────────────────────────────────────────────────────


def due_windows(
    anchors: Iterable[Mapping[str, Any]],
    *,
    start: datetime,
    end: datetime,
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
    close_days: int = POSTTEST_LAST_WINDOW_CLOSE_DAYS,
) -> list[dict]:
    """The windows that OPENED in [start, end]: for each concept anchor
    {user_id, node_id, course_id, anchor_at} and each window, a due window
    {user_id, node_id, course_id, window_days, opens_at, closes_at} when anchor
    + opens falls in the range. A window belongs to the range it opened in, so
    adjacent ranges never count one twice. An unreadable anchor is skipped."""
    out = []
    bounds = window_bounds(windows, close_days)
    for row in anchors:
        anchor = _ts(row.get("anchor_at"))
        if anchor is None or not row.get("user_id") or not row.get("node_id"):
            continue
        for window, opens, closes in bounds:
            opens_at = anchor + timedelta(days=opens)
            if start <= opens_at <= end:
                out.append(
                    {
                        "user_id": row["user_id"],
                        "node_id": row["node_id"],
                        "course_id": row.get("course_id"),
                        "window_days": window,
                        "opens_at": opens_at,
                        "closes_at": anchor + timedelta(days=closes),
                    }
                )
    return out


def _empty_funnel(window: int) -> dict:
    return {
        "window_days": window,
        "due": 0,
        "opened": 0,
        "answered": 0,
        "unassisted": 0,
        "expired": 0,
        "open": 0,
        "skipped": 0,
        "skip_reasons": {reason: 0 for reason in POSTTEST_SKIP_REASONS},
        "not_opened": 0,
        "still_open": 0,
    }


def posttest_funnel(
    due: Iterable[Mapping[str, Any]],
    poses: Mapping[tuple, Mapping[str, Any]],
    skips: Mapping[tuple, str],
    *,
    now: datetime,
    ttl_hours: float = POSTTEST_POSE_TTL_HOURS,
    windows: Sequence[int] = POSTTEST_WINDOWS_DAYS,
) -> list[dict]:
    """Per window, what happened to each due window (due_windows): its pose
    (`poses`, keyed (user_id, node_id, window_days): one row per window, a
    renewal replaces it) is answered (and `unassisted` when graded at rung 0),
    expired (unanswered past its TTL, or with an unreadable posed_at — void, as
    the route reads it) or open; with no pose, it is skipped when a skip was
    recorded for it (`skips`, same key → reason) and not opened otherwise.
    `still_open` counts the unanswered ones whose window has not closed yet. A
    window outside `windows` is ignored; every window is reported, zeros and
    all — here a zero IS the count."""
    out = {w: _empty_funnel(w) for w in windows}
    ttl = timedelta(hours=ttl_hours)
    for d in due:
        window = d.get("window_days")
        if isinstance(window, bool) or window not in out:
            continue
        row = out[window]
        key = (d.get("user_id"), d.get("node_id"), window)
        row["due"] += 1
        pose = poses.get(key)
        answered = False
        if pose is not None:
            row["opened"] += 1
            if pose.get("answered_at"):
                answered = True
                row["answered"] += 1
                row["unassisted"] += int(posttest_outcome(pose) is not None)
            else:
                posed = _ts(pose.get("posed_at"))
                if posed is None or posed + ttl < now:
                    row["expired"] += 1
                else:
                    row["open"] += 1
        elif key in skips:
            row["skipped"] += 1
            reason = skips[key]
            reasons = row["skip_reasons"]
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            row["not_opened"] += 1
        closes = _ts(d.get("closes_at"))
        if not answered and closes is not None and now < closes:
            row["still_open"] += 1
    return list(out.values())
