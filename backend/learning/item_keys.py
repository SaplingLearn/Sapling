"""Check-item key verification: an independent solve, compared with the key in
code (spec §13 A124).

Pure: imports learning.checks, learning.item_alignment and learning.params
only (all pure), so it is listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

A check item's answer key is drafted by one model from classmates' uploads
(A23, A43), and nobody reviews it before it grades students. Wrong-answer
feedback then releases that key as the solution, so one wrong key teaches
every student of the course the wrong answer. Before an item is stored (and,
for stored items, in scripts/backfill_check_item_keys.py), a model of another
family solves it BLIND — from the question, an mc_reason item's options and the
source passages, never the key, the rubric or the reference answer
(agents/check_items_solve.py) — and THIS module compares its answer with the
key in code:

- mc_reason → the option letter. The solver is shown the options under their
  STORED letters (checks.lettered_options), so it picks among exactly what a
  student sees, and its letter is compared with the stored correct letter.
- numeric → the value it states (checks.stated_value, the A34 reading) within
  the item's tolerance plus the A22 numeric gate's edge slack: the rule the
  gate grades a student's number with, so a key verified here is one the gate
  can apply.
- free text (free, teachback) → equal answer-token runs (checks.answer_run)
  agree in code; any other pair goes to ONE second structured call per batch
  that sees the question and the two answers and says whether they agree
  (agents/check_items_key_match.py). The equivalence cannot come from the
  solving call: a call shown the key is no blind solve (a model shown an answer
  tends to confirm it), so the solve stays blind and the comparison is a
  separate, closed judgment that never solves anything.

Outcomes: agreement → verified (the service sets canonical_verified); a
different answer → held under checks.KEY_DISPUTED; the solver states that the
question and the passages do not settle one answer → held under
checks.KEY_UNSOLVED; no usable answer (none, two that conflict, a letter that
is not one of the item's options, a numeric answer stating no number, a free
pair the match call left unanswered) → unverified, and the caller's rule
decides (the draft path drops that draft alone, the backfill leaves the item
untouched). Nothing trusts the model for a bound: ids are matched exactly, an
unlisted id is ignored, and a conflict is never read as either answer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import NamedTuple

from learning.checks import (
    KEY_AUDIT_AMBIGUOUS,
    KEY_AUDIT_WRONG,
    KEY_DISPUTED,
    KEY_UNSOLVED,
    answer_run,
    stated_value,
)
from learning.item_alignment import merge_flags
from learning.params import NUMERIC_GATE_EDGE_SLACK

_MC_REASON = "mc_reason"
_NUMERIC = "numeric"

#: The hold codes the independent solve sets (a re-check replaces them).
MODEL_KEY_FLAGS = (KEY_DISPUTED, KEY_UNSOLVED)
#: The hold codes a human audit verdict sets (no model run ever touches them).
AUDIT_KEY_FLAGS = (KEY_AUDIT_WRONG, KEY_AUDIT_AMBIGUOUS)

# compare() outcomes
AGREE = "agree"
DISPUTED = "disputed"
UNSOLVED = "unsolved"
NO_VERDICT = "no_verdict"
TO_MATCH = "to_match"  # free text the code could not settle: the match call decides

# Why a draft is held or dropped. Also what the mc_reason top-up is told
# (agents/check_items_topup.py), so each names its rule first.
DISPUTED_REASON = (
    "key: an independent solve of the question from the passages gave a different answer "
    "than the draft's key (held for staff review)"
)
UNSOLVED_REASON = (
    "key: an independent solve found that the question and the passages do not settle one "
    "answer (held for staff review)"
)
UNVERIFIED_REASON = "unverified: the key check gave no usable answer for this item"
#: A short code per reason, for output that must carry no text (the backfill).
REASON_CODES = {
    DISPUTED_REASON: KEY_DISPUTED,
    UNSOLVED_REASON: KEY_UNSOLVED,
    UNVERIFIED_REASON: "unverified",
}


class KeySubject(NamedTuple):
    """One item as the key check reads it. The solver is shown only `format`,
    `prompt`, `options` and `answer_kind` (agents/check_items_solve.SolveItem);
    the rest is the key it is compared with."""

    format: str
    prompt: str
    options: tuple[tuple[str, str], ...]  # (letter, text) in stored order; () unless mc_reason
    answer_kind: str
    correct_option: str | None  # mc_reason: the stored letter of the key
    canonical_answer: str | None  # numeric: the key's value, plain decimal text
    tolerance: float | None  # numeric: the accepted absolute error (None = exact)
    final_answer: str  # the key's stated final answer (A34)


class Solved(NamedTuple):
    """The independent solve's answer for one item, as collected."""

    solvable: bool
    answer: str


class KeyCheck(NamedTuple):
    """What the key check decided for one item."""

    verified: bool  # the independent solve agreed with the key
    flag: str | None = None  # KEY_DISPUTED / KEY_UNSOLVED: hold the item
    reason: str | None = None  # why it is held or unverified
    unverified: bool = False  # no usable verdict: the caller's rule decides


# An option named by its letter: "B", "(b)", "B.", "Option B", "B) <text>".
_LETTER = re.compile(
    r"^\s*(?:(?:option|choice|answer)\b\s*[:\-]?\s*)?[(\[]?\s*([A-Za-z])\s*(?:[)\].:]\s*(?:\S.*)?)?$",
    re.IGNORECASE | re.DOTALL,
)


def option_letter(answer: str | None) -> str | None:
    """The single option letter an answer names, uppercased, or None when it
    names none ("B", "(b)", "Option B" and "B) the size of the step" all name
    B; "Both" and "A bigger step" name nothing)."""
    m = _LETTER.match(answer or "")
    return m.group(1).upper() if m else None


def _number(text: str | None) -> float | None:
    """A finite number from plain decimal text, as the A22 gate parses a key."""
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def within_tolerance(got: float, want: float, tolerance: float | None) -> bool:
    """The negation of the A22 gate's clear mismatch
    (agents/tools/check.py::_numeric_mismatch): within the tolerance plus the
    gate's relative edge slack."""
    slack = NUMERIC_GATE_EDGE_SLACK * max(1.0, abs(got), abs(want))
    return abs(got - want) <= (tolerance or 0.0) + slack


def compare(subject: KeySubject, solved: Solved | None) -> str:
    """One item's comparison in code: AGREE, DISPUTED, UNSOLVED, NO_VERDICT
    or TO_MATCH (a free-text pair the match call must settle)."""
    if solved is None:
        return NO_VERDICT
    if not solved.solvable:
        return UNSOLVED
    if subject.format == _MC_REASON:
        letters = {letter.upper() for letter, _ in subject.options}
        picked = option_letter(solved.answer)
        if picked is None or picked not in letters or not subject.correct_option:
            return NO_VERDICT
        return AGREE if picked == subject.correct_option.upper() else DISPUTED
    if subject.answer_kind == _NUMERIC:
        stated = stated_value(solved.answer)
        want = _number(subject.canonical_answer)
        if stated is None or want is None:
            return NO_VERDICT
        got = float(stated)
        if not math.isfinite(got):
            return NO_VERDICT
        return AGREE if within_tolerance(got, want, subject.tolerance) else DISPUTED
    run = answer_run(solved.answer)
    if not run:
        return NO_VERDICT
    return AGREE if run == answer_run(subject.final_answer) else TO_MATCH


def settle(outcome: str, same: bool | None = None) -> KeyCheck:
    """The decision for one compared item; `same` is the match call's answer
    for a TO_MATCH pair (None = unanswered)."""
    if outcome == TO_MATCH:
        if same is None:
            return KeyCheck(False, None, UNVERIFIED_REASON, unverified=True)
        outcome = AGREE if same else DISPUTED
    if outcome == AGREE:
        return KeyCheck(True)
    if outcome == DISPUTED:
        return KeyCheck(False, KEY_DISPUTED, DISPUTED_REASON)
    if outcome == UNSOLVED:
        return KeyCheck(False, KEY_UNSOLVED, UNSOLVED_REASON)
    return KeyCheck(False, None, UNVERIFIED_REASON, unverified=True)


def collect_solutions(rows: Iterable[tuple[str, bool, str]]) -> dict[str, Solved]:
    """The solver's rows — (item id, solvable, answer) — as one Solved per
    item id. An item answered twice in disagreement gets none (unverified):
    a conflict is never read as either answer."""
    seen: dict[str, Solved] = {}
    conflicted: set[str] = set()
    for item, solvable, answer in rows:
        item = str(item).strip()
        solved = Solved(bool(solvable), str(answer or "").strip())
        if item in seen and _norm(seen[item]) != _norm(solved):
            conflicted.add(item)
        seen.setdefault(item, solved)
    return {item: solved for item, solved in seen.items() if item not in conflicted}


def _norm(solved: Solved) -> tuple:
    return (solved.solvable, answer_run(solved.answer))


def collect_matches(rows: Iterable[tuple[str, bool]]) -> dict[str, bool]:
    """The match call's rows — (item id, same) — as one answer per item id;
    two that disagree give none."""
    seen: dict[str, bool] = {}
    conflicted: set[str] = set()
    for item, same in rows:
        item = str(item).strip()
        if item in seen and seen[item] != bool(same):
            conflicted.add(item)
        seen.setdefault(item, bool(same))
    return {item: same for item, same in seen.items() if item not in conflicted}


def checked_flags(stored: Iterable[str] | None, check: KeyCheck) -> list[str]:
    """A stored item's flags after a model key check: its earlier model codes
    replaced by this check's (none when it agreed); every other code — the
    linter's, the alignment check's, a human audit's — kept as stored, in
    learning.item_alignment.merge_flags' order."""
    kept = [f for f in stored or () if f not in MODEL_KEY_FLAGS]
    return merge_flags(kept, [check.flag] if check.flag else [])


def audited_flags(stored: Iterable[str] | None, code: str | None) -> list[str]:
    """A stored item's flags after a human audit verdict: its earlier audit
    code replaced by `code` (None for "correct"); every other code kept."""
    kept = [f for f in stored or () if f not in AUDIT_KEY_FLAGS]
    return merge_flags(kept, [code] if code else [])
