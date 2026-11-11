"""The post-test's poses (spec §10 rung 3, A87): its window, exposure rules and
the pose rows it opens, claims, answers and releases.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Iterable, Mapping
from typing import get_args
from db.connection import page_all, table
from learning import zpd_events
from learning.checks import PosttestChoice, choose_posttest_item, posttest_reserves, pretest_match
from learning.learning_gain import window_at
from learning.loop_state_store import reported_hashes, revealed_hashes, seen_hashes
from services.loop.posed import _ts
from learning.params import (
    LOOP_GRADING_CLAIM_STALE_S,
    POSTTEST_POSE_TTL_HOURS,
    POSTTEST_WINDOWS_DAYS,
)
from services.graph_service import _normalize_concept

from services.loop.served import _POSES

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── Tool-removed post-test (PKG-14; spec §10 rung 3, A16, A23, A112, A113) ─

#: Every value `zpd.step.phase` may carry (PKG-06's Phase; spec §13 A8 adds
#: "posttest"). The `sessions.close_phase` CHECK is NOT widened: posttest is a
#: step phase only.
STEP_PHASES: tuple[str, ...] = get_args(zpd_events.Phase)


_NOT_A_POSTTEST_ITEM = "not a post-test item"


_ONE_DAY = timedelta(days=1)


def _posttest_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(ts: datetime) -> str:
    """A UTC ISO timestamp with no '+' (safe inside a PostgREST or=(…) filter)."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _posttest_window(anchor: datetime, now: datetime) -> int | None:
    """A112/A126: the fixed follow-up window `now` falls in, counted from
    `anchor`, the concept's FIRST graded evidence (practice cannot move it) —
    learning_gain.window_at, the one rule the funnel reads too. A window runs
    until the next one opens and the last closes POSTTEST_LAST_WINDOW_CLOSE_DAYS
    after the anchor, so a window the student was away for is skipped, never
    posed late under its label. None before the first window opens and after
    the last one closes."""
    return window_at(anchor, now)


def _posttest_exposed(user_id: str) -> set[str]:
    """seen ∪ revealed (A23): what a post-test never poses because the student
    has answered it or been shown its answer."""
    return set(seen_hashes(user_id)) | set(revealed_hashes(user_id))


def _posttest_excluded(user_id: str, reported: set[str] | None = None) -> set[str]:
    """seen ∪ revealed (A23) ∪ reported (A113), read once per request (the
    reported set is the caller's when it has read it already)."""
    if reported is None:
        reported = set(reported_hashes(user_id))
    return _posttest_exposed(user_id) | reported


class _CourseNodesRead:
    """A read-only page_all handle over graph_nodes (invariant 1's ast half
    allows the table only as a direct read — check_item_service's pattern)."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


def _course_nodes(user_id: str, course_id: str) -> dict[str, str]:
    """node id → concept key of the student's nodes in the course (paged)."""
    return {
        row["id"]: _normalize_concept(row.get("concept_name") or "")
        for row in page_all(
            _CourseNodesRead(),
            "id,concept_name",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
            order="id",
        )
        if row.get("id")
    }


def _read_poses(user_id: str, course_id: str) -> dict[str, dict[int, dict]]:
    """node id → window → the student's post-test pose rows in the course (A87;
    one row per (student, node, window) since A112)."""
    rows = table(_POSES).select(
        "node_id,window_days,question_hash,posed_at,answered_at,claim,claimed_at",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    poses: dict[str, dict[int, dict]] = {}
    for r in rows or []:
        if r.get("node_id"):
            poses.setdefault(r["node_id"], {})[int(r["window_days"])] = r
    return poses


def _pose_open(pose: dict | None, now: datetime) -> bool:
    """Unanswered and younger than POSTTEST_POSE_TTL_HOURS (A89): an expired
    pose is void — it may be re-posed. An unreadable posed_at is void too."""
    if not pose or pose.get("answered_at"):
        return False
    posed = _ts(pose.get("posed_at"))
    return posed is not None and posed >= now - timedelta(hours=POSTTEST_POSE_TTL_HOURS)


def _posed_order(pose: dict) -> tuple:
    """Earliest posed first; an unreadable posed_at sorts first; then the window."""
    return (_ts(pose.get("posed_at")) or datetime.min.replace(tzinfo=timezone.utc), int(pose["window_days"]))


def _open_posed_item(node_poses: dict[int, dict], items: list, now: datetime, reported: set[str]):
    """(pose, item) of the node's OPEN pose whose item is still in the bank — the
    earliest posed, should a race have left two (A87: returned as posed, never
    re-chosen); None when there is none. An open pose whose item was withdrawn
    counts as no pose, as it did before A112, and so does one whose item is in
    `reported` (A113: an item the student reported is never posed again — in
    any window)."""
    by_hash = {i.question_hash: i for i in items if i.question_hash not in reported}
    posed = [
        (p, by_hash[p.get("question_hash")])
        for p in node_poses.values()
        if _pose_open(p, now) and p.get("question_hash") in by_hash
    ]
    return min(posed, key=lambda pi: _posed_order(pi[0]), default=None)


def _bound_item(items: list, node_poses: dict[int, dict], excluded: set[str]):
    """A93 (minor 6), across windows since A112: the node's newest UNANSWERED
    pose (expired, or open with a withdrawn or reported item) keeps its item
    bound to the node — the next pose, a renewal in its window or a later
    window's, is that SAME item, never a fresh one to dodge it — while the item
    is still fresh (A23: neither seen nor revealed since; a stale item would
    grade practice as a delayed outcome) and not reported (A113: `excluded`
    holds the student's reported items, never posed again). None → the
    window's choice (`_window_choice`, A126)."""
    unanswered = [p for p in node_poses.values() if not p.get("answered_at")]
    if not unanswered:
        return None
    qh = max(unanswered, key=_posed_order).get("question_hash")
    if qh in excluded:
        return None
    return next((i for i in items if i.question_hash == qh), None)


def _new_pose(user_id: str, course_id: str, node: str, window: int, choice, span, now: datetime) -> dict:
    """A112: a pose row — its window, the window's fixed anchor (the concept's
    first graded evidence: journal row id and time), and the concept's last
    evidence before the pose with the days since it, the delay an analysis
    stratifies on (truly delayed vs recently practised — practice no longer
    postpones a window). A126: how its item was chosen (`choice`, a
    checks.PosttestChoice: `item_match` against the student's pretest item,
    `item_source` reserve or fallback). The outcome (`correct`, `max_rung`) and
    what the answer reports (`served_at` once the client shows the item; the
    latency and the page-hidden telemetry once it is answered) stay NULL — a
    renewal (A89/A93) resets them all. Hashes, ids, codes, times and numbers
    only."""
    return {
        "user_id": user_id,
        "node_id": node,
        "course_id": course_id,
        "window_days": window,
        "question_hash": choice.item.question_hash,
        "posed_at": now.isoformat(),
        "answered_at": None,
        "claim": None,
        "claimed_at": None,
        "anchor_event_id": span.first_id,
        "anchor_at": span.first_at.isoformat(),
        "last_evidence_at": span.last_at.isoformat(),
        "days_since_evidence": max(0.0, (now - span.last_at) / _ONE_DAY),
        "correct": None,
        "max_rung": None,
        "item_match": choice.match,
        "item_source": choice.source,
        "served_at": None,
        "answer_latency_s": None,
        "hidden_count": None,
        "hidden_s": None,
    }


def _record_poses(rows: list[dict]) -> None:
    """Open (or renew, A89/A93) the poses — one upsert, one row per (student,
    node, window) (A112)."""
    if rows:
        table(_POSES).upsert(rows, on_conflict="user_id,node_id,window_days")


#: spec §13 A126: a due window with nothing fresh to pose, and why — one row
#: per (student, node, window), the latest reason (written by /posttest/start)
_SKIPS = "posttest_skips"


def _skip_row(user_id: str, course_id: str, node: str, window: int, reason: str, now: datetime) -> dict:
    return {
        "user_id": user_id,
        "node_id": node,
        "course_id": course_id,
        "window_days": window,
        "reason": reason,
        "skipped_at": now.isoformat(),
    }


def _record_skips(rows: list[dict]) -> None:
    """A126: record the due windows /posttest/start had to skip, so the funnel
    can count them. One upsert. A measurement record, not the pose: a failed
    write logs and the start still answers (its poses are already committed)."""
    if not rows:
        return
    try:
        table(_SKIPS).upsert(rows, on_conflict="user_id,node_id,window_days")
    except Exception:
        logger.warning("post-test skips not recorded (%d)", len(rows), exc_info=True)


def _stamp_served(user_id: str, node_id: str, question_hash: str, now: datetime) -> bool:
    """A126: the first time the client SHOWS an open pose's item — one
    conditional UPDATE of the open pose (unanswered, within its TTL) whose
    served_at is still NULL, so a reload or a repeat call keeps the first
    display. The server's clock: a latency is answered_at − served_at, both
    stamped here. True when this call stamped it."""
    rows = table(_POSES).update(
        {"served_at": now.isoformat()},
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "question_hash": f"eq.{question_hash}",
            "answered_at": "is.null",
            "served_at": "is.null",
            "posed_at": f"gte.{_iso_z(now - timedelta(hours=POSTTEST_POSE_TTL_HOURS))}",
        },
    )
    return bool(rows)


def _claim_pose(
    user_id: str, node_id: str, question_hash: str, claim: str, now: datetime
) -> dict | None:
    """The DB claim (A87): one conditional UPDATE — the OPEN pose of this item
    (unanswered, posed within POSTTEST_POSE_TTL_HOURS, A89), unclaimed, with no
    claim time (m10) or under a claim older than LOOP_GRADING_CLAIM_STALE_S — so
    only one submission grades it, whatever the number of backend processes.
    A112: a node has one row per window, so the open pose's window is read first
    (the earliest posed, should a race have left two) and the UPDATE names it:
    one answer never closes two windows. Returns the claimed row (its posed_at
    and window_days), or None."""
    open_pose = {
        "user_id": f"eq.{user_id}",
        "node_id": f"eq.{node_id}",
        "question_hash": f"eq.{question_hash}",
        "answered_at": "is.null",
        "posed_at": f"gte.{_iso_z(now - timedelta(hours=POSTTEST_POSE_TTL_HOURS))}",
    }
    posed = table(_POSES).select("window_days,posed_at", filters=open_pose) or []
    if not posed:
        return None
    window = int(min(posed, key=_posed_order)["window_days"])
    stale = _iso_z(now - timedelta(seconds=LOOP_GRADING_CLAIM_STALE_S))
    rows = table(_POSES).update(
        {"claim": claim, "claimed_at": now.isoformat()},
        filters={
            **open_pose,
            "window_days": f"eq.{window}",
            "or": f"(claim.is.null,claimed_at.is.null,claimed_at.lt.{stale})",
        },
    )
    return rows[0] if rows else None


def _answer_pose(
    user_id: str,
    node_id: str,
    claim: str,
    now: datetime,
    *,
    correct: bool,
    max_rung: int,
    latency_s: float | None = None,
    hidden_count: int | None = None,
    hidden_s: float | None = None,
) -> bool:
    """m1/m2: re-validate the claim and CLOSE the pose before the one flush —
    a conditional UPDATE on this claim, still unanswered. The same write records
    the post-test OUTCOME (A112): `correct` and the rung the grade carries
    (`max_rung`, the floor after the in-claim re-read; above 0 it is no clean
    delayed outcome) — and, A126, what the answer reports beside it: the
    latency (answered_at − served_at, None when the item's display was never
    stamped) and the page-hidden telemetry, already clamped
    (learning_gain.clamp_visibility). None of it reaches the grade. True → the
    pose is answered for good (a later failure never reopens it: fail closed);
    False → the claim was taken over, and nothing may be written."""
    rows = table(_POSES).update(
        {
            "answered_at": now.isoformat(),
            "claim": None,
            "claimed_at": None,
            "correct": bool(correct),
            "max_rung": int(max_rung),
            "answer_latency_s": latency_s,
            "hidden_count": hidden_count,
            "hidden_s": hidden_s,
        },
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "claim": f"eq.{claim}",
            "answered_at": "is.null",
        },
    )
    return bool(rows)


def _release_pose(user_id: str, node_id: str, claim: str) -> None:
    """Nothing was graded: release this claim (an unanswered pose only)."""
    table(_POSES).update(
        {"claim": None, "claimed_at": None},
        filters={
            "user_id": f"eq.{user_id}",
            "node_id": f"eq.{node_id}",
            "claim": f"eq.{claim}",
            "answered_at": "is.null",
        },
    )


def _due_nodes(
    nodes: Iterable[str], poses: Mapping[str, dict[int, dict]], anchors: Mapping[str, datetime], now: datetime
) -> dict[str, int | None]:
    """A112: candidate node → its due, unanswered window, or None when only an
    open pose keeps it a candidate (an open pose stays posed until answered or
    expired, even when no window is due). `anchors`: node → its FIRST graded
    evidence time. Shared by /posttest/start and GET /posttest/due."""
    due: dict[str, int | None] = {}
    for node in nodes:
        node_poses = poses.get(node) or {}
        anchor = anchors.get(node)
        window = _posttest_window(anchor, now) if anchor is not None else None
        if window is not None and (node_poses.get(window) or {}).get("answered_at"):
            window = None  # answered: a window is posed at most once
        if window is not None or any(_pose_open(p, now) for p in node_poses.values()):
            due[node] = window
    return due


def _posttest_plans(
    due: Mapping[str, int | None],
    poses: Mapping[str, dict[int, dict]],
    anchors: Mapping[str, datetime],
    items_of: Callable[[str], list],
    now: datetime,
    reported: set[str],
) -> list[tuple]:
    """(order, node, the open pose's item or None, the window to pose or None),
    sorted: open poses first (A87: returned as posed), then the
    earliest-opened windows. An open pose of a withdrawn or reported item
    counts as no pose (A113), so its due window is posed afresh."""
    plans = []
    for node, window in due.items():
        current = _open_posed_item(poses.get(node) or {}, items_of(node), now, reported)
        if current is not None:
            plans.append(((0, _posed_order(current[0])[0], node), node, current[1], None))
        elif window is not None:
            opened = anchors[node] + timedelta(days=window)
            plans.append(((1, opened, node), node, None, window))
    return sorted(plans, key=lambda p: p[0])


def _window_choice(items: list, node_poses: dict[int, dict], excluded: set[str], window: int, pretest):
    """The item a due window poses (A23, A93, A113, A126) — a
    checks.PosttestChoice, or None (nothing fresh: the window is skipped). The
    newest unanswered pose's item first while it is fresh (A93: bound across
    windows, never shopped away); else checks.choose_posttest_item: a fresh
    protected reserve matched to the student's pretest item, else a fallback."""
    bound = _bound_item(items, node_poses, excluded)
    if bound is not None:
        source = "reserve" if bound.question_hash in posttest_reserves(items) else "fallback"
        return PosttestChoice(bound, pretest_match(bound, pretest), source)
    return choose_posttest_item(
        items, excluded, window_index=POSTTEST_WINDOWS_DAYS.index(window), pretest=pretest
    )
