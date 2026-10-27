"""Study-roadmap logic: hierarchy, ordering, freshness, readiness.

The roadmap is a PROJECTION of the knowledge graph, not a second store
(`.plans/course-study-roadmap-spec.md` §3.1). A topic is a `graph_nodes` row
with `part_of` children; a subtopic is such a child; anything in neither
position is "unfiled". Mastery stays on the node, so there is nothing here
that can drift out of sync with `/tree`.

Everything in this module is a PURE function over already-fetched rows. No
`table()` calls, no clock reads that aren't passed in, no imports from
routes. That is deliberate:

  * the ordering, freshness, and readiness rules are the part of the feature
    most likely to be wrong, and this shape lets them be tested exhaustively
    without a database or a stack;
  * the route layer stays a thin fetch-then-shape wrapper, so the frontend
    never re-derives any of it (two implementations of the readiness formula
    would be two chances to disagree with the "why?" panel).

The two numbers this module computes are deliberately SEPARATE channels and
must not be conflated (§3.5/§11):

    mastery_score   "do you know it"          written only by scored quizzes;
                                              falls on evidence, never on time
    freshness       "how recently proved it"  derived here, stored nowhere;
                                              falls with time, never persisted

`readiness` multiplies them. Nothing in this module ever returns a mastery
value to be written back.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable

from config import get_mastery_tier, is_mastered

logger = logging.getLogger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
#
# Freshness floor. A subtopic the student has not revisited never contributes
# LESS than 60% of its earned mastery to readiness. The floor exists because
# forgetting is partial: someone who genuinely mastered a concept a month ago
# is not back to zero, and a model that said so would make the ring useless
# the moment a student took a week off.
FRESHNESS_FLOOR = 0.6

# How much of the readiness contribution time can take away: 1.0 - FLOOR.
_FRESHNESS_RANGE = 1.0 - FRESHNESS_FLOOR

# A subtopic is flagged "needs review" once it is half-stale — i.e. the time
# since the student last PROVED it is at least half the time remaining before
# the exam. Expressed as a ratio rather than a day count so it scales: 10 days
# cold is fine for a final in May and alarming for a midterm on Friday.
STALE_AT = 0.5

# Relationship types that impose an order between two nodes. `related` does
# not — it is symmetric and carries no sequencing claim.
ORDERING_EDGES = ("prerequisite", "builds_on")

# The edge that builds the hierarchy itself.
HIERARCHY_EDGE = "part_of"


# ── Hierarchy ───────────────────────────────────────────────────────────────


def _edge_pairs(edges: Iterable[dict], types: tuple[str, ...] | str) -> list[tuple[str, str]]:
    """(source, target) for every edge whose relationship_type is wanted.

    Tolerates rows missing either endpoint rather than raising: a half-written
    edge should degrade the ordering, not take the page down.
    """
    wanted = (types,) if isinstance(types, str) else types
    pairs: list[tuple[str, str]] = []
    for e in edges:
        if e.get("relationship_type") not in wanted:
            continue
        source, target = e.get("source_node_id"), e.get("target_node_id")
        if not source or not target or source == target:
            continue
        pairs.append((source, target))
    return pairs


def build_hierarchy(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """Split a course's nodes into topics-with-children and unfiled concepts.

    `part_of` reads child -> parent: the edge (source=Mitochondria,
    target=Cell Structure) means Mitochondria is PART OF Cell Structure.

    Returns ``{"topics": [{"node": row, "subtopics": [row, ...]}, ...],
    "unfiled": [row, ...]}`` — both lists unordered; `order_roadmap` sorts.

    Three shapes a caller must expect, all of which occur in real graphs:

      * A node that is a parent -> a topic.
      * A node that is a child -> a subtopic of its parent. A child claimed by
        more than one parent is filed under ONE of them (first by parent id,
        for determinism) rather than duplicated, because a subtopic appearing
        twice would be counted twice by `readiness`.
      * A node in neither position -> unfiled. These are NOT dropped (§3.1):
        the page renders them in their own group, so no concept can become
        invisible just because nothing has grouped it yet.
    """
    by_id = {n["id"]: n for n in nodes if n.get("id")}
    parent_of: dict[str, str] = {}
    children: dict[str, list[str]] = {}

    for child, parent in sorted(_edge_pairs(edges, HIERARCHY_EDGE)):
        # Both endpoints must be nodes we were given. An edge pointing out of
        # the course (or at a deleted row) is ignored, not an error.
        if child not in by_id or parent not in by_id:
            continue
        if child in parent_of:
            # Already filed under an earlier parent. Sorting the pairs above
            # makes "earlier" stable across calls.
            continue
        parent_of[child] = parent
        children.setdefault(parent, []).append(child)

    topics = [
        {"node": by_id[pid], "subtopics": [by_id[cid] for cid in kids]}
        for pid, kids in children.items()
        # A node that is both someone's parent and someone else's child is
        # treated as a topic: it owns children, which is what the page needs
        # to render. Its own parent link is ignored rather than nesting two
        # deep, because the layout is two levels by design (§4).
    ]

    filed = set(parent_of) | set(children)
    unfiled = [n for nid, n in by_id.items() if nid not in filed]

    return {"topics": topics, "unfiled": unfiled}


# ── Ordering ────────────────────────────────────────────────────────────────


def _tie_break_key(node: dict) -> tuple[str, str]:
    """Stable order for nodes no prerequisite edge separates (§3.2).

    created_at first (the order the student met the material), then
    concept_name. Both coerced to str so a missing created_at sorts
    consistently instead of raising on a None comparison.
    """
    return (str(node.get("created_at") or ""), str(node.get("concept_name") or ""))


def topological_order(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], set[str]]:
    """Kahn's algorithm over `prerequisite` / `builds_on`, tie-broken stably.

    An ordering edge reads source -> target as "source comes first".

    Returns ``(ordered_nodes, cycle_ids)``. **This never raises on a cycle.**
    A knowledge graph assembled by an LLM will eventually contain "A requires
    B requires A", and a page that 500s because of it would be worse than one
    that shows a slightly odd order. Nodes still blocked when the algorithm
    stalls are appended in tie-break order and reported in `cycle_ids` so the
    UI can mark them.

    With no ordering edges at all — the common case on a freshly extracted
    graph — this degrades to a pure tie-break sort, which is stable across
    loads. That matters: a list that reshuffles between visits loses the
    student's place.
    """
    by_id = {n["id"]: n for n in nodes if n.get("id")}
    if not by_id:
        return [], set()

    # indegree[x] = how many nodes must come before x.
    indegree = {nid: 0 for nid in by_id}
    successors: dict[str, list[str]] = {nid: [] for nid in by_id}

    seen_pairs: set[tuple[str, str]] = set()
    for first, then in _edge_pairs(edges, ORDERING_EDGES):
        if first not in by_id or then not in by_id:
            continue
        # `prerequisite` and `builds_on` can both relate the same pair; they
        # are distinct rows under the table's UNIQUE but one constraint here.
        if (first, then) in seen_pairs:
            continue
        seen_pairs.add((first, then))
        successors[first].append(then)
        indegree[then] += 1

    ready = sorted(
        (nid for nid, deg in indegree.items() if deg == 0),
        key=lambda nid: _tie_break_key(by_id[nid]),
    )

    ordered: list[dict] = []
    while ready:
        nid = ready.pop(0)
        ordered.append(by_id[nid])
        newly_free = []
        for succ in successors[nid]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                newly_free.append(succ)
        if newly_free:
            # Re-sort rather than append: the frontier must stay in tie-break
            # order or two runs over the same data could differ.
            ready = sorted(
                ready + newly_free,
                key=lambda n: _tie_break_key(by_id[n]),
            )

    placed = {n["id"] for n in ordered}
    cycle_ids = set(by_id) - placed
    if cycle_ids:
        logger.info(
            "roadmap: %d node(s) in a prerequisite cycle — appending in tie-break order",
            len(cycle_ids),
        )
        ordered.extend(sorted((by_id[nid] for nid in cycle_ids), key=_tie_break_key))

    return ordered, cycle_ids


def order_roadmap(hierarchy: dict[str, Any], edges: list[dict]) -> dict[str, Any]:
    """Order topics against each other, and subtopics within each topic.

    Subtopics are sorted by the same rule scoped to their siblings, so a
    prerequisite between two concepts inside one topic is honoured without
    letting it reorder the topics themselves.
    """
    topic_nodes = [t["node"] for t in hierarchy["topics"]]
    ordered_topics, topic_cycles = topological_order(topic_nodes, edges)
    by_topic_id = {t["node"]["id"]: t for t in hierarchy["topics"]}

    out_topics = []
    cycles = set(topic_cycles)
    for node in ordered_topics:
        entry = by_topic_id[node["id"]]
        subs, sub_cycles = topological_order(entry["subtopics"], edges)
        cycles |= sub_cycles
        out_topics.append({"node": node, "subtopics": subs})

    unfiled, unfiled_cycles = topological_order(hierarchy["unfiled"], edges)
    cycles |= unfiled_cycles

    return {"topics": out_topics, "unfiled": unfiled, "cycle_node_ids": cycles}


def start_here_id(ordered_topics: list[dict]) -> str | None:
    """The first topic in order that is not fully mastered (§3.2).

    None when every topic is mastered — the page shows a finished state rather
    than pointing at something already done.
    """
    for topic in ordered_topics:
        subs = topic["subtopics"] or [topic["node"]]
        if not all(is_mastered(s.get("mastery_score") or 0.0) for s in subs):
            return topic["node"]["id"]
    return None


# ── Freshness ───────────────────────────────────────────────────────────────


def _as_date(value: Any) -> date | None:
    """Coerce a date / datetime / ISO string to a date. None on anything else.

    PostgREST hands back ISO strings, tests hand back date objects, and a
    missing column hands back None — all three reach this module.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        # fromisoformat handles both "2026-10-27" and a full timestamp; the
        # trailing Z that PostgREST sometimes emits is not accepted natively.
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            logger.debug("roadmap: unparseable date %r", value)
            return None


def freshness(
    last_correct_at: Any,
    exam_date: Any,
    *,
    today: date | None = None,
) -> tuple[float, bool]:
    """How much of a subtopic's earned mastery still counts, and is it stale.

    Returns ``(factor, is_stale)`` where factor is in [FRESHNESS_FLOOR, 1.0].

    Freshness is EXAM-RELATIVE (§3.7): the same subtopic can be stale for
    Friday's midterm and fresh for June's final, because staleness is about
    whether you will still have it when you need it, not about the calendar.

        d = days since the last CORRECT answer   (a wrong answer does not
                                                  reset the clock — being
                                                  reminded you're wrong is
                                                  not evidence you now know)
        D = days until the exam, floored at 1
        staleness = clamp(d / D, 0, 1)
        factor    = 1 - (1 - FLOOR) * staleness

    With no exam there is no deadline to be stale against, so this returns
    (1.0, False) and the ring reports pure mastery. A student with no exam
    recorded is not told their knowledge is rotting on a schedule we invented.

    Never having answered correctly also returns (1.0, False): such a subtopic
    has mastery 0 from the only writer that matters, so discounting it further
    would be double-counting the same absence of evidence.
    """
    exam = _as_date(exam_date)
    if exam is None:
        return 1.0, False

    last = _as_date(last_correct_at)
    if last is None:
        return 1.0, False

    now = today or datetime.now(timezone.utc).date()
    days_cold = max(0, (now - last).days)
    days_left = max(1, (exam - now).days)

    staleness = min(1.0, days_cold / days_left)
    return 1.0 - _FRESHNESS_RANGE * staleness, staleness >= STALE_AT


# ── Readiness ───────────────────────────────────────────────────────────────


def subtopic_readiness(
    node: dict,
    *,
    last_correct_at: Any = None,
    exam_date: Any = None,
    weight: float | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """One row of the readiness breakdown: the factors and their product.

    Everything the "why?" panel prints comes from here, so the panel can never
    show a number the formula didn't produce.
    """
    mastery = float(node.get("mastery_score") or 0.0)
    factor, stale = freshness(last_correct_at, exam_date, today=today)
    w = 1.0 if weight is None else float(weight)
    return {
        "node_id": node.get("id"),
        "concept_name": node.get("concept_name"),
        "mastery": mastery,
        "tier": node.get("mastery_tier") or get_mastery_tier(mastery),
        "freshness": factor,
        "is_stale": stale,
        "weight": w,
        "contribution": w * mastery * factor,
    }


def readiness(rows: list[dict]) -> float:
    """Weighted mean of per-subtopic readiness (§3.6).

        readiness = Σ(wᵢ · mᵢ · fᵢ) / Σ wᵢ

    `rows` are `subtopic_readiness` results. An empty scope returns 0.0 rather
    than raising or returning 1.0: a student with nothing in scope is not
    ready, and claiming otherwise would be the most damaging possible lie for
    this number to tell.
    """
    total_weight = sum(r["weight"] for r in rows)
    if total_weight <= 0:
        return 0.0
    return sum(r["contribution"] for r in rows) / total_weight


def topic_summary(subtopic_rows: list[dict]) -> dict[str, Any]:
    """Counts for a topic's bar and label (§3.6).

    COUNTS, never an average. The segmented bar draws one segment per
    subtopic, so a topic-level average would be a second, differently-computed
    number sitting next to the segments it disagrees with.
    """
    total = len(subtopic_rows)
    mastered = sum(1 for r in subtopic_rows if is_mastered(r["mastery"]))
    return {
        "total": total,
        "mastered": mastered,
        "stale": sum(1 for r in subtopic_rows if r["is_stale"]),
        "started": sum(1 for r in subtopic_rows if r["mastery"] > 0),
        "readiness": readiness(subtopic_rows),
    }
