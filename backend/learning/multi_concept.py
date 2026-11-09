"""Multi-concept items: identity, combinations, the serving gate and the
session rule (learning-loop spec §13 A141, flag `multi_concept_items`).

Pure: stdlib and learning.params; listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

What one is. An item that combines its APEX concept with one or two of the
apex's DIRECT prerequisites (a `prerequisite` graph edge into the apex,
EDGE_PREREQ_SOURCE_IS_PREREQ): an integrative item of the apex that also
exercises the ideas it builds on — the "how many ideas a problem combines"
dial of adaptive practice. Only prerequisite edges make a combination: the
other relation the loop reads from stored data, siblings sharing a parent
(A114), is confusability — the interleave's business — and names no apex.

Identity. A multi-concept item is a check_items row whose `concept_key` is
its components' concept keys joined by SEP (the apex first, then the
prerequisites in key order) and whose `apex_key` / `component_keys` columns
say the same. graph_service._normalize_concept never yields SEP (str.split()
treats it as whitespace), so no concept's key — and so no per-concept read,
picker, reserve or post-test — ever meets one: only the multi-concept picker
serves them, and never as a post-test reserve.

Evidence (decided in spec §13 A141): the answer is ONE observation on the
apex node, on the item's channel, at WEIGHT_MULTI_CONCEPT
(learning.evidence.evidence_weight); the other components are reached only by
§3.1's existing one-hop propagation, which credits a dependent's
prerequisites on a correct answer and blames none on a wrong one.

The gate: every component at least proficient — decayed p_known >=
MULTI_CONCEPT_GATE_P (BKT_PROFICIENT, the planner's prerequisite-readiness
cut) with >= MULTI_CONCEPT_GATE_MIN_STRONG strong-channel unassisted
observations (A110 (c)). At that level the conjunctive success expectation of
two or three components (DINA: p^k(1-S) + (1-p^k)G) stays inside the practice
band the A122 controller holds (0.65-0.85); at the profic band's floor (0.80)
it does not (0.61 for two, 0.50 for three).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations as _pairs
from typing import NamedTuple

from learning.params import (
    MULTI_CONCEPT_COMBOS_PER_APEX,
    MULTI_CONCEPT_COMBOS_PER_DOC,
    MULTI_CONCEPT_GATE_MIN_STRONG,
    MULTI_CONCEPT_GATE_P,
    MULTI_CONCEPT_MAX_COMPONENTS,
    MULTI_CONCEPT_MIN_COMPONENTS,
    MULTI_CONCEPT_PER_CONCEPT_SESSION,
)

#: The separator of a multi-concept item's concept_key (ASCII unit separator).
SEP = "\x1f"
#: How a combination is named to the drafter (the model copies it into `concept`).
LABEL_JOIN = " + "
#: The loop-state step key that marks a posed multi-concept item.
STEP_KEY = "multi_concept"


def combo_key(components: Sequence[str]) -> str:
    """The concept_key of a combination: the apex first, the prerequisites in
    key order. ValueError for anything that is not 2..3 distinct, non-empty
    concept keys free of SEP."""
    comps = [str(c) for c in components]
    if not MULTI_CONCEPT_MIN_COMPONENTS <= len(comps) <= MULTI_CONCEPT_MAX_COMPONENTS:
        raise ValueError(f"a combination has {len(comps)} components")
    if any(not c or SEP in c for c in comps) or len(set(comps)) != len(comps):
        raise ValueError("a combination's components are distinct concept keys")
    return SEP.join([comps[0], *sorted(comps[1:])])


def components_of(concept_key) -> tuple[str, ...] | None:
    """A multi-concept item's components (the apex first), or None for a
    single-concept key."""
    if not isinstance(concept_key, str) or SEP not in concept_key:
        return None
    parts = tuple(concept_key.split(SEP))
    if not MULTI_CONCEPT_MIN_COMPONENTS <= len(parts) <= MULTI_CONCEPT_MAX_COMPONENTS:
        return None
    if any(not p for p in parts) or len(set(parts)) != len(parts):
        return None
    return parts


def concept_key_of(name) -> str:
    """A concept's key from its node's name: graph_service._normalize_concept's
    rule (whitespace runs collapse to one space, then casefold; a test pins the
    two equal), so the stored check items' keys and a node's name meet. "" for
    no name."""
    return " ".join(str(name or "").split()).casefold()


def is_multi_concept(item) -> bool:
    return components_of(getattr(item, "concept_key", None)) is not None


def isomorph_class(format, difficulty, concept_key) -> tuple:
    """A76's isomorph class of an item on a node: (format, difficulty) — and,
    for a multi-concept item, its combination key too (spec §13 A141). Every
    item on a node shares the node's concept, so a single-concept item's class
    is exactly the pair it always was; a combination measures another
    construct, so a release of one never makes a single-concept item of the
    same format and difficulty a re-check, nor the reverse, nor one
    combination another's."""
    if components_of(concept_key) is None:
        return (format, difficulty)
    return (format, difficulty, concept_key)


def evidence_key(item) -> str | None:
    """The concept key an item's evidence is recorded under: a multi-concept
    item's apex, any other item's own concept_key."""
    comps = components_of(getattr(item, "concept_key", None))
    return comps[0] if comps else getattr(item, "concept_key", None)


def label(names: Sequence[str]) -> str:
    """The combination's name as the drafter reads it ("Apex + Prerequisite")."""
    return LABEL_JOIN.join(" ".join(str(n).split()) for n in names)


def combinations(
    apexes: Sequence[str],
    parents: Mapping[str, Iterable[str]],
    *,
    per_apex: int = MULTI_CONCEPT_COMBOS_PER_APEX,
    limit: int = MULTI_CONCEPT_COMBOS_PER_DOC,
) -> list[tuple[str, ...]]:
    """The combinations to draft: for each apex in the given order (the
    document's concepts, extraction order), its pairs with each direct
    prerequisite parent (key order), then its triples (two parents, key
    order), at most `per_apex` per apex and `limit` in all — two ideas before
    three, the order the dial moves in. Keys only; an apex is never its own
    parent; an apex listed twice counts once."""
    out: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for apex in apexes:
        if not apex or apex in seen or len(out) >= limit:
            continue
        seen.add(apex)
        prereqs = sorted({p for p in parents.get(apex, ()) if p and p != apex})
        mine = [(apex, p) for p in prereqs]
        if MULTI_CONCEPT_MAX_COMPONENTS >= 3:
            mine += [(apex, a, b) for a, b in _pairs(prereqs, 2)]
        out.extend(mine[: max(0, min(per_apex, limit - len(out)))])
    return out


class ComponentState(NamedTuple):
    p_known: float  # decayed
    n_strong_unassisted: int


def gate_open(states: Mapping[str, ComponentState | None], components: Iterable[str]) -> bool:
    """Every component at least proficient (module docstring). A component
    the student has no node or no state for is not proficient."""
    for key in components:
        st = states.get(key)
        if st is None:
            return False
        if (
            st.p_known < MULTI_CONCEPT_GATE_P
            or st.n_strong_unassisted < MULTI_CONCEPT_GATE_MIN_STRONG
        ):
            return False
    return True


def posed_on(steps: Mapping, node_id: str) -> int:
    """Multi-concept items posed on `node_id` in this session (loop-state steps)."""
    return sum(
        1
        for entry in (steps or {}).values()
        if isinstance(entry, dict)
        and entry.get("node_id") == node_id
        and entry.get(STEP_KEY) is True
    )


def graded_on(steps: Mapping, node_id: str) -> int:
    """Checks graded on `node_id` in this session (loop-state steps)."""
    return sum(
        1
        for entry in (steps or {}).values()
        if isinstance(entry, dict)
        and entry.get("node_id") == node_id
        and entry.get("graded_at") is not None
    )


def dial_open(steps: Mapping, node_id: str, *, at_top: bool, goal: bool) -> bool:
    """Whether the concept's next item may be a multi-concept one this session
    (spec §13 A141, the A122 controller's consistency): never in a goal
    session; only as the concept's next item after a check graded on it this
    session (the controller has decided from it); only while the concept's
    target difficulty is the top one (no easier step pending); and at most
    MULTI_CONCEPT_PER_CONCEPT_SESSION times a session."""
    if goal or not at_top:
        return False
    if graded_on(steps, node_id) < 1:
        return False
    return posed_on(steps, node_id) < MULTI_CONCEPT_PER_CONCEPT_SESSION
