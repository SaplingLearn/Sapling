"""Turn the concept_edges agent's proposal into edges safe to write.

Pure functions, no I/O. The model proposes; this decides. Everything the
radial layout (`frontend/src/lib/graph/radialLayout.ts`) needs from the data
is enforced here rather than trusted to the model:

* both endpoints are concepts of THIS course (exact match after the same
  case/whitespace fold `graph_service` dedups on) and differ;
* at most one edge per unordered pair, existing edges included;
* directed edges (prerequisite / builds_on) form a DAG with the course's
  existing directed edges: the layout's ring depth is a longest path, and a
  cycle makes it meaningless;
* each concept keeps at most `MAX_INCOMING` directed edges in, strongest
  first, so the drawing stays a tree-ish web rather than a hairball;
* no shortcut edges: a new A→C is dropped when A already reaches C through
  other edges, since it adds a line without changing any ring;
* `related` edges are capped per concept and per course.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

DIRECTED = frozenset({"prerequisite", "builds_on", "part_of"})
PROPOSABLE = frozenset({"prerequisite", "builds_on", "related"})
MAX_INCOMING = 3
MAX_RELATED_PER_CONCEPT = 2


def normalize(name: str) -> str:
    """Same fold as `graph_service._normalize_concept` (its dedup key)."""
    return " ".join((name or "").split()).casefold()


def build_message(course_label: str, concept_names: list[str]) -> str:
    listing = "\n".join(f"- {n}" for n in sorted(concept_names, key=str.casefold))
    return (
        f'Course: "{course_label}"\n'
        f"Concepts in the student's graph for this course ({len(concept_names)}):\n"
        f"{listing}"
    )


def _reaches(adj: dict[str, set[str]], start: str, goal: str, skip: tuple[str, str] | None = None) -> bool:
    """True when `goal` is reachable from `start` over `adj`, ignoring the
    single edge `skip`."""
    stack, seen = [start], {start}
    while stack:
        u = stack.pop()
        for v in adj.get(u, ()):
            if skip is not None and (u, v) == skip:
                continue
            if v == goal:
                return True
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return False


def sanitize_edges(
    concept_names: Iterable[str],
    proposed: Iterable[dict],
    existing: Iterable[dict] = (),
) -> list[dict]:
    """Return the NEW edges to write, as `apply_graph_update` `new_edges`
    dicts ({source, target, relationship_type, strength}) with canonical
    concept names. `existing` edges (same dict shape, names) constrain the
    result but are never returned."""
    canon: dict[str, str] = {}
    for n in concept_names:
        key = normalize(n)
        if key and key not in canon:
            canon[key] = n

    adj: dict[str, set[str]] = defaultdict(set)  # directed, canonical names
    indeg: dict[str, int] = defaultdict(int)
    pairs: set[frozenset[str]] = set()
    related_count: dict[str, int] = defaultdict(int)

    for e in existing:
        s, t = canon.get(normalize(e.get("source", ""))), canon.get(normalize(e.get("target", "")))
        if not s or not t or s == t:
            continue
        pairs.add(frozenset((s, t)))
        if e.get("relationship_type") in DIRECTED:
            adj[s].add(t)
            indeg[t] += 1
        else:
            related_count[s] += 1
            related_count[t] += 1

    resolved: list[dict] = []
    for e in proposed:
        rel = e.get("relationship_type")
        if rel not in PROPOSABLE:
            continue
        s, t = canon.get(normalize(e.get("source", ""))), canon.get(normalize(e.get("target", "")))
        if not s or not t or s == t:
            continue
        try:
            strength = max(0.0, min(1.0, float(e.get("strength", 0.6))))
        except (TypeError, ValueError):
            strength = 0.6
        resolved.append({"source": s, "target": t, "relationship_type": rel, "strength": strength})

    # Strongest first; the stable sort keeps the model's order among ties.
    resolved.sort(key=lambda e: -e["strength"])

    added_directed: list[dict] = []
    for e in (x for x in resolved if x["relationship_type"] in DIRECTED):
        s, t = e["source"], e["target"]
        pair = frozenset((s, t))
        if pair in pairs or indeg[t] >= MAX_INCOMING:
            continue
        if _reaches(adj, t, s):  # s→t would close a cycle
            continue
        adj[s].add(t)
        indeg[t] += 1
        pairs.add(pair)
        added_directed.append(e)

    # Transitive reduction over the NEW edges, weakest first: an edge whose
    # endpoints stay connected without it adds a line but no depth.
    kept_directed: list[dict] = []
    for e in sorted(added_directed, key=lambda x: x["strength"]):
        s, t = e["source"], e["target"]
        if _reaches(adj, s, t, skip=(s, t)):
            adj[s].discard(t)
            indeg[t] -= 1
            pairs.discard(frozenset((s, t)))
            continue
        kept_directed.append(e)

    related_cap = max(1, len(canon) // 3)
    kept_related: list[dict] = []
    for e in (x for x in resolved if x["relationship_type"] == "related"):
        s, t = e["source"], e["target"]
        pair = frozenset((s, t))
        if pair in pairs or len(kept_related) >= related_cap:
            continue
        if related_count[s] >= MAX_RELATED_PER_CONCEPT or related_count[t] >= MAX_RELATED_PER_CONCEPT:
            continue
        pairs.add(pair)
        related_count[s] += 1
        related_count[t] += 1
        kept_related.append(e)

    order = {id(e): i for i, e in enumerate(resolved)}
    return sorted(kept_directed + kept_related, key=lambda e: order[id(e)])


def ring_depths(concept_names: Iterable[str], edges: Iterable[dict]) -> dict[str, int]:
    """Longest-path depth per concept over directed edges: the ring each
    concept lands on in the radial layout (mirrors `computeDepths`)."""
    names = list(dict.fromkeys(concept_names))
    known = set(names)
    adj: dict[str, list[str]] = defaultdict(list)
    indeg = {n: 0 for n in names}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if e.get("relationship_type") in DIRECTED and s in known and t in known and s != t:
            adj[s].append(t)
            indeg[t] += 1
    depth = {n: 0 for n in names}
    queue = [n for n in names if indeg[n] == 0]
    while queue:
        u = queue.pop()
        for v in adj[u]:
            depth[v] = max(depth[v], depth[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return depth
