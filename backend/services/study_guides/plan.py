"""The planned outline: which concepts a guide will cover and how much room
each gets. Decided from the chosen materials and the student's mastery, with
no model call, so the modal can redraw it on every change.
"""
from __future__ import annotations

from config import get_mastery_tier
from models.study_guide import Depth, GuidePlan, GuideRequest, PlanSection, Tier
from services.study_guides.materials import aload_concepts
from services.study_guides.scopes import aresolve_offering
from services.study_guides.signals import amastery, concept_key

#: How many sections a guide of each depth has at most.
SECTION_COUNT: dict[Depth, int] = {"cram": 3, "standard": 5, "deep": 8}
#: Room a section gets by mastery: the weaker the concept, the more space.
TIER_ROOM: dict[Tier, int] = {"struggling": 5, "learning": 3, "unexplored": 3, "mastered": 1}
MINUTES_PER_SECTION: dict[Depth, int] = {"cram": 2, "standard": 5, "deep": 6}


def weights(tiers: list[Tier], *, use_history: bool) -> list[int]:
    """Each section's share of the guide: whole numbers that sum to exactly
    100, none below 1 (for up to 100 sections).

    With history on the shares follow ``TIER_ROOM``; with it off they are
    equal. Rounding is by largest remainder, earlier sections first on a tie.
    """
    if not tiers:
        return []
    room = [TIER_ROOM[tier] if use_history else 1 for tier in tiers]
    total = sum(room)
    shares = [100 * r // total for r in room]
    by_remainder = sorted(range(len(room)), key=lambda i: -(100 * room[i] % total))
    for i in by_remainder[: 100 - sum(shares)]:
        shares[i] += 1
    # Only a long, lopsided outline rounds a section down to nothing: give it
    # one point from the largest.
    for i, share in enumerate(shares):
        if share == 0:
            shares[shares.index(max(shares))] -= 1
            shares[i] = 1
    return shares


def _distinct(concepts: list[str]) -> list[str]:
    """The names in order, the first spelling of each kept."""
    seen: dict[str, str] = {}
    for name in concepts:
        if name.strip():
            seen.setdefault(concept_key(name), name.strip())
    return list(seen.values())


def _weakest(names: list[str], known: dict[str, float], limit: int) -> list[str]:
    """The ``limit`` lowest-scoring names (unknown counts as 0), still in
    their original order. With no scores this is the first ``limit``."""
    if len(names) <= limit:
        return names
    keep = sorted(range(len(names)), key=lambda i: known.get(concept_key(names[i]), 0.0))[:limit]
    return [names[i] for i in sorted(keep)]


def _tier(score: float | None) -> Tier:
    return "unexplored" if score is None else get_mastery_tier(score)


def plan_sections(
    concepts: list[str], scores: dict[str, float], *, depth: Depth, use_history: bool,
) -> list[PlanSection]:
    """One planned section per concept of the chosen materials.

    ``concepts`` is the materials' concept names in order; ``scores`` is the
    student's mastery per concept name. Past the depth's section count, the
    weakest concepts are kept with history on and the first ones with it off.
    A concept the tree does not have, and every concept with history off, is
    ``unexplored``.
    """
    known = {concept_key(name): score for name, score in scores.items()} if use_history else {}
    names = _weakest(_distinct(concepts), known, SECTION_COUNT[depth])
    section_tiers = [_tier(known.get(concept_key(name))) for name in names]
    shares = weights(section_tiers, use_history=use_history)
    return [
        PlanSection(title=name, tier=tier, weight=share)
        for name, tier, share in zip(names, section_tiers, shares)
    ]


async def aplan(user_id: str, request: GuideRequest) -> GuidePlan:
    """The planned outline for the modal's choices. No materials chosen gives
    an empty plan; a class the student is not in is ``GuideNotFound``."""
    offering_id = await aresolve_offering(user_id, request.course_id, request.semester)
    concepts = await aload_concepts(user_id, offering_id, request.material_ids)
    use_history = request.use_history
    scores = await amastery(user_id, request.course_id) if use_history and concepts else {}
    sections = plan_sections(concepts, scores, depth=request.depth, use_history=use_history)
    return GuidePlan(
        sections=sections, minutes=len(sections) * MINUTES_PER_SECTION[request.depth],
    )
