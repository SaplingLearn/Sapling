"""Attempt, rung, H6 and offer gates (spec §3.3 GATES; §13 A5, A32). Pure.

`non_attempt_phrases` / `matches_non_attempt` are the ONLY functions in the
policy layer that read student text, and they are a fixed phrase list, never
a model. policy.py must not import them (invariant 4).

Clocks are injected (A5): callers pass `now` / `independent_seconds` as float
seconds, and `time_scale=` (the route layer's `config.LEARNING_GATE_TIME_SCALE`,
default 1.0) scales every GATE_* constant through `params.gate_seconds`.
"""

from __future__ import annotations

import math
import re
from typing import get_args

from learning import params
from learning.policy import Band, StepState

NON_ATTEMPT_PATTERNS: tuple[str, ...] = (
    "just tell me",
    "give me the answer",
    "idk",
    "i don't know",
    "what's the answer",
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_APOSTROPHES = re.compile(r"['’‘ʼ`´]")
_BANDS = get_args(Band)
# Clause breaks: sentence and clause punctuation ('.' or ',' between digits is
# part of a number), brackets, newlines, and "but" ("I think it's 7 but idk").
_CLAUSE = re.compile(r"(?<!\d)[.,]|[.,](?!\d)|[;:!?()\[\]{}\n]|\bbut\b", re.I)
# A relation anywhere is an answer or shown work ("x = 7 idk", "F = ma, idk").
_RELATION = re.compile(r"[=<>≈≠≤≥]")
# Words that never make a clause an answer (normalized: apostrophes deleted).
# "yes"/"no"/"true"/"false" are answers, so they are not filler.
_FILLER = frozenset(
    "a am an and anyway are be can could confused help hey hi hm hmm honestly i im "
    "is it just lol lost me my not now oh ok okay please pls plz really so sorry "
    "stuck sure tbh thank thanks the this uh ugh um umm well what you".split()
)


def _norm(text: str) -> str:
    text = _APOSTROPHES.sub("", text.lower())
    return " ".join(_NON_ALNUM.sub(" ", text).split())


_NORMALIZED_PATTERNS = tuple(f" {_norm(p)} " for p in NON_ATTEMPT_PATTERNS)


def non_attempt_phrases(text: str) -> tuple[str, ...]:
    """The NON_ATTEMPT_PATTERNS (in their order) that make `text` a non-attempt,
    or () when it is not one. Phrases match whole (lowercase, apostrophes
    deleted, every other non-alphanumeric run a space: "idkfa" is not "idk").

    A phrase makes the MESSAGE a non-attempt only when nothing else in it could
    be an answer (spec §3.3: a genuine attempt is a submitted answer or shown
    work). The message splits into clauses: a phrase's own clause may say
    anything ("just tell me the steps"), every other clause may hold only
    filler ("sorry, idk"), and a relation symbol anywhere is an answer. So a
    hedged submission ("x = 7. idk if the units are right") is graded, never
    turned into idk evidence or a hint request (A16)."""
    found: set[str] = set()
    for clause in _CLAUSE.split(text):
        if _RELATION.search(clause):
            return ()
        norm = _norm(clause)
        padded = f" {norm} "
        hits = {p for p, n in zip(NON_ATTEMPT_PATTERNS, _NORMALIZED_PATTERNS) if n in padded}
        if hits:
            found |= hits
        elif not set(norm.split()) <= _FILLER:
            return ()
    return tuple(p for p in NON_ATTEMPT_PATTERNS if p in found)


def matches_non_attempt(text: str) -> bool:
    """`text` is a non-attempt ("just tell me", "idk", …): see non_attempt_phrases."""
    return bool(non_attempt_phrases(text))


def is_genuine_attempt(
    text_len_chars: int,
    has_shown_work: bool,
    matched_non_attempt: bool,
    independent_seconds: float,
    band: Band,
    *,
    time_scale: float = 1.0,
) -> bool:
    """Whether an attempt counts toward hint unlocking (spec §3.3). It never
    blocks grading an explicit submission (A16). A non-attempt message vetoes
    the attempt even when a separate work field is filled; a hedge beside an
    answer is not one (matches_non_attempt). The caller passes
    `matches_non_attempt`'s result, so only gates' text functions see the text."""
    if band not in _BANDS:
        raise ValueError(f"unknown band {band!r}")
    if math.isnan(independent_seconds):
        raise ValueError("independent_seconds is NaN")
    if matched_non_attempt:
        return False
    if text_len_chars <= 0 and not has_shown_work:
        return False
    gate = "GATE_INDEPENDENT_MIN_S_NOVICE" if band == "novice" else "GATE_INDEPENDENT_MIN_S"
    return independent_seconds >= params.gate_seconds(gate, time_scale)


def rung_unlock(step: StepState, now: float, *, time_scale: float = 1.0) -> bool:
    """The next rung unlocks after GATE_RUNG_DWELL_MIN_S on the current one AND a
    genuine attempt since it was shown. The anchor is `last_rung_at`, or
    `first_shown_at` when no rung was shown yet. `step.attempted_at` holds
    genuine attempts only (callers append when `is_genuine_attempt` is True)."""
    anchor = step.last_rung_at if step.last_rung_at is not None else step.first_shown_at
    dwelled = now - anchor >= params.gate_seconds("GATE_RUNG_DWELL_MIN_S", time_scale)
    return dwelled and any(t > anchor for t in step.attempted_at)


def h6_allowed(
    step: StepState, *, item_taught: bool, item_practice: bool, item_graded: bool
) -> bool:
    """Full solution gate (spec §3.3 H6 item predicates, §13 A32). The three
    predicates are keyword-only booleans the loop route supplies; ungraded is not
    practice, so `not item_graded` alone never admits H6."""
    return (
        step.genuine_attempts >= params.H6_MIN_GENUINE_ATTEMPTS
        and item_taught
        and item_practice
        and not item_graded
        and not step.exam_mode
    )


def offer_allowed(band: Band, last_attempt_wrong: bool) -> bool:
    """The error-triggered "want a hint?" offer: OFFER_BANDS only, after a wrong
    genuine attempt."""
    return band in params.OFFER_BANDS and last_attempt_wrong
