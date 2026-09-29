"""Planner (spec §3.4 PLAN_*; research §Plan). Pure over an in-memory graph.

outer_fringe: KST's "ready to learn" set — not proficient, every prerequisite
proficient. plan: PLAN_ORDER sections (due reviews → new material → interleaved
siblings) with the coupled cap. Edges arrive ALREADY oriented as (prerequisite,
dependent); the route applies EDGE_PREREQ_SOURCE_IS_PREREQ.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from learning.params import BKT_PROFICIENT, PLAN_MAX_CONCEPTS, PLAN_MAX_COUPLED, PLAN_ORDER

PlanKind = Literal["review", "new", "sibling"]

# PLAN_ORDER section name -> the kind its entries carry. Keyed by name, not by
# position, so reordering PLAN_ORDER reorders the plan without mislabelling it.
_SECTION_KIND: dict[str, PlanKind] = {
    "due_reviews": "review",
    "new_material": "new",
    "interleaved_siblings": "sibling",
}
if set(_SECTION_KIND) != set(PLAN_ORDER):
    raise ValueError(f"PLAN_ORDER {PLAN_ORDER} does not name the planner's sections")


@dataclass(frozen=True)
class PlanConcept:
    node_id: str
    kind: PlanKind


@dataclass(frozen=True)
class Plan:
    concepts: tuple[PlanConcept, ...]
    order: tuple[str, ...] = tuple(PLAN_ORDER)


def outer_fringe(states: dict[str, float], prereq_edges: Iterable[tuple[str, str]]) -> list[str]:
    """Every node below BKT_PROFICIENT whose prerequisites are all proficient (no
    prerequisites qualifies), by p descending then node_id. Edges with an endpoint
    outside `states`, and self-loops, are dropped."""
    prereqs: dict[str, set[str]] = defaultdict(set)
    for prereq, dependent in prereq_edges:
        if prereq == dependent or prereq not in states or dependent not in states:
            continue
        prereqs[dependent].add(prereq)
    fringe = [
        n
        for n, p in states.items()
        if p < BKT_PROFICIENT and all(states[q] >= BKT_PROFICIENT for q in prereqs[n])
    ]
    return sorted(fringe, key=lambda n: (-states[n], n))


def plan(
    fringe: Sequence[str],
    due_reviews: Sequence[str],
    siblings_fn: Callable[[str], Sequence[str]],
    goal_filter: Callable[[str], bool] | None,
    *,
    proficient: frozenset[str] = frozenset(),
    max_concepts: int = PLAN_MAX_CONCEPTS,
    max_coupled: int = PLAN_MAX_COUPLED,
) -> Plan:
    """Reviews (deduplicated, filtered, uncapped — budget_select caps them
    upstream), then new fringe concepts (≤ max_concepts; a candidate already
    sharing a parent with ≥ max_coupled chosen new concepts is skipped), then at
    most one proficient sibling per new concept. goal_filter=None keeps all."""
    keep = goal_filter or (lambda _n: True)

    reviews: list[str] = []
    for n in due_reviews:
        if n not in reviews and keep(n):
            reviews.append(n)

    new: list[str] = []
    for n in fringe:
        if len(new) >= max_concepts:
            break
        if n in reviews or n in new or not keep(n):
            continue
        sibs = set(siblings_fn(n))
        if sum(1 for c in new if c in sibs) >= max_coupled:
            continue
        new.append(n)

    taken = set(reviews) | set(new)
    siblings: list[str] = []
    for n in new:
        for s in siblings_fn(n):
            if s in proficient and s not in taken:
                siblings.append(s)
                taken.add(s)
                break

    by_kind: dict[PlanKind, list[str]] = {"review": reviews, "new": new, "sibling": siblings}
    concepts = tuple(
        PlanConcept(n, _SECTION_KIND[section])
        for section in PLAN_ORDER
        for n in by_kind[_SECTION_KIND[section]]
    )
    return Plan(concepts, tuple(PLAN_ORDER))
