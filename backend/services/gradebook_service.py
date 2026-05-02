"""
Pure functions for gradebook math.

No Supabase or HTTP coupling — routes pass in plain rows/dicts and get back
plain dicts. Keeps the calc logic trivially testable.
"""
from __future__ import annotations

from typing import Iterable, Optional, TypedDict


class CategoryRow(TypedDict):
    id: str
    name: str
    weight: float
    sort_order: int


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


def category_grade(items: Iterable[AssignmentRow]) -> Optional[float]:
    """Return the 0–1 grade for one category, or None if no graded items.

    A graded item has both points_possible (> 0) and points_earned (not None).
    Sums earned / sums possible across graded items.
    """
    total_possible = 0.0
    total_earned = 0.0
    for item in items:
        possible = item.get("points_possible")
        earned = item.get("points_earned")
        if possible is None or earned is None:
            continue
        if possible <= 0:
            continue
        total_possible += float(possible)
        total_earned += float(earned)
    if total_possible == 0:
        return None
    return total_earned / total_possible
