"""Read-side graph tools for Pydantic AI agents.

Per ADR 0004: the agent needs to pull mastery state + course-level
misconceptions when planning a quiz. These are the tool surfaces.
The pure-async functions are callable directly from routes;
the *_tool wrappers register on a Pydantic AI Agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from db.connection import table
from services import prompt_dimensions
from services.academics import user_offering_ids_for_course
from services.tool_signals import Expect, report_empty_result_async

logger = logging.getLogger(__name__)


# ── read_concepts_for_user ────────────────────────────────────────────────


class ConceptMastery(BaseModel):
    """Per-concept mastery state for the user in a course."""

    concept_name: str
    mastery: float = Field(ge=0.0, le=1.0)
    last_reviewed_at: str | None = None


async def read_concepts_for_user(
    user_id: str,
    course_id: str | None,
) -> list[ConceptMastery]:
    """Return the user's concept mastery for a course (or globally if
    course_id is None). Sorted by mastery ASC so the weakest concepts
    appear first — quiz_agent uses this ordering to focus on weak areas.

    Pure async, callable from routes. Wraps the underlying sync
    Supabase read in asyncio.to_thread so it doesn't block the loop.

    NOTE: The underlying `graph_nodes` table stores the mastery value as
    `mastery_score` and the timestamp as `last_studied_at`. We map them
    here to the agent-facing names (`mastery`, `last_reviewed_at`) so the
    tool contract stays stable even if storage column names change.
    """

    def _fetch() -> list[dict[str, Any]]:
        filters = {"user_id": f"eq.{user_id}"}
        if course_id:
            filters["course_id"] = f"eq.{course_id}"
        try:
            return (
                table("graph_nodes").select(
                    "concept_name,mastery_score,last_studied_at",
                    filters=filters,
                    order="mastery_score.asc",
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_concepts_for_user failed for user=%s course=%s",
                user_id,
                course_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    return [
        ConceptMastery(
            concept_name=r.get("concept_name") or "",
            mastery=float(r.get("mastery_score") or 0.0),
            last_reviewed_at=r.get("last_studied_at"),
        )
        for r in rows
        if r.get("concept_name")
    ]


async def read_concepts_for_user_tool(
    ctx: RunContext[SaplingDeps],
    limit: int = 25,
) -> list[ConceptMastery]:
    """List the student's tracked concepts, weakest first. Each entry
    carries the mastery score (0-1) and when the concept was last
    reviewed (last_reviewed_at) — use this for review-recency questions
    the GRAPH CONTEXT block can't answer.

    The LLM may choose `limit` (how many concepts to see, capped here on
    the wrapper only — the pure function stays uncapped for route/quiz
    callers). user_id/course_id come from deps, never the model. Fetches
    through the retrieval seam (ADR 0023).
    """
    from agents.tools.retrieval import resolve_retrieval

    from services.prompt_safety import neutralize_delimiters

    rows = await resolve_retrieval(ctx.deps).concept_mastery(
        ctx.deps.user_id, ctx.deps.course_id
    )
    # F5: a student with a populated graph whose concept read comes back
    # empty is a discrepancy, not a new student. Shared with the tutor,
    # which registers this same tool — the fourth instance of this bug class
    # is as likely to land there as in the quiz, hence `feature` off deps
    # rather than a hardcoded name.
    #
    # The probe is scoped to the SAME course the read was scoped to. Probing
    # the whole graph would flag every student who has concepts in one course
    # and none in another — the ordinary case for anyone taking more than one
    # class, and enough false alarms to make the signal worthless.
    await report_empty_result_async(
        "read_concepts_for_user",
        user_id=ctx.deps.user_id,
        count=len(rows),
        expect=Expect.HAS_GRAPH,
        feature=getattr(ctx.deps, "feature", "unknown"),
        scope=(
            {"course_id": f"eq.{ctx.deps.course_id}"} if ctx.deps.course_id else None
        ),
        payload={"course_id": ctx.deps.course_id},
    )
    n = max(0, int(limit))
    # #150 (PR #471 review): concept names are student-derived text — the
    # seed block neutralizes them and this sibling surface must too.
    return [
        r.model_copy(update={"concept_name": neutralize_delimiters(r.concept_name)})
        for r in rows[:n]
    ]


# ── read_graph_neighborhood (#149) ────────────────────────────────────────


class ConceptNode(BaseModel):
    """One concept in the student's course graph, agent-facing shape.

    Names only — row ids never cross the tool boundary (the LLM has no
    business echoing UUIDs, and every write path resolves by name)."""

    concept_name: str
    mastery: float = Field(ge=0.0, le=1.0)
    mastery_tier: str
    last_reviewed_at: str | None = None


class ConceptEdge(BaseModel):
    """A relationship between two concepts, by NAME (never node ids)."""

    source: str
    target: str
    relationship_type: str = "related"
    strength: float | None = None


class GraphNeighborhood(BaseModel):
    """A depth-1 subgraph around the requested seed concepts."""

    concepts: list[ConceptNode]
    edges: list[ConceptEdge]
    truncated: bool = False


async def read_graph_neighborhood(
    user_id: str,
    course_id: str | None,
    concepts: list[str],
    *,
    limit: int = 20,
) -> GraphNeighborhood:
    """Return the depth-1 neighborhood of `concepts` in the user's course
    graph: the seed concepts that exist (matched via the same
    case/whitespace-insensitive normalization `apply_graph_update` dedups
    on), every concept one edge away, and the edges among them — all by
    concept NAME. Row ids are resolved internally and never returned.

    Course scoping is strict: nodes are read with the course filter, and
    since `graph_edges` carries no course_id, edges are kept only when
    BOTH endpoints resolve to a course-scoped node — an edge into another
    course's concept is dropped rather than leaking its name.

    `limit` caps the total concepts returned (seeds first, then
    neighbors, deterministic order); `truncated=True` signals the cap
    bit. Degrades to an empty neighborhood on any DB error — the tutor
    can always answer without the graph; raising would kill the turn.
    """
    # Local import: graph_service imports config at module load; keep this
    # module's import surface unchanged for non-neighborhood callers.
    from services.graph_service import _normalize_concept

    def _fetch() -> GraphNeighborhood:
        empty = GraphNeighborhood(concepts=[], edges=[], truncated=False)
        try:
            node_filters = {"user_id": f"eq.{user_id}"}
            if course_id:
                node_filters["course_id"] = f"eq.{course_id}"
            nodes = (
                table("graph_nodes").select(
                    "id,concept_name,mastery_score,mastery_tier,last_studied_at",
                    filters=node_filters,
                )
                or []
            )

            by_id: dict[str, dict[str, Any]] = {}
            by_norm: dict[str, dict[str, Any]] = {}
            for n in nodes:
                name = n.get("concept_name") or ""
                node_id = n.get("id")
                if not name or not node_id:
                    continue
                by_id[node_id] = n
                by_norm[_normalize_concept(name)] = n

            seed_ids: list[str] = []
            seen_ids: set[str] = set()
            for raw in concepts:
                row = by_norm.get(_normalize_concept(raw or ""))
                if row and row["id"] not in seen_ids:
                    seed_ids.append(row["id"])
                    seen_ids.add(row["id"])
            if not seed_ids:
                return empty

            # Depth-1 edges touching any seed. PostgREST has no OR across
            # two columns in this client's filter dict (one key per
            # column), so: two in.() reads, merged + deduped.
            ids_csv = ",".join(seed_ids)
            edge_cols = "source_node_id,target_node_id,relationship_type,strength"
            edge_rows: list[dict[str, Any]] = []
            for col in ("source_node_id", "target_node_id"):
                edge_rows.extend(
                    table("graph_edges").select(
                        edge_cols,
                        filters={
                            "user_id": f"eq.{user_id}",
                            col: f"in.({ids_csv})",
                        },
                    )
                    or []
                )

            # Dedup (an edge between two seeds comes back from both reads)
            # and drop any edge whose endpoint is outside the course-scoped
            # node map — that endpoint belongs to another course (or is
            # dangling) and must not leak.
            kept_edges: list[dict[str, Any]] = []
            seen_edges: set[tuple] = set()
            for e in edge_rows:
                src, tgt = e.get("source_node_id"), e.get("target_node_id")
                if src not in by_id or tgt not in by_id:
                    continue
                key = (src, tgt, e.get("relationship_type") or "related")
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                kept_edges.append(e)

            # Selection: seeds first, then neighbors in edge order.
            ordered_ids: list[str] = list(seed_ids)
            ordered_set = set(seed_ids)
            for e in kept_edges:
                for nid in (e["source_node_id"], e["target_node_id"]):
                    if nid not in ordered_set:
                        ordered_ids.append(nid)
                        ordered_set.add(nid)

            cap = max(0, int(limit))
            truncated = len(ordered_ids) > cap
            kept_ids = ordered_ids[:cap]
            kept_id_set = set(kept_ids)

            def _clamp(v: Any) -> float:
                try:
                    return max(0.0, min(1.0, float(v or 0.0)))
                except (TypeError, ValueError):
                    return 0.0

            out_concepts = [
                ConceptNode(
                    concept_name=by_id[nid].get("concept_name") or "",
                    mastery=_clamp(by_id[nid].get("mastery_score")),
                    mastery_tier=by_id[nid].get("mastery_tier") or "unexplored",
                    last_reviewed_at=by_id[nid].get("last_studied_at"),
                )
                for nid in kept_ids
            ]
            out_edges = [
                ConceptEdge(
                    source=by_id[e["source_node_id"]]["concept_name"],
                    target=by_id[e["target_node_id"]]["concept_name"],
                    relationship_type=e.get("relationship_type") or "related",
                    strength=e.get("strength"),
                )
                for e in kept_edges
                if e["source_node_id"] in kept_id_set
                and e["target_node_id"] in kept_id_set
            ]
            return GraphNeighborhood(
                concepts=out_concepts, edges=out_edges, truncated=truncated
            )
        except Exception:
            logger.exception(
                "read_graph_neighborhood failed for user=%s course=%s",
                user_id,
                course_id,
            )
            return empty

    return await asyncio.to_thread(_fetch)


async def read_graph_neighborhood_tool(
    ctx: RunContext[SaplingDeps],
    concepts: list[str],
    limit: int = 20,
) -> GraphNeighborhood:
    """Expand the student's knowledge graph around the named concepts:
    each matched concept plus everything one relationship away, with
    mastery, tier, last_reviewed_at, and the connecting edges
    (prerequisite / builds_on / related).

    The LLM supplies only concept NAMES (and optionally `limit`);
    user_id/course_id come from deps so the model can never aim the read
    at another student or course. Fetches through the retrieval seam
    (ADR 0023).
    """
    from agents.tools.retrieval import resolve_retrieval

    from services.prompt_safety import neutralize_delimiters

    hood = await resolve_retrieval(ctx.deps).graph_neighborhood(
        ctx.deps.user_id, ctx.deps.course_id, concepts, limit=limit
    )
    # #150 (PR #471 review): student-derived concept names, same
    # neutralization as the seed block and the mastery reader above.
    return hood.model_copy(update={
        "concepts": [
            c.model_copy(update={"concept_name": neutralize_delimiters(c.concept_name)})
            for c in hood.concepts
        ],
        "edges": [
            e.model_copy(update={
                "source": neutralize_delimiters(e.source),
                "target": neutralize_delimiters(e.target),
            })
            for e in hood.edges
        ],
    })


# ── read_misconceptions_for_course ────────────────────────────────────────


class Misconception(BaseModel):
    """A class-level misconception observed across student sessions."""

    text: str
    related_concept: str | None = None


async def read_misconceptions_for_course(
    offering_id: str | None,
) -> list[Misconception]:
    """Return aggregated misconception strings for an offering (a class in a
    term). Anonymized (sourced from class-wide patterns, not any single student).
    Returns [] when offering_id is None or the underlying table is empty.

    Source: `offering_concept_stats` rows for the offering. Each row
    represents one concept and carries a `common_misconceptions` array
    (populated by the hash-gated aggregation in
    `services/course_context_service.py`). We flatten each array entry
    into its own Misconception, tagging `related_concept` with the
    concept name so the agent can route distractors per-concept.

    The tool contract (returning Misconception[]) is unchanged.
    """
    if not offering_id:
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            return (
                table("offering_concept_stats").select(
                    "concept_name,common_misconceptions",
                    filters={"offering_id": f"eq.{offering_id}"},
                    order="updated_at.desc",
                    limit=20,
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_misconceptions_for_course failed for offering=%s",
                offering_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    out: list[Misconception] = []
    seen: set[str] = set()
    for r in rows:
        concept = r.get("concept_name") or None
        for m in r.get("common_misconceptions") or []:
            text = (m or "").strip() if isinstance(m, str) else ""
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(Misconception(text=text, related_concept=concept))
    return out


async def read_misconceptions_for_course_tool(
    ctx: RunContext[SaplingDeps],
) -> list[Misconception]:
    """Pydantic AI tool wrapper. Reads from ctx.deps.

    #150: misconception strings are distilled from OTHER students'
    sessions — peer-derived text. Delimiters are neutralized at this LLM
    boundary so an injected string can't forge untrusted-envelope markers;
    the consuming agents' UNTRUSTED CONTENT POLICY covers the rest
    (typed short strings — no per-entry envelope).
    """
    from services.prompt_safety import neutralize_delimiters

    out = await read_misconceptions_for_course(ctx.deps.course_id)
    # F5: THE canonical instance of this bug class. This tool passed the
    # abstract course id where the query filters `offering_id` — a different
    # keyspace, so it returned zero rows for every student, indefinitely,
    # and looked exactly like a class that simply had no misconceptions yet.
    # (#553 carries the fix; this makes the next one impossible to miss.)
    # The probe asks whether aggregates exist for THIS student's offerings of
    # THIS course — not merely whether they are enrolled in something.
    # "Enrolled somewhere" would fire on every generation in a course whose
    # class simply has no aggregated misconceptions yet, which is the normal
    # state for the first weeks of any term.
    #
    # Scoped this way it detects the real failure instead: aggregates exist
    # for the class, but this tool's read returned none — the signature of a
    # keyspace mismatch, which is precisely how #553 (abstract course id used
    # where an offering id is expected) presents.
    #
    # Gated on the result being EMPTY, not merely on having a course id.
    # `user_offering_ids_for_course` is uncached and issues two unbounded
    # PostgREST reads (enrollments -> offerings), and this runs on the quiz
    # generation request path — resolving it whenever a course id exists made
    # every generation pay both round-trips even when the tool returned rows,
    # contradicting tool_signals' own documented contract ("one owner-scoped
    # indexed read, only on the empty path"). `report_empty_result` would
    # short-circuit on a non-zero count anyway, so the work was pure waste.
    if not out and ctx.deps.course_id:
        offering_ids: list[str] = []
        try:
            offering_ids = await asyncio.to_thread(
                user_offering_ids_for_course, ctx.deps.user_id, ctx.deps.course_id
            )
        except Exception:
            logger.debug("misconceptions probe: offering resolution failed", exc_info=True)
        if offering_ids:
            await report_empty_result_async(
                "read_misconceptions_for_course",
                user_id=ctx.deps.user_id,
                count=len(out),
                expect=Expect.COURSE_HAS_AGGREGATES,
                feature=getattr(ctx.deps, "feature", "unknown"),
                scope={"offering_id": f"in.({','.join(offering_ids)})"},
                payload={"course_id": ctx.deps.course_id},
            )
    # F6: this block's contribution to the prompt.
    prompt_dimensions.record(misconceptions=len(out))
    return [
        Misconception(
            text=neutralize_delimiters(m.text),
            related_concept=(
                neutralize_delimiters(m.related_concept)
                if m.related_concept
                else m.related_concept
            ),
        )
        for m in out
    ]
