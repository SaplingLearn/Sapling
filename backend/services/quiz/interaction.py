"""W7 kit `interaction` sanitize — generation / wire attach.

Keep this fail-closed and kind-narrow: a bad payload is dropped, never a
reason to reject the whole quiz. Client mirrors live in
`frontend/src/lib/quiz/*Interaction.ts`. See docs/learning-loop/w7-generation-emit.md.
"""

from __future__ import annotations

from typing import Any


def _clean_id(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    id_ = raw.strip()
    if not id_ or any(ch in id_ for ch in ";=,"):
        return ""
    return id_


def _clean_nodes(raw: Any) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return nodes
    for it in raw:
        if not isinstance(it, dict):
            continue
        id_ = _clean_id(it.get("id"))
        label = it.get("label")
        if not id_ or not isinstance(label, str) or not label.strip() or id_ in seen:
            continue
        seen.add(id_)
        nodes.append({"id": id_, "label": label.strip()})
    return nodes


def _sanitize_sort(raw: dict[str, Any]) -> dict[str, Any] | None:
    buckets_raw = raw.get("buckets")
    if not isinstance(buckets_raw, list):
        return None
    buckets = [b.strip() for b in buckets_raw if isinstance(b, str) and b.strip()]
    if len(buckets) < 2:
        return None
    items = _clean_nodes(raw.get("items"))
    if not items:
        return None
    return {"kind": "sort", "buckets": buckets, "items": items}


def _sanitize_connect(raw: dict[str, Any]) -> dict[str, Any] | None:
    mode = raw.get("mode")
    note = raw.get("note")
    note_s = note.strip() if isinstance(note, str) and note.strip() else None

    if mode == "map":
        nodes = _clean_nodes(raw.get("nodes"))
        if len(nodes) < 3:
            return None
        out: dict[str, Any] = {"kind": "connect", "mode": "map", "nodes": nodes}
        if note_s:
            out["note"] = note_s
        return out

    left = _clean_nodes(raw.get("left"))
    right = _clean_nodes(raw.get("right"))
    if len(left) < 2 or len(right) < 2 or len(left) != len(right):
        return None
    right_ids = {n["id"] for n in right}
    if any(n["id"] in right_ids for n in left):
        return None
    out = {"kind": "connect", "left": left, "right": right}
    if note_s:
        out["note"] = note_s
    return out


_KIND_SANITIZERS = {
    "sort": _sanitize_sort,
    "connect": _sanitize_connect,
}


def sanitize_interaction(raw: Any) -> dict[str, Any] | None:
    """Return a client-safe interaction dict, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if not isinstance(kind, str):
        return None
    fn = _KIND_SANITIZERS.get(kind.strip())
    if fn is None:
        return None
    return fn(raw)
