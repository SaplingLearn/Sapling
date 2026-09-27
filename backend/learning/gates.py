"""Attempt, rung, H6 and offer gates (spec §3.3 GATES; §13 A5, A32). Pure.

`has_non_attempt_phrase`, `non_attempt_phrases` and `matches_non_attempt` are
the ONLY functions in the policy layer that read student text, and they are
fixed phrase and word lists, never a model. policy.py must not import them
(invariant 4). They answer two questions, each failing in its safe direction:

- hint unlocking and H6: `has_non_attempt_phrase`, FAIL CLOSED. A phrase or a
  plea anywhere makes the message no genuine attempt; it is
  `is_genuine_attempt`'s `matched_non_attempt`.
- A16 routing of an explicit submission: `non_attempt_phrases`, FAIL TOWARD
  GRADING. idk evidence or a hint request only when nothing in the message
  can be an answer; otherwise it is graded.

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
# tell me the steps"), never an answer. The other two ("idk", "i don't know")
# are idk phrases (A16).
_REQUEST_PATTERNS = frozenset({"just tell me", "give me the answer", "what's the answer"})

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_APOSTROPHES = re.compile(r"['’‘ʼ`´]")
_BANDS = get_args(Band)
# Clause breaks bound a request phrase's object: sentence and clause
# punctuation, brackets, newlines, and "but". (A message with a digit never
# reaches the split, so "1.5" and "1,250" need no special case.)
_CLAUSE = re.compile(r"[.,;:!?()\[\]{}\n]|\bbut\b", re.I)
# Any digit is an answer.
_DIGIT = re.compile(r"\d")
# A relation symbol is an answer only BETWEEN operands ("F = ma", "a > b",
# "(a+b) = c"), so an emoticon ("=(", ">.<", "=/", ">_<") is not one.
_RELATION = re.compile(r"(?:[^\W_]|[)\]])\s*[=<>≈≠≤≥]+\s*[-−(\[]*[^\W_]")
# Words that never answer an item on their own (normalized: apostrophes
# deleted): filler, function words, the vocabulary of asking for help or being
# stuck, and chat slang. A word that CAN answer an item alone is not here
# ("even", "on", "in", "some", "any", "much", "still", "then", "when", "hour",
# "minute", "start", "begin", "up", "yes", "no", "true", "false", "hard",
# "right", "both", "none", "one", "bit", "lot", "lost", "solution", "id",
# "us", "impossible", "forever"); it is set aside only inside a _PLEA n-gram.
_NON_ANSWER = frozenset(
    """
    a am an and anyway are be can could confused help hey hi hm hmm honestly i im
    is it just lol me my not now oh ok okay please pls plz really so sorry
    stuck sure tbh thank thanks the this uh ugh um umm well what you
    bro dude omg rn u ur we your youre its itself they them that thats these
    those there theres here anything something someone
    man nah bruh lmao haha ngl xd sry tho though
    was were been being do does did doing done dont doesnt didnt wasnt werent
    isnt arent havent hasnt have has had having ive ill cant cannot couldnt
    wont wouldnt shouldnt would should will might gonna wanna gotta
    to of for at with about from by as if or than because
    whats how hows where wheres why which who
    very too again yet also already maybe probably perhaps possibly literally
    actually seriously totally completely basically kinda sorta kind sort like
    guess think thought way
    know knew understand understood get getting figure figured solve try tried
    trying spent spend ages need want give gave show explain tell hint hints
    another example next skip answer answers question problem step steps idea
    clue clueless dunno tired frustrated annoyed confusing difficult
    forgot remember missed lecture class mean means approach asking cover
    covered learned learnt taught differently write dumb stupid
    """.split()
)
# Pleas, matched on normalized text: n-grams that hold a word able to answer
# an item alone ("no", "up", "hard", "start", "hour", "much", "lost"), plus
# the idk variants outside NON_ATTEMPT_PATTERNS ("dunno", "don't know").
_PLEA = re.compile(
    r"\bno (?:idea|clue)\b|\b(?:give|gave|giving) up\b"
    r"|\bdunno\b|\b(?:dont|do not) know\b|\bnot sure\b"
    r"|\b(?:too|so|really|very|kinda|pretty|super|this is) (?:hard|tough|impossible)\b"
    r"|\b(?:where|how) (?:do i|to|should i|can i|would i|do you|do we) (?:even )?"
    r"(?:start|begin|get started)\b"
    r"|\b(?:for hours|an hour)(?: on (?:this|it))?\b|\btoo much\b"
    r"|\b(?:im|i am|so|totally|completely|really|kinda|a bit|a little) (?:lost|confused|stuck)\b"
    r"|\b(?:taking|takes|took|been|for) forever\b"
    r"|\b(?:makes? no|doesnt make|dont make) sense\b|\bmove on\b|\bwalk me through\b"
)


def _norm(text: str) -> str:
    text = _APOSTROPHES.sub("", text.lower())
    return " ".join(_NON_ALNUM.sub(" ", text).split())


_PATTERN_WORDS = tuple((p, tuple(_norm(p).split())) for p in NON_ATTEMPT_PATTERNS)


def _phrase_spans(words: list[str]) -> list[tuple[str, int, int]]:
    """Every whole-word NON_ATTEMPT_PATTERNS match in `words`: (pattern, start, end)."""
    return [
        (pattern, i, i + len(pw))
        for pattern, pw in _PATTERN_WORDS
        for i in range(len(words) - len(pw) + 1)
        if tuple(words[i : i + len(pw)]) == pw
    ]


def has_non_attempt_phrase(text: str) -> bool:
    """Whether a NON_ATTEMPT_PATTERNS phrase or a _PLEA plea ("no idea", "give
    up", "too hard", "where do I start", …) occurs anywhere in `text`, as whole
    words (lowercase, apostrophes deleted, every other non-alphanumeric run a
    space: "idkfa" is not "idk").

    This is `is_genuine_attempt`'s `matched_non_attempt` (decision (A), fail
    closed): no lexicon decides what else the message says, so "idk man",
    "just tell me, I hate this" and "I dont know how to do this problem" never
    unlock a rung or count toward H6. A hedged answer ("even, idk", "idk maybe
    7") is no genuine attempt either; it is still GRADED (non_attempt_phrases)."""
    norm = _norm(text)
    return bool(_phrase_spans(norm.split()) or _PLEA.search(norm))


def non_attempt_phrases(text: str) -> tuple[str, ...]:
    """The NON_ATTEMPT_PATTERNS (in their order) that route an explicit
    submission away from grading (A16), or () when it is graded (decision (B),
    fail toward grading). Phrases match as in has_non_attempt_phrase.

    - Any digit, or a relation symbol between operands ("F = ma"; an emoticon
      "=(" is not one), anywhere: () — graded.
    - A request phrase ("just tell me", "give me the answer", "what's the
      answer") is returned whatever else the message says; the rest of its
      clause is its object, never an answer. Such a message gets no evidence
      and is never graded ("just tell me, is it 7?" is graded: a digit).
    - An idk phrase ("idk", "i don't know") is returned only when the residue
      is empty: once the phrases, request objects, _PLEA pleas and _NON_ANSWER
      filler are set aside, no word is left. "idk lmao" and "idk, where do I
      start?" are idk; "even, idk" and "the mitochondria idk" are graded.

    A message holding both routes to idk when the idk phrase is returned (the
    route checks idk first, A16)."""
    if _DIGIT.search(text) or _RELATION.search(text):
        return ()
    found: set[str] = set()
    residue: list[str] = []
    for clause in _CLAUSE.split(text):
        words = _norm(clause).split()
        keep = [True] * len(words)
        for pattern, start, end in _phrase_spans(words):
            found.add(pattern)
            if pattern in _REQUEST_PATTERNS:
                end = len(words)
            keep[start:end] = [False] * (end - start)
        residue += _PLEA.sub(" ", " ".join(w for w, k in zip(words, keep) if k)).split()
    idk_holds = all(w in _NON_ANSWER for w in residue)
    return tuple(
        p for p in NON_ATTEMPT_PATTERNS if p in found and (p in _REQUEST_PATTERNS or idk_holds)
    )


def matches_non_attempt(text: str) -> bool:
    """The A16 routing test: `text` is not graded (idk evidence or a hint
    request) — see non_attempt_phrases. It is NEVER `is_genuine_attempt`'s
    argument: pass has_non_attempt_phrase, or a hedged answer would count
    toward hint unlocking."""
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
    blocks grading an explicit submission (A16). `matched_non_attempt` is
    DEFINED as `has_non_attempt_phrase(text)` (never `matches_non_attempt`):
    a phrase or plea anywhere vetoes the attempt, even beside an answer or a
    filled work field, so it fails closed. The caller passes the bool, so only
    gates' text functions see the text."""
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
