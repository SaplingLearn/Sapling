"""The admin report on self-explanation prompts (spec §13 A139). Pure: rows in,
numbers out (stdlib and params only, so the admin route may import it without
touching the PKG-06 layer). Every rate carries its n; a rate over nothing is
None, never 0.

Inputs: the `learning_self_explanations` rows of the range (one per served
prompt: its node, its item, juncture, when, status and reply length — never
the reply) and the endpoint's non-void evidence rows (A123's one void rule
already applied). Per prompt, the NEXT ITEM is the student's first graded
opportunity on the concept after the prompt with another question than the
prompt's own (A133's next-opportunity reading): unassisted when correct, not
assisted and at rung 0 after the help floor. Reported for prompts the student
replied to against the rest (skipped, or never replied) — a description of
what followed, never a causal claim: students who reply may differ from those
who do not.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from learning.params import SELF_EXPLAIN_JUNCTURES


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class _Journal:
    """The non-void evidence rows by node, oldest first."""

    def __init__(self, evidence: Iterable[Mapping]) -> None:
        self.by_node: dict[str, list[tuple[datetime, Mapping]]] = defaultdict(list)
        for row in evidence:
            at = _ts(row.get("created_at"))
            node = row.get("node_id")
            if at is not None and node:
                self.by_node[node].append((at, row))
        for rows in self.by_node.values():
            rows.sort(key=lambda t: t[0])

    def next_outcome(self, prompt: Mapping) -> str:
        """unassisted / other — the next graded item on the concept after the
        prompt, with another question — or none (no such row in the range)."""
        at = _ts(prompt.get("prompted_at"))
        own = prompt.get("question_hash")
        if at is None:
            return "none"
        for when, row in self.by_node.get(prompt.get("node_id") or "", ()):
            if when <= at or row.get("question_hash") in (None, own):
                continue
            unassisted = (
                row.get("correct") is True
                and row.get("assisted") is not True
                and (_int(row.get("max_rung")) or 0) == 0
            )
            return "unassisted" if unassisted else "other"
        return "none"


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def _next_item(outcomes: list[str]) -> dict[str, Any]:
    graded = [o for o in outcomes if o != "none"]
    unassisted = sum(1 for o in graded if o == "unassisted")
    return {
        "n": len(graded),
        "unassisted": unassisted,
        "rate": _rate(unassisted, len(graded)),
        "none": len(outcomes) - len(graded),
    }


def _summary(prompts: list[Mapping], journal: _Journal) -> dict[str, Any]:
    replied = [p for p in prompts if p.get("status") == "replied"]
    others = [p for p in prompts if p.get("status") != "replied"]
    return {
        "shown": len(prompts),
        "replied": len(replied),
        "reply_rate": _rate(len(replied), len(prompts)),
        "next_item": {
            "replied": _next_item([journal.next_outcome(p) for p in replied]),
            "not_replied": _next_item([journal.next_outcome(p) for p in others]),
        },
    }


def self_explanation_report(prompts: Iterable[Mapping], evidence: Iterable[Mapping]) -> dict[str, Any]:
    """The report: overall counts (shown, replied, skipped, open — never
    replied), the reply rate (n = shown), the median reply length in
    characters (n = replies), next-item unassisted success after replying vs
    not, and the same by juncture."""
    rows = list(prompts)
    journal = _Journal(evidence)
    chars = [c for c in (_int(p.get("reply_chars")) for p in rows if p.get("status") == "replied") if c is not None]
    by_juncture = [
        {"juncture": j, **_summary([p for p in rows if p.get("juncture") == j], journal)}
        for j in SELF_EXPLAIN_JUNCTURES
    ]
    return {
        **_summary(rows, journal),
        "skipped": sum(1 for p in rows if p.get("status") == "skipped"),
        "open": sum(1 for p in rows if p.get("status") == "open"),
        "reply_chars": {"median": statistics.median(chars) if chars else None, "n": len(chars)},
        "by_juncture": by_juncture,
    }
