"""Planner (spec §3.4 PLAN_*; research §Plan). Pure over an in-memory graph.

outer_fringe: KST's "ready to learn" set — not proficient, every prerequisite
proficient. plan: PLAN_ORDER sections (due reviews → new material → interleaved
siblings) with the coupled cap. Edges arrive ALREADY oriented as (prerequisite,
dependent); the route applies EDGE_PREREQ_SOURCE_IS_PREREQ.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from learning.params import (
    BKT_PROFICIENT,
    CHANNELS,
    LADDER_MAX_RUNG,
    PLAN_MAX_CONCEPTS,
    PLAN_MAX_COUPLED,
    PLAN_ORDER,
    PROBE_DIFFICULTY_SHIFT,
)
from learning.probe import independent_observations

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


def _valid_planning_miss(observation: Mapping) -> bool:
    """A real failed check is a practice need, even after help or a release.

    This does not certify an independent diagnostic ceiling. Saved metadata is
    untrusted JSON: outages, synthetic refusal-to-IDK and malformed verdicts
    must not create a learner failure. Previously exposed/replayed items also
    cannot create a new need after fresh recovery.
    """
    correct, idk = observation.get("correct"), observation.get("idk", False)
    channel, difficulty = observation.get("channel"), observation.get("difficulty")
    rung = observation.get("max_rung", 0)
    refused = observation.get("refused", False)
    return (
        type(correct) is bool
        and type(idk) is bool
        and (idk or not correct)
        and isinstance(channel, str)
        and channel in CHANNELS
        and type(difficulty) is int
        and difficulty in PROBE_DIFFICULTY_SHIFT
        and type(observation.get("independent")) is bool
        and type(rung) is int
        and 0 <= rung <= LADDER_MAX_RUNG
        and type(observation.get("same_session_recheck", False)) is bool
        and type(observation.get("assisted", False)) is bool
        and observation.get("unavailable", False) is False
        and observation.get("graded", True) is True
        and (refused is False or refused is None or refused == "")
        and observation.get("synthetic_idk", False) is False
        and observation.get("previously_seen", False) is False
    )


def planning_states(states: dict[str, float], observations: Sequence[dict]) -> dict[str, float]:
    """Local planning needs, without changing a stored mastery posterior.

    A valid graded miss, including one after help or a release, cannot be
    erased by an old high posterior, help, a repeated item or an easier floor
    confirmation. Only a later fresh unaided success at the missed level or
    above resolves that need. Assisted misses remain excluded from diagnosis.
    Observation order is causal (diagnosis first, then graded teaching checks).
    """
    failed: dict[str, set[int]] = defaultdict(set)
    independent = {id(observation) for observation in independent_observations(observations)}
    seen: set[str] = set()
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        question_hash = observation.get("question_hash")
        if not isinstance(question_hash, str) or not question_hash.strip() or question_hash in seen:
            continue
        seen.add(question_hash)
        node = observation.get("node_id")
        if not isinstance(node, str) or node not in states:
            continue
        if (
            id(observation) in independent
            and observation["correct"]
            and not observation.get("idk", False)
            and observation.get("assisted", False) is False
        ):
            difficulty = observation["difficulty"]
            failed[node].difference_update(d for d in tuple(failed[node]) if d <= difficulty)
        elif _valid_planning_miss(observation):
            failed[node].add(observation["difficulty"])
    result = dict(states)
    for node, levels in failed.items():
        if levels:
            result[node] = min(result[node], BKT_PROFICIENT - 0.01)
    return result


def goal_scope(
    target_node_ids: Iterable[str],
    prereq_edges: Iterable[tuple[str, str]],
    *,
    nodes: Iterable[str],
) -> frozenset[str]:
    """Valid targets plus all their transitive valid prerequisites.

    Edges point prerequisite -> dependent, as for outer_fringe. Invalid graph
    endpoints cannot bridge into unrelated content. A visited set handles cycles;
    descendants and disconnected strands stay outside the selected goal.
    """
    valid = set(nodes)
    prerequisites: dict[str, set[str]] = defaultdict(set)
    for prerequisite, dependent in prereq_edges:
        if prerequisite in valid and dependent in valid:
            prerequisites[dependent].add(prerequisite)
    scope = set(target_node_ids) & valid
    pending = list(scope)
    while pending:
        for prerequisite in prerequisites[pending.pop()]:
            if prerequisite not in scope:
                scope.add(prerequisite)
                pending.append(prerequisite)
    return frozenset(scope)


def _components(nodes: Sequence[str], prereqs: dict[str, set[str]]) -> dict[str, int]:
    """node -> strongly-connected-component id over the prerequisite graph
    (iterative Tarjan; deterministic over the sorted node list)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    comp: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(prereqs[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, edges = work[-1]
            advanced = False
            for nxt in edges:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(prereqs[nxt]))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp[member] = index[node]
                    if member == node:
                        break
    return comp


def prerequisite_ready(
    states: dict[str, float],
    prereq_edges: Iterable[tuple[str, str]],
    *,
    transitive: bool = False,
) -> frozenset[str]:
    """Nodes whose external-SCC direct prerequisites are all proficient.

    Readiness applies even to an already-proficient node: an advanced goal
    review must not bypass a missing prerequisite merely because its own old
    posterior is high. Cycles are one component, blocked only by prerequisites
    outside that component. Foreign endpoints and self-loops are ignored.

    Explicit goals can set transitive=True: every weak ancestor component
    blocks its descendants, even if an intermediate node's old posterior is
    high. A component's own weak members do not block that component itself.
    The default keeps course-wide direct-readiness behavior unchanged.
    """
    prereqs: dict[str, set[str]] = defaultdict(set)
    for prereq, dependent in prereq_edges:
        if prereq == dependent or prereq not in states or dependent not in states:
            continue
        prereqs[dependent].add(prereq)
    comp = _components(sorted(states), prereqs)
    members: dict[int, list[str]] = defaultdict(list)
    for n, c in comp.items():
        members[c].append(n)

    if transitive:
        dependents: dict[int, set[int]] = defaultdict(set)
        for dependent, prerequisites in prereqs.items():
            for prerequisite in prerequisites:
                if comp[prerequisite] != comp[dependent]:
                    dependents[comp[prerequisite]].add(comp[dependent])
        weak = {comp[n] for n, p in states.items() if p < BKT_PROFICIENT}
        pending = [child for parent in weak for child in dependents[parent]]
        blocked: set[int] = set()
        while pending:
            component = pending.pop()
            if component not in blocked:
                blocked.add(component)
                pending.extend(dependents[component])
        return frozenset(n for n in states if comp[n] not in blocked)

    def ready(n: str) -> bool:
        outside = {q for m in members[comp[n]] for q in prereqs[m] if comp[q] != comp[n]}
        return all(states[q] >= BKT_PROFICIENT for q in outside)

    return frozenset(n for n in states if ready(n))


def outer_fringe(states: dict[str, float], prereq_edges: Iterable[tuple[str, str]]) -> list[str]:
    """Ready nodes below proficiency, by p descending then node_id."""
    ready = prerequisite_ready(states, prereq_edges)
    fringe = [n for n, p in states.items() if p < BKT_PROFICIENT and n in ready]
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
            if s in proficient and s not in taken and keep(s):
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
