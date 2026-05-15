"""
Pure functions for gradebook math.

No Supabase or HTTP coupling — routes pass in plain rows/dicts and get back
plain dicts. Keeps the calc logic trivially testable.
"""
from __future__ import annotations

from typing import Iterable, Optional, TypedDict


class CategoryRow(TypedDict, total=False):
    id: str
    name: str
    weight: float
    sort_order: int
    drop_lowest: int


class AssignmentRow(TypedDict, total=False):
    id: str
    title: str
    category_id: Optional[str]
    points_possible: Optional[float]
    points_earned: Optional[float]


# Default letter scale, descending. Keys are floor percentages.
DEFAULT_LETTER_SCALE: list[tuple[float, str]] = [
    (93.0, "A"),
    (90.0, "A-"),
    (87.0, "B+"),
    (83.0, "B"),
    (80.0, "B-"),
    (77.0, "C+"),
    (73.0, "C"),
    (70.0, "C-"),
    (67.0, "D+"),
    (63.0, "D"),
    (60.0, "D-"),
    (0.0,  "F"),
]


def _coerce_drop(value) -> int:
    """Categories from the DB carry drop_lowest as int; tolerate Nones too."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def dropped_assignment_ids(
    items: Iterable[AssignmentRow],
    drop_lowest: int,
) -> list[str]:
    """Return ids of the `drop_lowest` lowest-scoring graded assignments in
    a single category. Score is earned/possible — ties broken by larger
    points_possible first (drop the higher-stakes failure), then by id for
    determinism. Returns up to `drop_lowest` ids; fewer if not enough
    graded items exist."""
    n = _coerce_drop(drop_lowest)
    if n <= 0:
        return []
    graded: list[tuple[float, float, str]] = []
    for a in items:
        p = a.get("points_possible")
        e = a.get("points_earned")
        aid = a.get("id")
        if p is None or e is None or aid is None:
            continue
        if float(p) <= 0:
            continue
        graded.append((float(e) / float(p), float(p), str(aid)))
    if not graded:
        return []
    graded.sort(key=lambda x: (x[0], -x[1], x[2]))
    return [aid for (_, _, aid) in graded[:n]]


def category_grade(
    items: Iterable[AssignmentRow],
    drop_lowest: int = 0,
) -> Optional[float]:
    """Return the 0–1 grade for one category, or None if no graded items.

    A graded item has both points_possible (> 0) and points_earned (not None).
    The lowest `drop_lowest` graded items (by earned/possible) are excluded
    before averaging. Sums earned / sums possible across the kept items.
    """
    items = list(items)
    dropped = set(dropped_assignment_ids(items, drop_lowest))
    total_possible = 0.0
    total_earned = 0.0
    for item in items:
        possible = item.get("points_possible")
        earned = item.get("points_earned")
        if possible is None or earned is None:
            continue
        if float(possible) <= 0:
            continue
        if item.get("id") in dropped:
            continue
        total_possible += float(possible)
        total_earned += float(earned)
    if total_possible == 0:
        return None
    return total_earned / total_possible


def current_grade(
    categories: list[CategoryRow],
    assignments: Iterable[AssignmentRow],
) -> Optional[float]:
    """Return the 0–100 current grade across all categories, or None.

    For each category with at least one graded item, computes the
    category_grade (respecting per-category drop_lowest) and weights it
    by the category's weight. Categories with no graded items drop out —
    total weight is renormalized so contributing weights sum to 100.
    """
    by_cat: dict[str, list[AssignmentRow]] = {c["id"]: [] for c in categories}
    for a in assignments:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)

    total_weight = 0.0
    weighted_sum = 0.0
    for cat in categories:
        grade = category_grade(by_cat[cat["id"]], cat.get("drop_lowest", 0))
        if grade is None:
            continue
        total_weight += float(cat["weight"])
        weighted_sum += grade * float(cat["weight"])

    if total_weight == 0:
        return None
    return (weighted_sum / total_weight) * 100.0


def all_dropped_ids(
    categories: list[CategoryRow],
    assignments: Iterable[AssignmentRow],
) -> list[str]:
    """Flatten every category's currently-dropped assignment IDs. Useful for
    the API to send to the frontend so dropped items can be flagged in the UI."""
    by_cat: dict[str, list[AssignmentRow]] = {c["id"]: [] for c in categories}
    for a in assignments:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)
    out: list[str] = []
    for cat in categories:
        out.extend(dropped_assignment_ids(by_cat[cat["id"]], cat.get("drop_lowest", 0)))
    return out


def letter_for(percent: Optional[float], scale: Optional[list[dict]]) -> Optional[str]:
    """Map a 0–100 percentage to a letter using the given scale (or default).

    Custom scale shape: [{"min": 90, "letter": "A"}, ...] sorted descending
    by min during evaluation. None percent → None letter.
    """
    if percent is None:
        return None
    if scale:
        ordered = sorted(scale, key=lambda x: -float(x.get("min", 0)))
        for tier in ordered:
            if percent >= float(tier["min"]):
                return str(tier["letter"])
        return None
    for floor, letter in DEFAULT_LETTER_SCALE:
        if percent >= floor:
            return letter
    return None
