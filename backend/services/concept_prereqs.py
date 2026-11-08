"""Prerequisite edges from document uploads (spec §13 A118).

Before A118 an upload wrote concept NODES only, all hanging off the course
node: a 10-slide hash-tables deck became nine nodes and zero `graph_edges`, so
every prerequisite consumer was inert for an upload-built graph — one-hop
evidence propagation (spec §3.1), the "prerequisite proficient / not known"
policy bands and wheelspin prerequisite repair, the novice exit to the lowest
prerequisite, and the planner's KST outer fringe (learning/planner.py), which
then ordered the deck's concepts by node id.

The concept extraction agent (agents/concept_extraction.py) now also names
direct (prerequisite, dependent) relations between the concepts it extracted
and, optionally, the course's existing concepts (listed in its message by
`course_concept_names`). Nothing the model sends is trusted as an identity or
a bound: `resolve_prerequisites` applies the rules below in code, and
`write_document_prerequisites` writes what survives through
services/graph_service.py::apply_graph_update as `prerequisite` edges oriented
by learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ — the direction propagation,
`_prereq_proficient` and the planner read. Only the WRITE is gated, by the
`upload_prereq_edges` flag; the extraction always carries the relations.

Resolution rules (pure, deterministic):

1. Scope. Both names must resolve — case- and whitespace-insensitively, the
   graph's own dedup rule — to concepts of this student's course graph as it
   stands at write time (after the upload's nodes were merged; a subject-root
   node is never an endpoint). Otherwise: dropped, ``unknown``.
2. No self-loops: both names resolve to the same concept → ``self_loop``.
3. The document rule: at least one endpoint must be one of THIS document's
   extracted concepts, since the document is the evidence for the relation; a
   relation between two concepts it did not extract → ``off_document``.
4. A repeated (prerequisite, dependent) pair → ``duplicate``.
5. An edge the course graph already has is a no-op (``already_present``), never
   rewritten: the edge upsert merges on conflict, which would replace the
   row's id and strength on every re-upload. That is what makes a re-upload
   write nothing.
6. Cycle break. The candidates are ranked in one canonical order —
   prerequisite first, then dependent, each ranked: a concept the course
   already had (not in this document) before this document's concepts, these
   by extraction importance descending, ties by normalized name — so the
   result depends on the SET of relations, never on the order the model listed
   them. They are admitted greedily against the course's existing prerequisite
   edges; one whose dependent already reaches its prerequisite would close a
   cycle → ``cycle``. Existing edges therefore always win over a new
   contradiction, and within one document the more foundational concept stays
   the prerequisite.
7. Transitive reduction. An admitted edge whose dependent is still reachable
   without it (through admitted or existing edges) → ``redundant``. Prerequisite
   edges mean DIRECT prerequisites: propagation is one hop, and the planner's
   siblings are concepts sharing a direct parent, so a shortcut A->C beside
   A->B->C would make B and C false siblings and C a one-hop target of A.
   Checked lowest rank first, removing only while another path remains, so
   reachability never changes.
8. Cap: at most MAX_PREREQ_EDGES_PER_DOCUMENT new edges per document, the
   highest-ranked kept → ``cap``.

Every drop is logged (WARNING, with a bounded sample of the names); the model
never sees a rejection, so a bad relation costs nothing but the log line.

Concurrency: the read → resolve → write runs under a per-(student, course)
lock stripe, so two documents uploaded together (the upload modal runs files
in parallel) cannot each pass the cycle check and close a cycle between them.
The lock is per process (backend/Dockerfile runs one uvicorn worker); a race
across processes (a deploy's overlap window, a second replica) can still close
one, and the planner then treats the cycle as one strongly connected
component, as it does for a cycle from any edge writer.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.concept_extraction import EXISTING_CONCEPTS_PROMPT_MAX
from db.connection import page_all, table
from learning.evidence import PREREQ_RELATIONSHIP_TYPE
from learning.params import EDGE_PREREQ_SOURCE_IS_PREREQ
from services.feature_flags import flag_on
from services.graph_service import _normalize_concept, apply_graph_update

if TYPE_CHECKING:
    from agents.concept_extraction import ConceptList

logger = logging.getLogger(__name__)

#: The flag that gates the edge WRITE (services/feature_flags.py::REGISTRY).
UPLOAD_PREREQ_EDGES_FLAG = "upload_prereq_edges"

#: † At most this many NEW prerequisite edges per document (rule 8). A typical
#: lecture's direct prerequisites number about one per concept, and the
#: extraction caps concepts at 30; this bounds a runaway output, not a normal one.
MAX_PREREQ_EDGES_PER_DOCUMENT = 30

#: † The strength an upload edge is written at. Display weight only: no
#: learning-loop reader (propagation, bands, planner) reads strength; the graph
#: view and the tutor's graph tool show it. Below the seeds' hand-authored 0.9,
#: because a model inferred it.
UPLOAD_PREREQ_STRENGTH = 0.5

# Drop reasons (rules 1–4 and 6–8).
UNKNOWN = "unknown"
SELF_LOOP = "self_loop"
OFF_DOCUMENT = "off_document"
DUPLICATE = "duplicate"
CYCLE = "cycle"
REDUNDANT = "redundant"
OVER_CAP = "cap"

_LOG_SAMPLE = 8  # dropped relations named per log line
_LOG_NAME_MAX = 60

_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


def _lock_for(user_id: str, course_id: str) -> threading.Lock:
    """The lock stripe serializing one (student, course) graph's edge writes."""
    return _LOCK_STRIPES[hash((user_id, course_id)) % len(_LOCK_STRIPES)]


@dataclass(frozen=True)
class PrereqResolution:
    #: (prerequisite, dependent) to write, by the course graph's stored names,
    #: in rank order.
    edges: tuple[tuple[str, str], ...]
    #: Resolved edges the course graph already has (rule 5): nothing to write.
    already_present: tuple[tuple[str, str], ...]
    #: (reason, prerequisite, dependent) — the model's names for rules 1–4, the
    #: stored names for rules 6–8.
    dropped: tuple[tuple[str, str, str], ...]


def _reaches(successors: dict[str, set[str]], start: str, goal: str) -> bool:
    seen = {start}
    stack = [start]
    while stack:
        for nxt in successors.get(stack.pop(), ()):
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def resolve_prerequisites(
    relations: Iterable[tuple[str, str]],
    *,
    document_concepts: Iterable[tuple[str, float]],
    course_concepts: Iterable[str],
    existing_edges: Iterable[tuple[str, str]] = (),
    max_edges: int = MAX_PREREQ_EDGES_PER_DOCUMENT,
) -> PrereqResolution:
    """Apply the module docstring's rules to the model's relations.

    `relations` and `existing_edges` are (prerequisite, dependent) NAME pairs;
    `document_concepts` are this document's (name, importance); and
    `course_concepts` is the scope — every concept name in the student's course
    graph at write time."""
    scope: dict[str, str] = {}
    for name in course_concepts:
        key = _normalize_concept(name)
        if key:
            scope.setdefault(key, " ".join(name.split()))
    importance: dict[str, float] = {}
    for name, value in document_concepts:
        key = _normalize_concept(name)
        if key:
            importance[key] = max(importance.get(key, value), value)

    def rank(key: str) -> tuple[int, float, str]:
        if key in importance:
            return (1, -importance[key], key)
        return (0, 0.0, key)

    dropped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[str, str]] = []
    for raw_pre, raw_dep in relations:
        pre, dep = _normalize_concept(raw_pre), _normalize_concept(raw_dep)
        if pre not in scope or dep not in scope:
            reason = UNKNOWN
        elif pre == dep:
            reason = SELF_LOOP
        elif pre not in importance and dep not in importance:
            reason = OFF_DOCUMENT
        elif (pre, dep) in seen:
            reason = DUPLICATE
        else:
            seen.add((pre, dep))
            candidates.append((pre, dep))
            continue
        dropped.append((reason, raw_pre, raw_dep))
    candidates.sort(key=lambda edge: (rank(edge[0]), rank(edge[1])))

    successors: dict[str, set[str]] = defaultdict(set)
    present: set[tuple[str, str]] = set()
    for raw_pre, raw_dep in existing_edges:
        pre, dep = _normalize_concept(raw_pre), _normalize_concept(raw_dep)
        if pre and dep and pre != dep:
            successors[pre].add(dep)
            present.add((pre, dep))

    already: list[tuple[str, str]] = []
    admitted: list[tuple[str, str]] = []
    for pre, dep in candidates:
        if (pre, dep) in present:
            already.append((pre, dep))
        elif _reaches(successors, dep, pre):
            dropped.append((CYCLE, scope[pre], scope[dep]))
        else:
            successors[pre].add(dep)
            admitted.append((pre, dep))

    redundant: set[tuple[str, str]] = set()
    for pre, dep in reversed(admitted):
        successors[pre].discard(dep)
        if _reaches(successors, pre, dep):
            redundant.add((pre, dep))
            dropped.append((REDUNDANT, scope[pre], scope[dep]))
        else:
            successors[pre].add(dep)
    kept = [edge for edge in admitted if edge not in redundant]
    for pre, dep in kept[max_edges:]:
        dropped.append((OVER_CAP, scope[pre], scope[dep]))

    def named(edges: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
        return tuple((scope[pre], scope[dep]) for pre, dep in edges)

    return PrereqResolution(named(kept[:max_edges]), named(already), tuple(dropped))


def edge_payload(prerequisite: str, dependent: str) -> dict:
    """One `apply_graph_update` new_edges entry, oriented by
    EDGE_PREREQ_SOURCE_IS_PREREQ (spec §3.1)."""
    source, target = (
        (prerequisite, dependent) if EDGE_PREREQ_SOURCE_IS_PREREQ else (dependent, prerequisite)
    )
    return {
        "source": source,
        "target": target,
        "relationship_type": PREREQ_RELATIONSHIP_TYPE,
        "strength": UPLOAD_PREREQ_STRENGTH,
    }


def course_concept_names(user_id: str, course_id: str | None) -> list[str]:
    """The existing concept names the extraction message lists (A118): the
    EXISTING_CONCEPTS_PROMPT_MAX most recently created nodes of this student's
    course graph — a document's DIRECT prerequisites are most often the
    material just before it. Context, never a gate: a failed read is logged
    and reads as none, and the extraction then runs on the text alone, exactly
    as before A118."""
    if not user_id or not course_id:
        return []
    try:
        rows = table("graph_nodes").select(
            "concept_name",
            filters={
                "user_id": f"eq.{user_id}",
                "course_id": f"eq.{course_id}",
                "mastery_tier": "neq.subject_root",
            },
            order="created_at.desc,id.desc",
            limit=EXISTING_CONCEPTS_PROMPT_MAX,
        )
    except Exception:
        logger.warning(
            "existing-concepts read failed for user=%s course=%s; extracting "
            "without them", user_id, course_id, exc_info=True,
        )
        return []
    if not isinstance(rows, list):
        return []
    return [
        r["concept_name"] for r in rows
        if isinstance(r, dict) and isinstance(r.get("concept_name"), str)
    ]


def _course_nodes(user_id: str, course_id: str) -> dict[str, str]:
    """node id -> concept name, for every concept of the course graph."""
    rows = page_all(
        table("graph_nodes"), "id,concept_name",
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{course_id}",
            "mastery_tier": "neq.subject_root",
        },
        order="id",
    )
    return {r["id"]: r["concept_name"] for r in rows if r.get("id") and r.get("concept_name")}


def _course_prereq_edges(user_id: str, nodes: dict[str, str]) -> list[tuple[str, str]]:
    """The student's prerequisite edges between the course's nodes, as
    (prerequisite, dependent) names. Edges carry no course column, so they are
    read per student and kept when both endpoints are this course's."""
    rows = page_all(
        table("graph_edges"), "id,source_node_id,target_node_id",
        filters={
            "user_id": f"eq.{user_id}",
            "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}",
        },
        order="id",
    )
    out: list[tuple[str, str]] = []
    for r in rows:
        src, tgt = r.get("source_node_id"), r.get("target_node_id")
        if src in nodes and tgt in nodes:
            pre, dep = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
            out.append((nodes[pre], nodes[dep]))
    return out


def _log_outcome(user_id: str, course_id: str, res: PrereqResolution) -> None:
    """One line per write: INFO when every relation was used, WARNING (with
    the reasons and a bounded sample of the names) when any was dropped."""
    detail = ""
    if res.dropped:
        counts = dict(sorted(Counter(reason for reason, _, _ in res.dropped).items()))
        sample = "; ".join(
            f"{reason}: {str(pre)[:_LOG_NAME_MAX]!r} -> {str(dep)[:_LOG_NAME_MAX]!r}"
            for reason, pre, dep in res.dropped[:_LOG_SAMPLE]
        )
        detail = f" {counts} ({sample})"
    logger.log(
        logging.WARNING if res.dropped else logging.INFO,
        "upload prerequisites user=%s course=%s: wrote %d, already present %d, dropped %d%s",
        user_id, course_id, len(res.edges), len(res.already_present), len(res.dropped), detail,
    )


def write_document_prerequisites(
    user_id: str, course_id: str | None, concepts: ConceptList,
) -> int:
    """Write one document's prerequisite edges (A118); returns how many new
    edges were written.

    Runs after the upload merged the document's concepts as nodes, so they are
    in scope. Gated by the `upload_prereq_edges` flag (per student); off, it
    reads and writes nothing. Best-effort, like any enrichment of an upload
    that already succeeded: a failure is logged and returns 0, never raised —
    a re-upload writes what is missing, idempotently. Blocking I/O: call it
    off the event loop."""
    relations = [
        (r.prerequisite, r.dependent)
        # getattr: a ConceptList checkpointed by DBOS before A118 has no field.
        for r in (getattr(concepts, "prerequisites", None) or [])
    ]
    # No course, no scope: the upload routes always send one (a required form
    # field), and an unscoped apply_graph_update would resolve names across
    # every course the student has.
    if not relations or not user_id or not course_id:
        return 0
    if not flag_on(UPLOAD_PREREQ_EDGES_FLAG, user_id):
        return 0
    try:
        with _lock_for(user_id, course_id):
            nodes = _course_nodes(user_id, course_id)
            res = resolve_prerequisites(
                relations,
                document_concepts=[(c.name, c.importance) for c in concepts.concepts],
                course_concepts=nodes.values(),
                existing_edges=_course_prereq_edges(user_id, nodes),
            )
            if res.edges:
                apply_graph_update(
                    user_id,
                    {"new_edges": [edge_payload(pre, dep) for pre, dep in res.edges]},
                    course_id=course_id,
                )
    except Exception:
        logger.exception(
            "upload prerequisites failed for user=%s course=%s (the upload is "
            "unaffected)", user_id, course_id,
        )
        return 0
    _log_outcome(user_id, course_id, res)
    return len(res.edges)
