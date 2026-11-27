"""W7 kit `interaction` sanitize — generation / wire attach.

Keep this fail-closed and kind-narrow: a bad payload is dropped, never a
reason to reject the whole quiz. Client mirrors live in
`frontend/src/lib/quiz/*Interaction.ts`. See docs/learning-loop/w7-generation-emit.md.
"""

from __future__ import annotations

import hashlib
from typing import Any

#: A dialogue's reply bounds: each of minReplies/maxReplies is clamped into
#: [DIALOGUE_REPLIES_FLOOR, DIALOGUE_REPLIES_CEILING]; a missing value takes its
#: default, and an inverted pair falls back to both defaults.
DIALOGUE_REPLIES_FLOOR = 1
DIALOGUE_REPLIES_CEILING = 8
DIALOGUE_MIN_REPLIES_DEFAULT = 2
DIALOGUE_MAX_REPLIES_DEFAULT = 4
#: A connect-map needs at least this many nodes to draw a map.
CONNECT_MAP_MIN_NODES = 3
#: The fewest entries any other kit list (buckets, steps, options, passages,
#: markers, stops, items, each side of a pairing) or a scrambled pool takes.
MIN_KIT_ENTRIES = 2
#: A highlight's minSelected when the payload gives none (and its floor).
HIGHLIGHT_MIN_SELECTED_DEFAULT = 1


def _clean_id(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    id_ = raw.strip()
    if not id_ or any(ch in id_ for ch in ";=,"):
        return ""
    return id_


def _clean_text(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _clean_nodes(raw: Any) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return nodes
    for it in raw:
        if not isinstance(it, dict):
            continue
        id_ = _clean_id(it.get("id"))
        label = _clean_text(it.get("label"))
        if not id_ or not label or id_ in seen:
            continue
        seen.add(id_)
        nodes.append({"id": id_, "label": label})
    return nodes


def _clean_side(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    id_ = _clean_id(raw.get("id"))
    label = _clean_text(raw.get("label"))
    if not id_ or not label:
        return None
    return {"id": id_, "label": label}


def _opt_str(raw: Any) -> str | None:
    text = _clean_text(raw)
    return text or None


def _clamp_int(raw: Any, default: int, lo: int, hi: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return max(lo, min(hi, raw))


def _sanitize_sort(raw: dict[str, Any]) -> dict[str, Any] | None:
    buckets_raw = raw.get("buckets")
    if not isinstance(buckets_raw, list):
        return None
    buckets = [b.strip() for b in buckets_raw if isinstance(b, str) and b.strip()]
    if len(buckets) < MIN_KIT_ENTRIES:
        return None
    items = _clean_nodes(raw.get("items"))
    if not items:
        return None
    return {"kind": "sort", "buckets": buckets, "items": items}


def _sanitize_label(raw: dict[str, Any]) -> dict[str, Any] | None:
    spots = _clean_nodes(raw.get("spots"))
    labels = _clean_nodes(raw.get("labels"))
    if not spots or not labels or len(spots) != len(labels):
        return None
    spot_ids = {s["id"] for s in spots}
    if any(label["id"] in spot_ids for label in labels):
        return None
    return {"kind": "label", "spots": spots, "labels": labels}


def _sanitize_sequence(raw: dict[str, Any]) -> dict[str, Any] | None:
    steps = _clean_nodes(raw.get("steps"))
    if len(steps) < MIN_KIT_ENTRIES:
        return None
    return {"kind": "sequence", "steps": steps}


def _sanitize_build(raw: dict[str, Any]) -> dict[str, Any] | None:
    slots = _clean_nodes(raw.get("slots"))
    parts = _clean_nodes(raw.get("parts"))
    if not slots or not parts or len(parts) < len(slots):
        return None
    slot_ids = {s["id"] for s in slots}
    if any(p["id"] in slot_ids for p in parts):
        return None
    return {"kind": "build", "slots": slots, "parts": parts}


def _sanitize_compare(raw: dict[str, Any]) -> dict[str, Any] | None:
    left = _clean_side(raw.get("left"))
    right = _clean_side(raw.get("right"))
    options = _clean_nodes(raw.get("options"))
    if not left or not right or left["id"] == right["id"] or len(options) < MIN_KIT_ENTRIES:
        return None
    side_ids = {left["id"], right["id"]}
    if any(o["id"] in side_ids for o in options):
        return None
    return {"kind": "compare", "left": left, "right": right, "options": options}


def _sanitize_dialogue(raw: dict[str, Any]) -> dict[str, Any] | None:
    role = _clean_text(raw.get("role"))
    open_ = _clean_text(raw.get("open"))
    follow = _clean_text(raw.get("follow"))
    if not role or not open_ or not follow:
        return None
    min_replies = _clamp_int(
        raw.get("minReplies"), DIALOGUE_MIN_REPLIES_DEFAULT, DIALOGUE_REPLIES_FLOOR, DIALOGUE_REPLIES_CEILING
    )
    max_replies = _clamp_int(
        raw.get("maxReplies"), DIALOGUE_MAX_REPLIES_DEFAULT, DIALOGUE_REPLIES_FLOOR, DIALOGUE_REPLIES_CEILING
    )
    if max_replies < min_replies:
        min_replies, max_replies = DIALOGUE_MIN_REPLIES_DEFAULT, DIALOGUE_MAX_REPLIES_DEFAULT
    out: dict[str, Any] = {
        "kind": "dialogue",
        "role": role,
        "open": open_,
        "follow": follow,
        "minReplies": min_replies,
        "maxReplies": max_replies,
    }
    placeholder = _opt_str(raw.get("placeholder"))
    if placeholder:
        out["placeholder"] = placeholder
    return out


def _sanitize_explain(raw: dict[str, Any]) -> dict[str, Any] | None:
    out: dict[str, Any] = {"kind": "explain"}
    placeholder = _opt_str(raw.get("placeholder"))
    if placeholder:
        out["placeholder"] = placeholder
    rubric_raw = raw.get("rubric")
    if isinstance(rubric_raw, list):
        rubric = [r.strip() for r in rubric_raw if isinstance(r, str) and r.strip()]
        if rubric:
            out["rubric"] = rubric
    return out


def _sanitize_highlight(raw: dict[str, Any]) -> dict[str, Any] | None:
    passages = _clean_nodes(raw.get("passages"))
    if len(passages) < MIN_KIT_ENTRIES:
        return None
    min_selected = _clamp_int(
        raw.get("minSelected"), HIGHLIGHT_MIN_SELECTED_DEFAULT, HIGHLIGHT_MIN_SELECTED_DEFAULT, len(passages)
    )
    out: dict[str, Any] = {
        "kind": "highlight",
        "passages": passages,
        "minSelected": min_selected,
    }
    note = _opt_str(raw.get("note"))
    if note:
        out["note"] = note
    return out


def _sanitize_calculate(raw: dict[str, Any]) -> dict[str, Any] | None:
    out: dict[str, Any] = {"kind": "calculate"}
    for key in ("placeholder", "unitLabel", "stepsPlaceholder"):
        val = _opt_str(raw.get(key))
        if val:
            out[key] = val
    return out


def _sanitize_position(raw: dict[str, Any]) -> dict[str, Any] | None:
    markers = _clean_nodes(raw.get("markers"))
    stops = _clean_nodes(raw.get("stops"))
    if len(markers) < MIN_KIT_ENTRIES or len(stops) < MIN_KIT_ENTRIES:
        return None
    stop_ids = {s["id"] for s in stops}
    if any(m["id"] in stop_ids for m in markers):
        return None
    out: dict[str, Any] = {"kind": "position", "markers": markers, "stops": stops}
    axis = _opt_str(raw.get("axisLabel"))
    if axis:
        out["axisLabel"] = axis
    return out


def _sanitize_rank(raw: dict[str, Any]) -> dict[str, Any] | None:
    items = _clean_nodes(raw.get("items"))
    if len(items) < MIN_KIT_ENTRIES:
        return None
    out: dict[str, Any] = {"kind": "rank", "items": items}
    for key in ("hint", "whyPlaceholder"):
        val = _opt_str(raw.get(key))
        if val:
            out[key] = val
    return out


def _sanitize_connect(raw: dict[str, Any]) -> dict[str, Any] | None:
    mode = raw.get("mode")
    note = _opt_str(raw.get("note"))

    if mode == "map":
        nodes = _clean_nodes(raw.get("nodes"))
        if len(nodes) < CONNECT_MAP_MIN_NODES:
            return None
        out: dict[str, Any] = {"kind": "connect", "mode": "map", "nodes": nodes}
        if note:
            out["note"] = note
        return out

    left = _clean_nodes(raw.get("left"))
    right = _clean_nodes(raw.get("right"))
    if len(left) < MIN_KIT_ENTRIES or len(right) < MIN_KIT_ENTRIES or len(left) != len(right):
        return None
    right_ids = {n["id"] for n in right}
    if any(n["id"] in right_ids for n in left):
        return None
    out = {"kind": "connect", "left": left, "right": right}
    if note:
        out["note"] = note
    return out


_KIND_SANITIZERS = {
    "sort": _sanitize_sort,
    "label": _sanitize_label,
    "sequence": _sanitize_sequence,
    "build": _sanitize_build,
    "compare": _sanitize_compare,
    "dialogue": _sanitize_dialogue,
    "explain": _sanitize_explain,
    "highlight": _sanitize_highlight,
    "calculate": _sanitize_calculate,
    "position": _sanitize_position,
    "rank": _sanitize_rank,
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


def attach_interaction(wire: dict[str, Any], raw: Any) -> dict[str, Any]:
    """Copy a sanitized kit payload onto a short_answer wire item (in place).

    Other types ignore `raw`. Bad payloads are dropped without mutating.
    """
    if wire.get("type") != "short_answer":
        return wire
    interaction = sanitize_interaction(raw)
    if interaction is not None:
        wire["interaction"] = interaction
    return wire


# The pool a student drags FROM. The model writes it in key order (a
# sequence's steps ARE the answer `id1;id2;…`, a match's `right[i]` pairs
# with `left[i]`), so the student view must never show it as written. Kits
# assign by id, never by index. A connect MAP's nodes are not a pool.
_POOL_KEYS: dict[str, str] = {
    "sequence": "steps",
    "rank": "items",
    "sort": "items",
    "label": "labels",
    "build": "parts",
    "position": "markers",
    "connect": "right",
}

# Fields a kit shows only WITH the verdict (ExplainAnswer renders the rubric
# once marked): the pre-answer view never carries them.
_POST_ANSWER_KEYS: dict[str, tuple[str, ...]] = {"explain": ("rubric",)}


def scramble_pool(interaction: dict[str, Any], seed: str) -> dict[str, Any]:
    """Return a copy with the kit's pool in a stable, non-key order.

    Ordered by sha256(seed|id), so a resume shows the same order; when that
    happens to reproduce the written order it is rotated by one, so a pool of
    two or more never arrives in key order.
    """
    key = _POOL_KEYS.get(str(interaction.get("kind")))
    if key is None:
        return interaction
    pool = interaction.get(key)
    if not isinstance(pool, list) or len(pool) < MIN_KIT_ENTRIES:
        return interaction
    ranked = sorted(
        pool,
        key=lambda n: hashlib.sha256(f"{seed}|{n.get('id', '')}".encode()).hexdigest(),
    )
    if [n.get("id") for n in ranked] == [n.get("id") for n in pool]:
        ranked = ranked[1:] + ranked[:1]
    return {**interaction, key: ranked}


def keyless_interaction(raw: Any, seed: str) -> dict[str, Any] | None:
    """The pre-answer view of a kit: sanitized, post-answer fields dropped,
    the pool scrambled. None when the payload is unusable."""
    interaction = sanitize_interaction(raw)
    if interaction is None:
        return None
    for field in _POST_ANSWER_KEYS.get(interaction["kind"], ()):
        interaction.pop(field, None)
    return scramble_pool(interaction, seed)
