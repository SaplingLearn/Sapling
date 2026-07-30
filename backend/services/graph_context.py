"""Compact, course-scoped knowledge-graph context for tutor prompts (#149).

Two callers, one serialization:

  - `build_graph_context_block(user_id, course_id, message)` — the agent
    path's deterministic seed block. Selects up to `max_concepts` of the
    student's course concepts (message token-overlap first, weakest-mastery
    fill after), plus the depth-1 edges among the selected, and renders the
    compact GRAPH CONTEXT block `routes.learn._prepare_chat_run` prefixes
    onto the user message. Returns "" when there is no course or no
    concepts — the block is simply omitted.

  - `compact_graph_context(graph, course_id)` — the legacy-prompt
    de-dump. Takes an already-built `graph_service.get_graph` payload and
    renders the SAME compact serialization, course-scoped, replacing the
    old `json.dumps(get_graph(user_id), indent=2)` (which leaked every
    OTHER course's concepts into the prompt and burned tokens on ids and
    event history).

Serialization: one line per concept —

    - Derivatives (0.42, learning) → related: Limits, Chain Rule

No ids, no mastery-event history, hard character budget (~1.5k). Names are
verbatim so the model can echo the EXACT concept_name strings the graph
tools expect.
"""

from __future__ import annotations

import logging

from db.connection import table
from services.token_overlap import tokenize

logger = logging.getLogger(__name__)

# Hard budget for the rendered block (header included). Keeps the seed
# block a small, bounded prompt cost; selection already caps concepts, this
# is the backstop for pathologically long concept names.
GRAPH_CONTEXT_CHAR_BUDGET = 1500

_HEADER = (
    "GRAPH CONTEXT (the student's tracked concepts in this course; "
    "mastery 0-1):"
)


def _select_concepts(
    nodes: list[dict],
    message: str,
    max_concepts: int,
) -> list[dict]:
    """Deterministic selection: token-overlap matches first (higher overlap
    first), then lowest-mastery fill. Ties break on mastery ASC then name,
    so the same inputs always produce the same block."""
    msg_tokens = tokenize(message)

    def _mastery(n: dict) -> float:
        try:
            return float(n.get("mastery_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _overlap(n: dict) -> int:
        if not msg_tokens:
            return 0
        return len(msg_tokens & tokenize(n.get("concept_name") or ""))

    ranked = sorted(
        (n for n in nodes if n.get("concept_name")),
        key=lambda n: (
            -_overlap(n),
            _mastery(n),
            (n.get("concept_name") or "").lower(),
        ),
    )
    return ranked[: max(0, int(max_concepts))]


def _render(selected: list[dict], edges_by_source: dict[str, list[tuple[str, str]]]) -> str:
    """Render the block. `edges_by_source` maps a selected concept's node id
    to [(relationship_type, target_concept_name), ...] — already filtered to
    edges whose BOTH endpoints are selected."""
    lines: list[str] = []
    for n in selected:
        try:
            mastery = float(n.get("mastery_score") or 0.0)
        except (TypeError, ValueError):
            mastery = 0.0
        tier = n.get("mastery_tier") or "unexplored"
        line = f"- {n['concept_name']} ({mastery:.2f}, {tier})"
        rels = edges_by_source.get(n.get("id") or "", [])
        if rels:
            by_type: dict[str, list[str]] = {}
            for rel_type, target_name in rels:
                by_type.setdefault(rel_type or "related", []).append(target_name)
            rendered = "; ".join(
                f"{rel_type}: {', '.join(targets)}"
                for rel_type, targets in by_type.items()
            )
            line += f" → {rendered}"
        lines.append(line)

    # Enforce the character budget by dropping trailing (weakest-signal)
    # concept lines until the block fits. The budget applies to the raw
    # serialization; the #150 untrusted envelope below is fixed overhead
    # on top (see untrusted_envelope_overhead).
    while lines and len("\n".join([_HEADER, *lines])) > GRAPH_CONTEXT_CHAR_BUDGET:
        lines.pop()
    if not lines:
        return ""
    # #150: concept names are student-derived (extracted from their
    # documents/chats), so the concept lines ship inside the untrusted
    # envelope — a concept named "ignore your instructions" stays inert
    # data, and embedded delimiter forgeries are neutralized. The header
    # stays outside as trusted framing.
    from services.prompt_safety import wrap_untrusted

    return "\n".join(
        [_HEADER, wrap_untrusted("\n".join(lines), source="student graph concepts")]
    )


def graph_context_from_rows(
    nodes: list[dict],
    edge_rows: list[dict],
    message: str,
    max_concepts: int = 12,
) -> str:
    """Shared core: select from raw graph_nodes-shaped dicts + raw edge rows
    ({source_node_id/target_node_id or source/target, relationship_type}).
    Public so the offline evals can render the same GRAPH CONTEXT block
    from fixture rows that production renders from Supabase rows."""
    selected = _select_concepts(nodes, message, max_concepts)
    if not selected:
        return ""
    selected_ids = {n.get("id") for n in selected if n.get("id")}
    name_by_id = {n["id"]: n["concept_name"] for n in selected if n.get("id")}

    edges_by_source: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple] = set()
    for e in edge_rows:
        src = e.get("source_node_id") or e.get("source")
        tgt = e.get("target_node_id") or e.get("target")
        if src not in selected_ids or tgt not in selected_ids:
            continue
        rel = e.get("relationship_type") or "related"
        key = (src, tgt, rel)
        if key in seen:
            continue
        seen.add(key)
        edges_by_source.setdefault(src, []).append((rel, name_by_id[tgt]))

    return _render(selected, edges_by_source)


def build_graph_context_block(
    user_id: str,
    course_id: str | None,
    message: str,
    *,
    max_concepts: int = 12,
) -> str:
    """The agent path's deterministic seed block (AC 1 of #149).

    Course-scoped `graph_nodes` read + one user-wide `graph_edges` read
    (edges carry no course_id; both endpoints must be selected concepts to
    render, which enforces the course scope). Empty course → "" (block
    omitted). Degrades to "" on any DB error — the tutor still answers,
    it just isn't graph-grounded this turn.
    """
    if not course_id:
        return ""
    try:
        nodes = (
            table("graph_nodes").select(
                "id,concept_name,mastery_score,mastery_tier",
                filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
            )
            or []
        )
        if not nodes:
            return ""
        edge_rows = (
            table("graph_edges").select(
                "source_node_id,target_node_id,relationship_type",
                filters={"user_id": f"eq.{user_id}"},
            )
            or []
        )
        return graph_context_from_rows(nodes, edge_rows, message, max_concepts)
    except Exception:
        logger.exception(
            "build_graph_context_block failed for user=%s course=%s",
            user_id,
            course_id,
        )
        return ""


def compact_graph_context(
    graph: dict,
    course_id: str | None,
    *,
    max_concepts: int = 12,
) -> str:
    """Legacy-prompt serializer (#149 decision 3): compact course-scoped
    subgraph text from an already-built `get_graph` payload.

    Filters out other courses' nodes (the old `json.dumps(get_graph(...))`
    was user-wide) and the synthesized subject-root hubs. No message in
    scope on the legacy path, so selection is weakest-mastery-first —
    the concepts the tutor most needs to see. Renders via the same
    serializer as the agent seed block, same character budget.
    """
    if not course_id:
        return ""
    nodes = [
        n
        for n in (graph or {}).get("nodes", [])
        if n.get("course_id") == course_id
        and not n.get("is_subject_root")
        and n.get("mastery_tier") != "subject_root"
    ]
    if not nodes:
        return ""
    edge_rows = (graph or {}).get("edges", [])
    # get_graph edges use source/target keys; subject edges reference the
    # synthetic subject_root ids, which never appear in `nodes` and are
    # therefore dropped by the both-endpoints-selected rule.
    return graph_context_from_rows(nodes, edge_rows, message="", max_concepts=max_concepts)
