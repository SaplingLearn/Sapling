"""Help abuse, measured (spec §13 A133). Pure: stdlib + learning.params.

The loop's hint ladder ends in solution-level help — H5, a completion problem,
and H6, the full solution. Reaching that bottom quickly, through attempts that
say nothing, is the help abuse of the help-seeking literature: rapid hint
requests to the bottom-out hint (Aleven et al. 2006, 2016: a high bottom-out
rate goes with poorer learning, time spent per hint level with better) and the
"gaming the system" detectors built on it (Baker et al.). Its cost is
substitution — the help does the work, practice looks fine and unassisted
performance drops (Bastani et al. 2025, PNAS: unguarded GPT access raised
practice scores and lowered the unassisted exam). A109 measures the opposite
failure, help withheld from an earnest student; this report measures this one.

One STEP is one loop check item posed in one session — the help ledger's
`posed` rows with source `loop` (A93), keyed (student, session, item), posed at
the earliest. Every number below is read from structured records the loop
already writes; none from text:

- help: the ledger's `help` rows of the same (student, session, item), source
  `loop` — every granted /hint rung and every planned hint turn's rung, an H6
  served as a leaking payload included — each rung at its first row. The
  step's help level is the highest rung; a BOTTOM-OUT is a level of at least
  HELP_BOTTOM_OUT_RUNG (H5 †), a full solution H6.
- time to bottom-out: the pose to the first help at or above H5; help gaps: the
  seconds between consecutive new rungs on a step (the pace of the requests).
- attempts: the `zpd.attempt` events of the step (A134): every hint-unlocking
  attempt as judged — its time alone with the latest help against the band's
  independent-time gate (`rapid` when short of it), whether it said anything
  no counted attempt on the item had said (`repeat` when not), what the strict
  rule says of it, and whether it counted. A bottom-out's attempts are the
  counted ones made while the step was below H5 — the attempts that bought the
  climb. A bottom-out with none recorded (a step before A134, or help that
  needed no attempt) is `unmeasured`, never a zero.
- what happened next: for a graded step (its own non-void evidence row: the
  same session and item), the student's next graded opportunity on the
  concept with ANOTHER item — the first later non-void evidence row on the
  node with another question hash: correct with no help (correct, not
  assisted, rung 0 after the help floor) or not; `none` when no later
  opportunity is in the range. Split by the step's help: none, partial (H1 up
  to below H5), bottom-out.

What is NOT measurable, and why: whether a hint-unlocking attempt had
SUBSTANCE in the grader's sense. Those attempts are never graded — the grader
sees one explicit submission per step, after the help — and their text is
never stored (only a digest and a time). The attempt signals above are what
can be computed per attempt without the item's key and without storing the
text; they see rapid and repeated attempts, not a patient one-character one.

Groups: overall; by band (the graded step's zpd.step band, else its first
attempt's band, else unknown); by gate (`strict` when an attempt on the step
was judged under the help_gate_strict flag, `standard` when its attempts were
judged under the §3.3 rule, `none` when the student made no hint-unlocking
attempt — the gate never acted); by course (the session's course); by student.

It lives outside the PKG-06 layer (params only), like learning/earnest_revise.py:
the admin route must not import a PKG-06 module.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from learning import params

#: the bottom-out rung (H5 †) and the full solution (H6)
BOTTOM_OUT_RUNG = params.HELP_BOTTOM_OUT_RUNG
FULL_SOLUTION_RUNG = params.LADDER_MAX_RUNG
#: the ledger source of the loop's own help and poses (learning/help_ledger.py)
LOOP_SOURCE = "loop"
UNKNOWN = "unknown"
#: the gate cohort of a step on which no hint-unlocking attempt was made
NO_ATTEMPT = "none"
_BANDS = ("novice", "develop", "profic")
_GATES = ("standard", "strict")
#: help levels for "what happened next"
HELP_LEVELS = ("none", "partial", "bottom_out")


def _ts(raw) -> datetime | None:
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _payload(row: Mapping) -> Mapping:
    p = row.get("payload")
    return p if isinstance(p, Mapping) else {}


def _rung(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= params.LADDER_MAX_RUNG else None


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class _Step:
    user_id: str
    session_id: str
    question_hash: str
    posed_at: datetime
    help: dict[int, datetime] = field(default_factory=dict)  # rung -> first reached
    attempts: list[Mapping] = field(default_factory=list)  # zpd.attempt payloads, in order
    graded_band: str | None = None
    course: str = UNKNOWN

    @property
    def level(self) -> int:
        return max(self.help, default=0)

    @property
    def bottomed_out(self) -> bool:
        return self.level >= BOTTOM_OUT_RUNG

    @property
    def band(self) -> str:
        if self.graded_band in _BANDS:
            return self.graded_band
        for p in self.attempts:
            if p.get("band") in _BANDS:
                return p["band"]
        return UNKNOWN

    @property
    def gate(self) -> str:
        gates = {p.get("gate") for p in self.attempts}
        if "strict" in gates:
            return "strict"
        return "standard" if self.attempts else NO_ATTEMPT

    def bottom_out_at(self) -> datetime | None:
        times = [at for rung, at in self.help.items() if rung >= BOTTOM_OUT_RUNG]
        return min(times) if times else None

    def gaps(self, *, through_bottom_out: bool = False) -> list[float]:
        """Seconds between consecutive new rungs (in the order reached)."""
        rungs = sorted(self.help.items(), key=lambda kv: (kv[1], kv[0]))
        if through_bottom_out:
            cut = next((i for i, (r, _) in enumerate(rungs) if r >= BOTTOM_OUT_RUNG), None)
            rungs = rungs if cut is None else rungs[: cut + 1]
        return [
            max(0.0, (b[1] - a[1]).total_seconds()) for a, b in zip(rungs, rungs[1:])
        ]

    def counted(self) -> list[Mapping]:
        return [p for p in self.attempts if p.get("counted") is True]

    def climb(self) -> list[Mapping]:
        """The counted attempts made while the step was below the bottom-out
        rung: the attempts that bought the climb."""
        return [p for p in self.counted() if (_rung(p.get("rung")) or 0) < BOTTOM_OUT_RUNG]


def _rapid(p: Mapping) -> bool:
    alone, gate = _int(p.get("alone_ms")), _int(p.get("gate_ms"))
    return alone is not None and gate is not None and alone < gate


def _repeat(p: Mapping) -> bool:
    return p.get("novel") is False


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _steps(ledger: Iterable[Mapping]) -> dict[tuple[str, str, str], _Step]:
    """The posed steps, with their help, from the help ledger's loop rows."""
    rows = [r for r in ledger if r.get("source") == LOOP_SOURCE]
    steps: dict[tuple[str, str, str], _Step] = {}
    for r in rows:
        if r.get("kind") != "posed":
            continue
        key = (r.get("user_id"), r.get("session_id"), r.get("question_hash"))
        at = _ts(r.get("at"))
        if not all(key) or at is None:
            continue
        step = steps.get(key)
        if step is None:
            steps[key] = _Step(*key, posed_at=at)
        elif at < step.posed_at:
            step.posed_at = at
    for r in rows:
        if r.get("kind") != "help":
            continue
        step = steps.get((r.get("user_id"), r.get("session_id"), r.get("question_hash")))
        rung, at = _rung(r.get("rung")), _ts(r.get("at"))
        if step is None or rung is None or rung == 0 or at is None:
            continue
        if rung not in step.help or at < step.help[rung]:
            step.help[rung] = at
    return steps


def _join(
    steps: dict[tuple[str, str, str], _Step],
    attempt_events: Iterable[Mapping],
    step_events: Iterable[Mapping],
    courses: Mapping[str, str],
) -> None:
    def key(row: Mapping, p: Mapping) -> tuple:
        return (row.get("user_id"), p.get("session_id"), p.get("question_hash"))

    for row in sorted(attempt_events, key=lambda r: str(r.get("created_at") or "")):
        p = _payload(row)
        step = steps.get(key(row, p))
        if step is not None:
            step.attempts.append(p)
    for row in step_events:
        p = _payload(row)
        step = steps.get(key(row, p)) if p.get("phase") == "check" else None
        if step is not None and p.get("band") in _BANDS:
            step.graded_band = p["band"]
    for step in steps.values():
        step.course = courses.get(step.session_id) or UNKNOWN


class _Journal:
    """The non-void evidence rows, by node and by (session, item)."""

    def __init__(self, evidence: Iterable[Mapping]) -> None:
        self.by_node: dict[str, list[tuple[datetime, Mapping]]] = defaultdict(list)
        #: (session, item) -> (when the step was graded, the student's node)
        self.graded: dict[tuple[str, str], tuple[datetime, str]] = {}
        for row in evidence:
            at = _ts(row.get("created_at"))
            node = row.get("node_id")
            if at is None or not node:
                continue
            self.by_node[node].append((at, row))
            sk = (row.get("session_id"), row.get("question_hash"))
            if all(sk) and (sk not in self.graded or at < self.graded[sk][0]):
                self.graded[sk] = (at, node)
        for rows in self.by_node.values():
            rows.sort(key=lambda t: t[0])

    def next_outcome(self, step: _Step) -> str | None:
        """None: the step has no graded, non-void evidence row in the scan.
        Otherwise the student's next opportunity on the concept (the step's own
        evidence row names the node) with another item: unassisted_correct /
        other / none."""
        found = self.graded.get((step.session_id, step.question_hash))
        if found is None:
            return None
        graded, node = found
        for at, row in self.by_node.get(node, ()):
            if at <= graded or row.get("question_hash") in (None, step.question_hash):
                continue
            unassisted = (
                row.get("correct") is True
                and row.get("assisted") is not True
                and (_int(row.get("max_rung")) or 0) == 0
            )
            return "unassisted_correct" if unassisted else "other"
        return "none"


def _help_level(step: _Step) -> str:
    if step.bottomed_out:
        return "bottom_out"
    return "partial" if step.level > 0 else "none"


def _group(key: str, steps: list[_Step], journal: _Journal) -> dict[str, Any]:
    bottoms = [s for s in steps if s.bottomed_out]
    to_bottom = [
        max(0.0, (s.bottom_out_at() - s.posed_at).total_seconds())
        for s in bottoms
        if s.bottom_out_at() is not None
    ]
    gaps = [g for s in steps for g in s.gaps()]
    climb_gaps = [g for s in bottoms for g in s.gaps(through_bottom_out=True)]
    counted = [p for s in steps for p in s.counted()]
    measured = [s for s in bottoms if s.climb()]
    held = [s for s in measured if any(p.get("strict") is not True for p in s.climb())]
    none_strict = [s for s in measured if all(p.get("strict") is not True for p in s.climb())]
    nxt: dict[str, dict[str, int]] = {
        level: {"graded": 0, "unassisted_correct": 0, "other": 0, "none": 0} for level in HELP_LEVELS
    }
    for s in steps:
        outcome = journal.next_outcome(s)
        if outcome is None:
            continue
        bucket = nxt[_help_level(s)]
        bucket["graded"] += 1
        bucket[outcome] += 1
    return {
        "key": key,
        "steps": len(steps),
        "bottom_outs": len(bottoms),
        "full_solutions": sum(1 for s in steps if s.level >= FULL_SOLUTION_RUNG),
        "bottom_out_rate": len(bottoms) / len(steps) if steps else None,
        "time_to_bottom_out_s": {"n": len(to_bottom), "median": _median(to_bottom)},
        "help_gap_s": {"n": len(gaps), "median": _median(gaps)},
        "climb_gap_s": {"n": len(climb_gaps), "median": _median(climb_gaps)},
        "attempts": {
            "counted": len(counted),
            "rapid": sum(1 for p in counted if _rapid(p)),
            "repeat": sum(1 for p in counted if _repeat(p)),
            # strict-rule refusals of attempts the §3.3 rule would have counted:
            # the strict gate's friction, seen only where it was in force
            "strict_refused": sum(
                1
                for s in steps
                for p in s.attempts
                if p.get("gate") == "strict" and p.get("standard") is True and p.get("strict") is not True
            ),
        },
        "bottom_out_attempts": {
            "measured": len(measured),
            "unmeasured": len(bottoms) - len(measured),
            "held_by_strict": len(held),
            "no_strict_attempt": len(none_strict),
        },
        "next": nxt,
    }


def _grouped(
    name_of, steps: list[_Step], journal: _Journal, order: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    groups: dict[str, list[_Step]] = defaultdict(list)
    for s in steps:
        groups[name_of(s)].append(s)
    rank = {k: i for i, k in enumerate(order)}
    keys = sorted(groups, key=lambda k: (rank.get(k, len(rank)), k))
    return [_group(k, groups[k], journal) for k in keys]


def help_abuse(
    ledger: Iterable[Mapping],
    attempt_events: Iterable[Mapping],
    step_events: Iterable[Mapping],
    evidence: Iterable[Mapping],
    courses: Mapping[str, str],
) -> dict[str, Any]:
    """Spec §13 A133's report (module docstring). `ledger`: learning_reveals
    rows (kind, source, user_id, session_id, question_hash, rung, at);
    `attempt_events` / `step_events`: zpd.attempt / zpd.step event rows
    (user_id, payload, created_at); `evidence`: NON-VOID evidence rows (A123:
    the caller drops the void ones); `courses`: session id → course id."""
    by_key = _steps(ledger)
    _join(by_key, attempt_events, step_events, courses)
    steps = sorted(by_key.values(), key=lambda s: (s.posed_at, s.user_id, s.question_hash))
    journal = _Journal(evidence)
    students = _grouped(lambda s: s.user_id, steps, journal)
    students.sort(key=lambda g: (-g["bottom_outs"], -g["steps"], g["key"]))
    return {
        "bottom_out_rung": BOTTOM_OUT_RUNG,
        "overall": _group("all", steps, journal),
        "by_band": _grouped(lambda s: s.band, steps, journal, (*_BANDS, UNKNOWN)),
        "by_gate": _grouped(lambda s: s.gate, steps, journal, (*_GATES, NO_ATTEMPT)),
        "by_course": _grouped(lambda s: s.course, steps, journal),
        "by_student": students,
    }
