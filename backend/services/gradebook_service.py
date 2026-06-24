"""
Pure functions for gradebook math.

No Supabase or HTTP coupling — routes pass in plain rows/dicts and get back
plain dicts. Keeps the calc logic trivially testable.

This module is schema-agnostic: it never sees ``user_id`` / ``course_id`` /
``enrollment_id``. The routes resolve the enrollment and hand the math layer
plain category + assignment rows plus the enrollment's curve policy.
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

# Standard letter → 4.0-scale grade points (US GPA convention).
LETTER_GRADE_POINTS: dict[str, float] = {
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "C-": 1.7,
    "D+": 1.3,
    "D": 1.0,
    "D-": 0.7,
    "F": 0.0,
}


def category_grade(
    items: Iterable[AssignmentRow],
    drop_lowest: int = 0,
) -> Optional[float]:
    """Return the 0–1 grade for one category, or None if no graded items.

    A graded item has both points_possible (> 0) and points_earned (not None).
    Sums earned / sums possible across graded items.

    Drop-lowest policy (gradebook_categories.drop_lowest): if ``drop_lowest > 0``,
    the N graded items with the lowest per-item ratio (earned/possible) are
    discarded before summing. If ``drop_lowest`` is >= the number of graded
    items the category has no contributing items and returns None (so it drops
    out of the weighted average and its weight is renormalized away).
    """
    graded = []
    for item in items:
        possible = item.get("points_possible")
        earned = item.get("points_earned")
        if possible is None or earned is None:
            continue
        if possible <= 0:
            continue
        graded.append((float(possible), float(earned)))

    if not graded:
        return None

    if drop_lowest and drop_lowest > 0:
        # Drop the N items with the lowest earned/possible ratio.
        graded.sort(key=lambda pe: pe[1] / pe[0])
        graded = graded[drop_lowest:]
        if not graded:
            return None

    total_possible = sum(p for p, _ in graded)
    total_earned = sum(e for _, e in graded)
    if total_possible == 0:
        return None
    return total_earned / total_possible


def apply_curve(
    raw_percent: Optional[float],
    *,
    class_mean: Optional[float],
    class_sd: Optional[float],
    avg_target: Optional[float],
    sd_delta: Optional[float],
) -> Optional[float]:
    """Linear z-score bell-curve rescale of a 0–100 percent.

    The curve recenters the class distribution on ``avg_target`` and optionally
    re-scales its spread by ``sd_delta`` (a delta added to the class standard
    deviation — negative tightens the spread, positive widens it)::

        new_sd = class_sd + sd_delta
        curved = avg_target + (raw - class_mean) * (new_sd / class_sd)
        curved = clamp(curved, 0, 100)

    The student keeps their position relative to the class mean but the whole
    distribution slides so the class average lands on ``avg_target``.

    Degenerate inputs fall back to ``raw_percent`` (no curve) so a missing or
    zero class SD, or a missing target, can never blow up or zero out a grade.
    """
    if raw_percent is None:
        return None
    if avg_target is None or class_mean is None:
        return raw_percent
    if not class_sd:  # None or 0 — can't rescale spread; just return raw.
        return raw_percent
    new_sd = float(class_sd) + float(sd_delta or 0.0)
    curved = float(avg_target) + (raw_percent - float(class_mean)) * (new_sd / float(class_sd))
    return max(0.0, min(100.0, curved))


def _class_stats_from_assignments(
    assignments: Iterable[AssignmentRow],
) -> tuple[Optional[float], Optional[float]]:
    """Average the per-assignment class mean / class sd carried on assignment
    rows (curve_class_mean / curve_class_sd, plaintext NUMERIC). Returns
    (mean, sd) using the mean of the present values, or (None, None) when no
    assignment carries stats. Lets an enrollment-level curve borrow class stats
    that the (out-of-scope) gradescope sync stamps per assignment.
    """
    means = [float(a["curve_class_mean"]) for a in assignments
             if a.get("curve_class_mean") is not None]
    sds = [float(a["curve_class_sd"]) for a in assignments
           if a.get("curve_class_sd") is not None]
    mean = sum(means) / len(means) if means else None
    sd = sum(sds) / len(sds) if sds else None
    return mean, sd


def current_grade(
    categories: list[CategoryRow],
    assignments: Iterable[AssignmentRow],
    *,
    curve_mode: str = "raw",
    curve_avg_target: Optional[float] = None,
    curve_sd_delta: Optional[float] = None,
) -> Optional[float]:
    """Return the 0–100 current grade across all categories, or None.

    For each category with at least one graded item (after applying the
    category's ``drop_lowest``), computes the category_grade and weights it by
    the category's weight. Categories with no contributing graded items drop
    out — total weight is renormalized so the contributing weights sum to 100.

    When ``curve_mode == 'curved'`` the final weighted percent is run through
    ``apply_curve`` using the enrollment-level ``curve_avg_target`` /
    ``curve_sd_delta`` policy against the class mean/sd derived from the
    assignments' per-assignment curve stats. If no class stats are available
    the curve degenerates to a no-op (raw percent).
    """
    assignments = list(assignments)
    by_cat: dict[str, list[AssignmentRow]] = {c["id"]: [] for c in categories}
    for a in assignments:
        cid = a.get("category_id")
        if cid in by_cat:
            by_cat[cid].append(a)

    total_weight = 0.0
    weighted_sum = 0.0
    for cat in categories:
        grade = category_grade(by_cat[cat["id"]], int(cat.get("drop_lowest") or 0))
        if grade is None:
            continue
        total_weight += float(cat["weight"])
        weighted_sum += grade * float(cat["weight"])

    if total_weight == 0:
        return None
    raw = (weighted_sum / total_weight) * 100.0

    if curve_mode == "curved":
        class_mean, class_sd = _class_stats_from_assignments(assignments)
        return apply_curve(
            raw,
            class_mean=class_mean,
            class_sd=class_sd,
            avg_target=curve_avg_target,
            sd_delta=curve_sd_delta,
        )
    return raw


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


def gpa_points(
    percent: Optional[float],
    scale: Optional[list[dict]] = None,
) -> Optional[float]:
    """Map a 0–100 percentage to 4.0-scale grade points, or None.

    Resolves the letter via ``letter_for`` (custom or default scale), then maps
    the letter through the standard LETTER_GRADE_POINTS table. Unknown letters
    (e.g. from an exotic custom scale) fall back to None so they don't silently
    score 0.0 into a GPA.
    """
    letter = letter_for(percent, scale)
    if letter is None:
        return None
    return LETTER_GRADE_POINTS.get(letter)


def weighted_gpa(course_grades: Iterable[dict]) -> Optional[float]:
    """Credit-weighted GPA across courses, or None when nothing contributes.

    ``course_grades`` items: {"grade_points": float | None, "credits": number}.
    Entries with ``grade_points is None`` (ungraded) are skipped. Credits
    default to 1 when null/zero so a course always counts at least once::

        gpa = Σ(grade_points_i * credits_i) / Σ credits_i
    """
    total_credits = 0.0
    total_points = 0.0
    for cg in course_grades:
        gp = cg.get("grade_points")
        if gp is None:
            continue
        credits = cg.get("credits")
        c = float(credits) if credits else 1.0
        if c <= 0:
            c = 1.0
        total_credits += c
        total_points += float(gp) * c
    if total_credits == 0:
        return None
    return total_points / total_credits
