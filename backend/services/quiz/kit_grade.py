"""Richer kit answer compare for short_answer + interaction (W7).

Order-insensitive where the UI encode allows (Sort buckets, Connect map
edges, Highlight ids). Falls through to exact normalize when unknown.
Never writes mastery — callers still use grade_written → evidence path.
"""

from __future__ import annotations

from typing import Any

from services.quiz.grading import normalize_answer


def _parts(raw: str, sep: str) -> list[str]:
    return [p for p in raw.split(sep) if p != ""]


def _sort_canonical(raw: str) -> str | None:
    # BucketA=id1,id2;BucketB=id3 — sort ids inside each bucket; keep bucket order.
    buckets = []
    for part in raw.split(";"):
        if "=" not in part:
            return None
        name, ids = part.split("=", 1)
        name = name.strip()
        items = sorted(i.strip() for i in ids.split(",") if i.strip())
        buckets.append(f"{name}={','.join(items)}")
    return ";".join(buckets) if buckets else None


def _map_edges_canonical(raw: str) -> str | None:
    # Undirected a=b;c=d — normalize each pair and sort pairs.
    keys: list[str] = []
    for part in raw.split(";"):
        if "=" not in part:
            return None
        a, b = (x.strip() for x in part.split("=", 1))
        if not a or not b or a == b:
            return None
        keys.append(f"{a}={b}" if a < b else f"{b}={a}")
    return ";".join(sorted(set(keys)))


def _set_ids_canonical(raw: str, sep: str = ",") -> str | None:
    ids = sorted({p.strip() for p in raw.split(sep) if p.strip()})
    return sep.join(ids) if ids else None


def kit_canonical(interaction: Any, answer: str) -> str | None:
    """Return a canonical form for kit compare, or None if not applicable."""
    if not isinstance(interaction, dict):
        return None
    kind = interaction.get("kind")
    text = (answer or "").strip()
    if not text or not isinstance(kind, str):
        return None
    if kind == "sort":
        return _sort_canonical(text)
    if kind == "connect" and interaction.get("mode") == "map":
        return _map_edges_canonical(text)
    if kind == "highlight":
        return _set_ids_canonical(text, ",")
    if kind == "calculate":
        # value|unit[|steps] — grade on value|unit only.
        parts = text.split("|", 2)
        if len(parts) < 2:
            return None
        return f"{parts[0].strip()}|{parts[1].strip()}"
    return None


def kit_answers_match(question: dict, answer: str) -> bool | None:
    """True/False when kit compare applies; None → caller uses exact written grade."""
    if question.get("type") != "short_answer":
        return None
    interaction = question.get("interaction")
    got = kit_canonical(interaction, answer)
    if got is None:
        return None
    expected = question.get("correct_answer", "")
    if not isinstance(expected, str):
        return False
    want = kit_canonical(interaction, expected)
    if want is None:
        want = expected.strip()
    if got == want:
        return True
    accepted = question.get("accepted_answers") or []
    for alt in accepted:
        if not isinstance(alt, str):
            continue
        alt_c = kit_canonical(interaction, alt) or alt.strip()
        if got == alt_c:
            return True
    # Last resort: normalized exact (legacy keys).
    if normalize_answer(got) == normalize_answer(want):
        return True
    return False
