"""The learning loop's scan set (spec §13 A93/A101; owner decision 1): every
item POSED to a student and not yet graded — `posed_items`.

Moved out of routes/learn_loop.py with the #118 layout (spec §13 A149), and
into the loop's package (was services/loop_posed.py) when the route was split
into services/loop/: the loop's turn assembly reads it once per turn, and the
loop's integrity guard on the AI surfaces OUTSIDE the loop
(services/integrity_guard.py, spec §13 A125) reads the same set through the
package (`from services.loop import posed_items`). The loop's modules import
`posed_items` and `_ts` from here under the names they always used, so a
`patch_loop("posed_items")` reaches the loop's own reads, and a patch on
`services.loop.posed.posed_items` the guard's.

PKG-06: `learning.loop_state_store` (its `seen_hashes`) is a PKG-06 module, so
this module is a sanctioned PKG-06 importer (the whole services/loop/ package
is; tests/test_learning_zpd_policy.py); nothing the app loads at boot imports
it — the loop's modules do, and the guard only inside an active guard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.connection import page_all, table
from db.scope import runs_as_service
from learning.help_ledger import ungraded_posed_window
from learning.loop_state_store import seen_hashes
from learning.params import LOOP_SCAN_POSED_MAX
from services.check_item_service import items_by_hash, items_by_ids
from services.session_modes import NOT_REVIEW

# Log records keep the name they had in routes/learn_loop.py, as every module
# of the package does: an operator (or a caplog test) filters on it.
logger = logging.getLogger("routes.learn_loop")

POSES = "posttest_poses"  # spec §13 A87: the post-test commits when it is opened


def _ts(value) -> datetime | None:
    """A posed-at time from Unix seconds or an ISO string (None if unreadable)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@runs_as_service  # spec §13 A148: reads service-only loop tables; called by the notes/flashcards integrity guard
def posed_items(user_id: str, *, now: datetime) -> tuple[list[tuple], datetime | None] | None:
    """A93 (owner decision 1, M2): (item, first posed at) for every item POSED to
    the student and not yet graded — every session's ungraded steps (ended or
    closed sessions too) and its probe item, each ungraded review item, every
    unanswered post-test pose (expired too), and the help ledger's 'posed' rows.

    Spec §13 A101 (focused review M1): an item that is CURRENTLY OPEN — an
    ungraded step, an open review entry, a probe's current item, an unanswered
    pose — is always in the set, whether or not the student has evidence on it
    (review serves previously-seen items; dropping them reopened laundering).
    The seen filter (`seen_hashes`) applies only to the ledger's historical
    'posed' rows. (M2 (a)/(d)): the candidates are ranked by posed time and cut
    to the newest LOOP_SCAN_POSED_MAX BEFORE any item is loaded, then loaded in
    batched reads (`items_by_ids`, `items_by_hash`). The second element is the
    edge of what was left out — the newest candidate beyond the window, or
    (minor 3) the oldest ledger row read when that read hit its row limit —
    at which the caller records an 'unscanned' marker, so every older ungraded
    item grades as assisted. None when any of it cannot be read."""
    try:
        open_ids: dict[str, datetime | None] = {}  # check item id → first posed
        open_hashes: dict[str, datetime | None] = {}  # question hash → first posed

        def keep(store: dict, key, at) -> None:
            if not key:
                return
            if key not in store or (at is not None and (store[key] is None or at < store[key])):
                store[key] = at

        for row in page_all(
            table("sessions"),
            "id,steps:loop_state->steps,probe:loop_state->probe",
            filters={"user_id": f"eq.{user_id}", **NOT_REVIEW},
            order="id",
        ):
            for entry in (row.get("steps") or {}).values():
                if isinstance(entry, dict) and entry.get("graded_at") is None:
                    keep(open_ids, entry.get("check_item_id"), _ts(entry.get("first_shown_at")))
            cur = (row.get("probe") or {}).get("current") if isinstance(row.get("probe"), dict) else None
            if isinstance(cur, dict):
                keep(open_hashes, cur.get("question_hash"), None)
        for row in page_all(
            table("sessions"),
            "id,open:loop_state->open",
            filters={"user_id": f"eq.{user_id}", "mode": "eq.review", "loop_state->open": "not.is.null"},
            order="id",
        ):
            for key, entry in (row.get("open") or {}).items():
                if (
                    isinstance(entry, dict)
                    and not str(key).startswith("fc:")
                    and entry.get("graded_at") is None
                ):
                    keep(open_ids, entry.get("item_id"), _ts(entry.get("served_at")))
        pose_course: dict[str, str] = {}  # a pose names its course: matched on load
        for pose in table(POSES).select(
            "course_id,question_hash,posed_at",
            filters={"user_id": f"eq.{user_id}", "answered_at": "is.null"},
        ) or []:
            keep(open_hashes, pose.get("question_hash"), _ts(pose.get("posed_at")))
            if pose.get("question_hash"):
                pose_course[pose["question_hash"]] = pose.get("course_id")
        ledger, edge = ungraded_posed_window(user_id, LOOP_SCAN_POSED_MAX)
        ledger_hashes = {qh for qh, _ in ledger}
        historical: dict[str, datetime | None] = {}
        for qh, at in ledger:
            if qh in open_hashes:
                keep(open_hashes, qh, at)  # open: always scanned; the earliest pose counts
            else:
                keep(historical, qh, at)
        if historical:  # M1: the seen filter reads the historical rows only
            seen = seen_hashes(user_id)
            historical = {qh: at for qh, at in historical.items() if qh not in seen}
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        candidates = sorted(
            [("id", k, at) for k, at in open_ids.items()]
            + [("hash", k, at) for k, at in open_hashes.items()]
            + [("ledger", k, at) for k, at in historical.items()],
            key=lambda c: c[2] or oldest,
            reverse=True,
        )
        kept, left = candidates[:LOOP_SCAN_POSED_MAX], candidates[LOOP_SCAN_POSED_MAX:]
        overflow = (left[0][2] or now) if left else None
        if edge is not None:
            overflow = edge if overflow is None else max(overflow, edge)
        found: dict[str, tuple] = {}
        ids = sorted(k for kind, k, _ in kept if kind == "id")
        for item in items_by_ids(ids) if ids else []:
            found.setdefault(item.question_hash, (item, open_ids.get(item.id)))
        hashes = sorted(k for kind, k, _ in kept if kind != "id" and k not in found)
        for item in items_by_hash(hashes) if hashes else []:
            qh = item.question_hash
            if qh in pose_course and qh not in ledger_hashes and pose_course[qh] != item.course_id:
                continue  # a pose's hash names an item of ITS course only
            found.setdefault(qh, (item, open_hashes.get(qh, historical.get(qh))))
        ranked = sorted(found.values(), key=lambda pair: pair[1] or oldest, reverse=True)
        return ranked, overflow
    except Exception as exc:
        logger.warning("posed items could not be read (%s)", type(exc).__name__)
        return None
