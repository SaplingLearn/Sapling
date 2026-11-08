"""Empirical item statistics for staff (learning-loop spec §13 A131).
Pure: stdlib, learning.params, learning.evidence (the writer's weight rule),
learning.evidence_void (the one void rule) and learning.item_audit (the
Wilson interval).

Classical item analysis of the check items over the evidence journal, per
course item — (course_id, question_hash), the identity the review queue, the
reports and the void rule key on (A113, A123) — from each student's FIRST
graded attempt on it, kept only when that attempt was unassisted:

  • `n` — the students whose first attempt was unassisted, `correct` of them
    right;
  • `p_value` — correct / n, the classical difficulty (the share who got it
    right; high = easy), with its Wilson 95% interval;
  • `discrimination` — the corrected item–rest point-biserial: the Pearson
    correlation, over the students who also have a first unassisted attempt on
    at least one OTHER item of the same concept (`discrimination_n` of them),
    between the item's outcome (1 right, 0 wrong) and their rest score — their
    correct share on those other items. Corrected: the item never counts in
    its own rest score. The concept is the student's node (items are course
    assets per concept; nodes are per student, A2). None when either side does
    not vary — r is undefined there, and a constant outcome is the p-value's
    finding, not a discrimination one;
  • `flags` — `too_easy` (p > ITEM_STATS_EASY_P), `too_hard`
    (p < ITEM_STATS_HARD_P), `negative_discrimination` (r < 0) and
    `low_discrimination` (0 ≤ r < ITEM_STATS_LOW_DISCRIMINATION), each only
    once its own n reaches ITEM_STATS_MIN_N.

UNASSISTED is the loop's own definition, never a new one:
  • no help — `assisted` false (unknown help is never unassisted, as the band-
    control window reads it) and the journaled rung 0, which is the rung AFTER
    the A93 help floor: a recorded hint, a served reveal, an outside-AI help
    row or an unscanned turn raised it;
  • not a re-check after a release (A76: "never an unassisted first attempt")
    — `same_session_recheck` as the writer journals it since A123; on an older
    row the planning envelope's flag, else the one flag the writer's own
    weight rule (`evidence.evidence_weight`) needs to give the journaled
    weight — evidence_replay's rule; undecidable → not unassisted (fail
    closed).
An idk is an answer the evidence model scores incorrect, and so is it here.

FIRST attempt = the student's first graded row on the item in the journal's
total order (created_at, evidence_seq, id). A later attempt is never a first
one, whatever its help: a student whose first attempt was helped contributes
nothing to that item. A pair (student, item) with a row whose time cannot be
read is left out — its first attempt is unknown.

A row graded against an item staff retired is void evidence (A123): left out
everywhere — the item's own outcomes and every rest score. The caller passes
the retired items (the review decisions with status 'retired', the rows
`item_reports.retired_items` reads), as a mapping to their decision times when
it has them, so `numbers_changed_at` can date the change a retire makes. A
row with no check item (a quiz question) is no check-item attempt.

A report for staff: it never writes, never gates, never touches lint_flags or
a hold. Staff read the numbers in the review queue and decide.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from learning.evidence import Evidence, evidence_weight
from learning.evidence_void import ItemKey, graded_item, is_void_row
from learning.item_audit import wilson
from learning.params import (
    CHANNELS,
    ITEM_STATS_EASY_P,
    ITEM_STATS_FLAGS,
    ITEM_STATS_HARD_P,
    ITEM_STATS_LOW_DISCRIMINATION,
    ITEM_STATS_MIN_N,
)

_NO_SEQ = math.inf  # a row without evidence_seq (before A36) sorts after those with one


def _user(row: Mapping[str, Any]) -> str | None:
    """The student a journal row belongs to: its own `user_id`, else its
    node's owner from a `graph_nodes!inner(user_id)` embed."""
    user = row.get("user_id")
    if not (isinstance(user, str) and user) and isinstance(row.get("graph_nodes"), Mapping):
        user = row["graph_nodes"].get("user_id")
    return user if isinstance(user, str) and user else None


def _time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _idk(row: Mapping[str, Any]) -> bool:
    return row.get("reason") == f"evidence:{row.get('channel')}:idk"


def recheck(row: Mapping[str, Any]) -> bool | None:
    """Was the row graded as a re-check after a release (A76)? The writer's
    journaled flag (A123), else the planning envelope's, else the one flag the
    writer's weight rule needs to give the journaled weight on this unassisted
    rung-0 row; None when that cannot be decided."""
    flag = row.get("same_session_recheck")
    if isinstance(flag, bool):
        return flag
    envelope = row.get("planning_recheck")
    if isinstance(envelope, bool):
        return envelope
    weight, channel, correct = _number(row.get("weight")), row.get("channel"), row.get("correct")
    if weight is None or channel not in CHANNELS or not isinstance(correct, bool):
        return None
    found = []
    for candidate in (False, True):
        try:
            ev = Evidence(
                node_id=str(row.get("node_id") or "node"),
                channel=channel,
                correct=correct and not _idk(row),
                idk=_idk(row),
                assisted=False,
                max_rung=0,
                confidence=_number(row.get("confidence")),
                same_session_recheck=candidate,
            )
        except ValidationError:
            return None
        if evidence_weight(ev) == weight:
            found.append(candidate)
    return found[0] if len(found) == 1 else None


def unassisted(row: Mapping[str, Any]) -> bool:
    """The attempt had no help and was no re-check after a release — the
    loop's definition (see the module docstring)."""
    rung = row.get("max_rung")
    if row.get("assisted") is not False:
        return False
    if isinstance(rung, bool) or not isinstance(rung, int) or rung != 0:
        return False
    return recheck(row) is False


def _outcome(row: Mapping[str, Any]) -> int | None:
    """1 right, 0 wrong (an idk is wrong); None when the row records no outcome."""
    correct = row.get("correct")
    if not isinstance(correct, bool):
        return None
    return 0 if _idk(row) else int(correct)


def first_unassisted(
    rows: Iterable[Mapping[str, Any]], *, retired: Collection[ItemKey] = frozenset()
) -> list[dict]:
    """One observation per (student, course item) whose FIRST graded attempt
    was unassisted: {user_id, node_id, item: (course_id, question_hash),
    outcome: 0 | 1, at: its journal time}. Void rows and rows with no check
    item are left out before the first attempt is found, so a void attempt is
    never anyone's first. In (student, course, question_hash) order."""
    by_pair: dict[tuple[str, ItemKey], list[tuple[datetime | None, float, str, Mapping]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, Mapping) or is_void_row(row, retired):
            continue
        item, user = graded_item(row), _user(row)
        if item is None or user is None or not row.get("node_id"):
            continue
        seq = _number(row.get("evidence_seq"))
        by_pair[(user, item)].append(
            (_time(row.get("created_at")), _NO_SEQ if seq is None else seq, str(row.get("id") or ""), row)
        )
    out: list[dict] = []
    for (user, item), attempts in sorted(by_pair.items()):
        if any(at is None for at, _, _, _ in attempts):
            continue  # an unreadable time: the first attempt is unknown
        at, _, _, first = min(attempts, key=lambda a: a[:3])
        outcome = _outcome(first)
        if outcome is None or not unassisted(first):
            continue
        out.append({"user_id": user, "node_id": first["node_id"], "item": item, "outcome": outcome, "at": at})
    return out


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    """The Pearson correlation of the pairs; None with fewer than two or when
    either side does not vary. "Does not vary" is decided on the values
    themselves, never on a computed variance: a constant rest score such as
    1/3 leaves a variance of float noise (~1e-32), not 0, and its "r" would be
    noise read as a (negative) discrimination. Equal shares are equal floats
    (division is correctly rounded), so the set test is exact."""
    n = len(pairs)
    if n < 2 or len({x for x, _ in pairs}) < 2 or len({y for _, y in pairs}) < 2:
        return None
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def flags_for(n: int, p_value: float | None, discrimination_n: int, discrimination: float | None) -> list[str]:
    """The data flags (ITEM_STATS_FLAGS order), each only once its own n
    reaches ITEM_STATS_MIN_N. A flag asks staff to look; it decides nothing."""
    out = []
    if p_value is not None and n >= ITEM_STATS_MIN_N:
        if p_value > ITEM_STATS_EASY_P:
            out.append("too_easy")
        if p_value < ITEM_STATS_HARD_P:
            out.append("too_hard")
    if discrimination is not None and discrimination_n >= ITEM_STATS_MIN_N:
        if discrimination < 0.0:
            out.append("negative_discrimination")
        elif discrimination < ITEM_STATS_LOW_DISCRIMINATION:
            out.append("low_discrimination")
    order = {f: i for i, f in enumerate(ITEM_STATS_FLAGS)}
    return sorted(out, key=order.__getitem__)


def empty_stats() -> dict:
    """An item no student has a first unassisted attempt on."""
    return {
        "n": 0,
        "correct": 0,
        "p_value": None,
        "p_ci_low": None,
        "p_ci_high": None,
        "discrimination": None,
        "discrimination_n": 0,
        "flags": [],
        "numbers_changed_at": None,
    }


def _void_times(
    rows: Iterable[Mapping[str, Any]], retired: Collection[ItemKey]
) -> dict[tuple[str, str], datetime]:
    """(student, node) → when a staff retire last removed some of that
    student's attempts on the node from the statistics: the newest retire
    decision among the items its void rows were graded against. Only when
    `retired` maps each retired item to its decision time; a retire changes
    the numbers the moment it is decided (the void rule reads the decision,
    not the sweep)."""
    if not isinstance(retired, Mapping):
        return {}
    out: dict[tuple[str, str], datetime] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not is_void_row(row, retired):
            continue
        user, node, at = _user(row), row.get("node_id"), retired.get(graded_item(row))
        if user is None or not node or not isinstance(at, datetime):
            continue
        key = (user, node)
        if key not in out or at > out[key]:
            out[key] = at
    return out


def item_statistics(
    rows: Iterable[Mapping[str, Any]], *, retired: Collection[ItemKey] = frozenset()
) -> dict[ItemKey, dict]:
    """(course_id, question_hash) → its statistics (module docstring), for
    every course item some student has a first unassisted attempt on.
    `retired`: the staff-retired items — a mapping of each to its decision
    time when the caller has it (for `numbers_changed_at`), else a set.

    `numbers_changed_at` (ISO) is when the item's numbers last changed: the
    newest first attempt they count — the item's own AND every other-item
    attempt in its students' rest scores, since a new answer on the concept
    changes the discrimination too — or the newest retire that voided some of
    its students' attempts on the concept. Nothing else changes them, so a
    review decided at or after it was decided on the numbers shown."""
    rows = list(rows)
    observations = first_unassisted(rows, retired=retired)
    voided_at = _void_times(rows, retired)
    by_student_node: dict[tuple[str, str], dict[ItemKey, dict]] = defaultdict(dict)
    by_item: dict[ItemKey, list[dict]] = defaultdict(list)
    for ob in observations:
        by_student_node[(ob["user_id"], ob["node_id"])][ob["item"]] = ob
        by_item[ob["item"]].append(ob)
    out: dict[ItemKey, dict] = {}
    for item, obs in by_item.items():
        n = len(obs)
        correct = sum(ob["outcome"] for ob in obs)
        ci = wilson(correct, n)
        pairs = []
        changed = max(ob["at"] for ob in obs)
        for ob in obs:
            student_node = (ob["user_id"], ob["node_id"])
            others = [other for key, other in by_student_node[student_node].items() if key != item]
            if others:
                pairs.append((float(ob["outcome"]), sum(o["outcome"] for o in others) / len(others)))
                changed = max(changed, *(o["at"] for o in others))
            if student_node in voided_at:
                changed = max(changed, voided_at[student_node])
        p_value = correct / n
        discrimination = _pearson(pairs)
        out[item] = {
            "n": n,
            "correct": correct,
            "p_value": p_value,
            "p_ci_low": ci[0],
            "p_ci_high": ci[1],
            "discrimination": discrimination,
            "discrimination_n": len(pairs),
            "flags": flags_for(n, p_value, len(pairs), discrimination),
            "numbers_changed_at": changed.isoformat(),
        }
    return out
