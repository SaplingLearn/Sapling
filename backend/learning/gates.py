"""Attempt, rung, H6 and offer gates (spec §3.3 GATES; §13 A5, A32). Pure.

`non_attempt_phrases` / `matches_non_attempt` are the ONLY functions in the
policy layer that read student text, and they are fixed phrase and word
lists, never a model. policy.py must not import them (invariant 4).

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
# The request phrases: the rest of their clause is what is asked for ("just
# tell me the steps", "what's the answer to part 2"), never an answer. The
# other two ("idk", "i don't know") are idk phrases (A16).
_REQUEST_PATTERNS = frozenset({"just tell me", "give me the answer", "what's the answer"})

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_APOSTROPHES = re.compile(r"['’‘ʼ`´]")
_BANDS = get_args(Band)
# Clause breaks: sentence and clause punctuation ('.' or ',' between digits is
# part of a number), brackets, newlines, and "but" ("I think it's 7 but idk").
_CLAUSE = re.compile(r"(?<!\d)[.,]|[.,](?!\d)|[;:!?()\[\]{}\n]|\bbut\b", re.I)
# A relation anywhere is an answer or shown work ("x = 7 idk", "F = ma, idk").
_RELATION = re.compile(r"[=<>≈≠≤≥]")
# Words that are never an answer on their own (normalized: apostrophes
# deleted): filler, function words, and the vocabulary of asking for help,
# being stuck or giving up. Every other word is an answer: a number, a content
# word, and words that can answer an item alone ("yes", "no", "true", "false",
# "up", "hard", "right", "both", "none", "one").
_NON_ANSWER = frozenset(
    """
    a am an and anyway are be can could confused help hey hi hm hmm honestly i im
    is it just lol lost me my not now oh ok okay please pls plz really so sorry
    stuck sure tbh thank thanks the this uh ugh um umm well what you
    bro dude omg rn u ur we us your youre its itself they them that thats these
    those there theres here any anything some something someone
    was were been being do does did doing done dont doesnt didnt have has had
    having ive id ill cant cannot couldnt wont wouldnt would should will might
    gonna wanna gotta
    to of for on in at with about from by as if or than then because
    whats how hows where wheres when why which who
    very too much still even again yet also already maybe probably perhaps
    possibly literally actually seriously totally completely basically kinda
    sorta kind sort bit lot like guess think thought way
    know knew understand understood get getting figure figured solve start
    started begin try tried trying spent spend hour hours minute minutes ages
    forever need want give gave show explain tell hint hints answer answers
    solution question step steps idea clue clueless dunno tired frustrated
    annoyed confusing difficult impossible
    """.split()
)
# Pleas whose words can answer an item alone ("no", "up", "hard").
_PLEA = re.compile(
    r"\bno (?:idea|clue)\b|\b(?:give|gave|giving) up\b"
    r"|\b(?:too|so|really|very|kinda|pretty|super|this is) (?:hard|tough)\b"
)


def _norm(text: str) -> str:
    text = _APOSTROPHES.sub("", text.lower())
    return " ".join(_NON_ALNUM.sub(" ", text).split())


_PATTERN_WORDS = tuple((p, tuple(_norm(p).split())) for p in NON_ATTEMPT_PATTERNS)


def _holds_an_answer(words: list[str]) -> bool:
    return any(w not in _NON_ANSWER for w in _PLEA.sub(" ", " ".join(words)).split())


def non_attempt_phrases(text: str) -> tuple[str, ...]:
    """The NON_ATTEMPT_PATTERNS (in their order) that make `text` a non-attempt,
    or () when it is not one. Phrases match whole (lowercase, apostrophes
    deleted, every other non-alphanumeric run a space: "idkfa" is not "idk").

    A phrase makes the MESSAGE a non-attempt only when nothing else in it is an
    answer (spec §3.3: a genuine attempt is a submitted answer or shown work,
    not idk/just tell me). What remains once the phrases, the object of a
    request phrase (the rest of its clause: "just tell me the steps"), pleas
    and non-answer words ("sorry", "where do I start", "I give up") are set
    aside must be empty: a number or a content word anywhere else, or a
    relation symbol anywhere, is an answer, with or without punctuation beside
    the hedge ("idk maybe 7", "the mitochondria idk"). So a hedged submission
    is graded, never turned into idk evidence or a hint request (A16); a plea
    never counts as a genuine attempt."""
    if _RELATION.search(text):
        return ()
    found: set[str] = set()
    for clause in _CLAUSE.split(text):
        words = _norm(clause).split()
        rest = [True] * len(words)
        for pattern, pw in _PATTERN_WORDS:
            for i in range(len(words) - len(pw) + 1):
                if tuple(words[i : i + len(pw)]) == pw:
                    found.add(pattern)
                    end = len(words) if pattern in _REQUEST_PATTERNS else i + len(pw)
                    rest[i:end] = [False] * (end - i)
        if _holds_an_answer([w for w, keep in zip(words, rest) if keep]):
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
