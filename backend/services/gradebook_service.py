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
