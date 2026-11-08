"""Attempt, rung, H6 and offer gates (spec §3.3 GATES; §13 A5, A32). Pure.

`has_non_attempt_phrase`, `attempt_content`, `vetoes_attempt`,
`non_attempt_phrases` and `matches_non_attempt` are the ONLY functions in the
policy layer that read student text, and they are fixed phrase and word lists,
never a model. policy.py must not import them (invariant 4). They answer two
questions, each failing in its safe direction:

- hint unlocking and H6: `vetoes_attempt`, FAIL CLOSED for pleas (spec §13
  A120). A phrase or a plea vetoes the attempt only when nothing else in the
  message clears the genuine-attempt bar (`attempt_content`): the phrase, what
  it governs (a request's object, the clause an "I'm not sure" is about),
  question labels and filler never count, so a plea alone is no genuine
  attempt and an answer with a hedge beside it is one. It is
  `is_genuine_attempt`'s `matched_non_attempt`.
- A16 routing of an explicit submission: `non_attempt_phrases`, FAIL TOWARD
  GRADING. idk evidence or a hint request only when nothing in the message
  can be an answer; otherwise it is graded.

Clocks are injected (A5): callers pass `now` / `independent_seconds` as float
seconds, and `time_scale=` (the route layer's `config.LEARNING_GATE_TIME_SCALE`,
default 1.0) scales every GATE_* constant through `params.gate_seconds`.
"""

from __future__ import annotations

import bisect
import math
import re
from typing import get_args

from learning import params
from learning.policy import (
    Band,
    CeilingReason,
    LearnerView,
    StepState,
    ceiling_with_reason,
    independent_gate,
)
from learning.ladder import Rung

NON_ATTEMPT_PATTERNS: tuple[str, ...] = (
    "just tell me",
    "give me the answer",
    "idk",
    "i don't know",
    "what's the answer",
    # Owner decision A38 06(b): two idk variants beyond the spec's five, so a
    # bare "no idea" / "dunno" routes as idk (it already vetoed the attempt
    # through _PLEA).
    "no idea",
    "dunno",
)
# The request phrases: the rest of their clause is what is asked for ("just
# tell me the steps"), never an answer. The others ("idk", "i don't know",
# "no idea", "dunno") are idk phrases (A16): IDK_PATTERNS is what the route
# checks first.
_REQUEST_PATTERNS = frozenset({"just tell me", "give me the answer", "what's the answer"})
IDK_PATTERNS = frozenset(NON_ATTEMPT_PATTERNS) - _REQUEST_PATTERNS

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_APOSTROPHES = re.compile(r"['’‘ʼ`´]")
_BANDS = get_args(Band)
# Clause breaks bound a request phrase's object: sentence and clause
# punctuation, brackets, newlines, and "but". (A digit that survives
# _QUESTION_REF makes the message graded before the split matters, so "1.5"
# and "1,250" need no special case.)
_CLAUSE = re.compile(r"[.,;:!?()\[\]{}\n]|\bbut\b", re.I)
# Any digit is an answer, except the number of the question a request asks
# about.
_DIGIT = re.compile(r"\d")
# A question label ("the answer to question 3", "part 2(b)", "q3", "#3",
# "no. 3", "problems 3-5", "the answer for 4b"): what a request phrase asks
# about, never a submitted answer (A16). Set aside only in a message holding a
# request phrase; beside an idk phrase alone a digit is still an answer.
# Every whitespace run is followed by a REQUIRED token or ends the optional
# group it opens, so no two runs can share the same spaces: a long run with
# no digit after it costs one linear scan, never a cubic backtrack (the text
# is a raw student submission). An all-caps "CH" glued to a digit ("CH4",
# "CH3OH") is a chemical formula, never "chapter N".
_QUESTION_REF = re.compile(
    r"(?:\b(?-i:(?!CH\d))(?:questions?|qs?|parts?|problems?|probs?|numbers?|num|exercises?|ex|items?"
    r"|tasks?|steps?|sections?|sec|pages?|pg|chapters?|ch|hw|homework|labs?|quiz(?:zes)?)"
    r"(?:\s*[.#])?|\bno\s*\.|#|\banswers?\s+(?:to|for|of|on))\s*(?:#\s*)?"
    r"\d+[a-z]?(?:\.\d+[a-z]?)*(?:\s*[-–]\s*\d+[a-z]?)?(?:\s*\(\s*[a-z0-9]{1,4}\s*\))?",
    re.I,
)
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
# The function words in _BARE_ANSWER are the exception: filler beside a help
# word, an answer when a clause holds nothing else (_bare_answer).
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
# Function words that CAN answer an item alone: a yes/no-equivalent auxiliary
# or modal ("it isn't", "it does", "cannot"), a connective ("or", "not"), the
# imaginary unit "i", an article or a lettered option ("a", "an"). All are in
# _NON_ANSWER, so "idk, can I get a hint" stays a plea; a clause made of them
# and _ANSWER_FRAME words only ("it isn't", "I think it is") is an answer.
# "i" answers only as the last word of its part ("it's i"); before another
# word it is the subject ("I think", "I guess I'm stuck"). "so" (a hedge) answers
# after "think"/"guess": "I think so" is a yes.
_BARE_ANSWER = frozenset(
    """
    a an and or not if i is isnt are arent was wasnt were werent do does doesnt
    did didnt dont can cant cannot could couldnt will wont would wouldnt should
    shouldnt have has had havent hasnt might
    """.split()
)
_SUBJECT_I = "i"
_SO = "so"
_SO_AFTER = frozenset({"think", "guess"})
# A subject, a hedge, an intensifier or chat slang around a bare answer: "it
# is", "I think it does", "not really", "it just does", "it will be", "it
# has to", "it isnt lol", "nah it isnt". Every word is in _NON_ANSWER.
_ANSWER_FRAME = frozenset(
    """
    it its itself that thats they them there theres im think guess maybe probably
    perhaps possibly so um umm uh hm hmm well ok okay
    really just actually too though tho be to like literally totally kinda sorta
    also very honestly seriously basically lol man bro bruh dude ngl tbh haha lmao
    xd nah
    """.split()
)
# A first-person statement ("I'm not sure", "I am so lost", "I've no idea")
# starts a new part of a clause for the bare-answer check, so a plea after a
# bare answer ("it isnt im not sure") does not hide it.
_FIRST_PERSON = re.compile(r"\b(?=(?:im|i am|ive)\b)")
# Pleas, matched on normalized text: n-grams that hold a word able to answer
# an item alone ("no", "up", "hard", "start", "hour", "much", "lost", "can't
# do it"), plus the idk variants outside NON_ATTEMPT_PATTERNS ("dunno",
# "don't know"). "I can't do it" followed by a method ("by factoring", "with
# substitution", "using", "via", "without") is worked reasoning, not a plea.
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
    r"|\bi (?:cant|cannot|can not|couldnt) do (?:it|this)\b(?! (?:by|with|using|via|without)\b)"
)


def _norm(text: str) -> str:
    text = _APOSTROPHES.sub("", text.lower())
    return " ".join(_NON_ALNUM.sub(" ", text).split())


_PATTERN_WORDS = tuple((p, tuple(_norm(p).split())) for p in NON_ATTEMPT_PATTERNS)
# The patterns that are also _PLEA pleas ("no idea", "dunno"): non_attempt_phrases
# records them but leaves their words in the clause for the plea rules, so a
# part holding one is never a bare answer ("idk, I have no idea" stays idk).
_PLEA_PATTERNS = frozenset(p for p in NON_ATTEMPT_PATTERNS if _PLEA.fullmatch(_norm(p)))


def _phrase_spans(words: list[str]) -> list[tuple[str, int, int]]:
    """Every whole-word NON_ATTEMPT_PATTERNS match in `words`: (pattern, start, end)."""
    return [
        (pattern, i, i + len(pw))
        for pattern, pw in _PATTERN_WORDS
        for i in range(len(words) - len(pw) + 1)
        if tuple(words[i : i + len(pw)]) == pw
    ]


def _answers_alone(words: list[str], k: int) -> bool:
    """Whether words[k] is a bare answer in its part ("i" only last; "so" only
    after "think"/"guess")."""
    word = words[k]
    if word == _SUBJECT_I:
        return k == len(words) - 1
    if word == _SO:
        return k > 0 and words[k - 1] in _SO_AFTER
    return word in _BARE_ANSWER


def _bare_answer(words: list[str]) -> bool:
    """A clause part that answers the item with function words alone: every
    word a _BARE_ANSWER or _ANSWER_FRAME word, and one of them a bare answer."""
    return any(_answers_alone(words, k) for k in range(len(words))) and all(
        w in _BARE_ANSWER or w in _ANSWER_FRAME for w in words
    )


def _holds_bare_answer(rest: str) -> bool:
    """Whether a clause residue holds a bare answer in some part: parts split
    at a first-person statement, and a part holding a plea ("I give up",
    "can we move on") is never one."""
    return any(
        not _PLEA.search(part) and _bare_answer(part.split()) for part in _FIRST_PERSON.split(rest)
    )


def has_non_attempt_phrase(text: str) -> bool:
    """Whether a NON_ATTEMPT_PATTERNS phrase or a _PLEA plea ("no idea", "give
    up", "too hard", "where do I start", …) occurs anywhere in `text`, as whole
    words (lowercase, apostrophes deleted, every other non-alphanumeric run a
    space: "idkfa" is not "idk").

    Detection only. Since spec §13 A120 a phrase or plea no longer vetoes a
    genuine attempt on its own: `vetoes_attempt` (is_genuine_attempt's
    `matched_non_attempt`) asks what is left of the message beside it."""
    norm = _norm(text)
    return bool(_phrase_spans(norm.split()) or _PLEA.search(norm))


# ── Spec §13 A120: what a hedge leaves of an attempt ───────────────────────
# A phrase or plea vetoes a genuine attempt only when nothing else in the
# message clears the genuine-attempt bar. Hedging is ordinary student language:
# "Separate chaining keeps colliding keys in a list at the slot. I'm not sure
# what the other strategy is called." is an honest partial answer, exactly when
# a hint should unlock, while "idk", "no idea lol" and "I'm not sure, can I have
# a hint?" hold nothing but the plea. Fail closed for pleas: what a phrase or
# plea GOVERNS is part of it, never content — a request's or complaint's object
# (the rest of its clause, as A16 reads a request's), and the embedded clause
# an uncertainty phrase is about ("not sure WHAT the other strategy is called",
# "idk I never learned this", "I don't know THE formula"); question labels and
# filler never count either. An object ends at a guess word ("idk maybe 7",
# "idk I think it's chaining").

#: Words that end what a phrase or plea governs: what follows them is a guess.
_GUESS_WORDS = frozenset(
    "maybe probably perhaps possibly think guess believe suppose assume reckon feel".split()
)
#: An uncertainty phrase ("idk", "not sure", "no idea", "dunno", "no clue")
#: governs what follows it only when that is an embedded clause: one opening —
#: past filler — with a question word or a pronoun subject ("not sure what it
#: is called", "idk I never learned this", "idk lol this makes no sense").
#: Anything else after it is the student's own guess ("idk 7", "idk is it the
#: mitochondria", "not sure if it's 12 N").
_EMBEDDED_OPENERS = frozenset(
    """
    what whats which how hows why where wheres when who whom whose
    i im ive we you youre this that thats these those
    """.split()
)
#: The uncertainty pleas among _PLEA's n-grams; the other pleas are complaints
#: and requests ("too hard", "walk me through", "I'm stuck"), which govern the
#: rest of their clause like a request phrase.
_UNSURE_PLEA = re.compile(r"no (?:idea|clue)|dunno|(?:dont|do not) know|not sure")
#: A "know" phrase takes an object: an article right after it opens one ("I
#: don't know the formula", "idk the answer").
_KNOW_PHRASE = re.compile(r"idk|i dont know|dunno|(?:dont|do not) know")
_KNOW_OBJECT_OPENERS = frozenset({"the", "a", "an"})
#: Words that answer an item only when they stand alone — A16 keeps them out of
#: _NON_ANSWER for that reason (its comment lists them), plus "never", "before",
#: "bad" and "good": "even, idk" and "I think it's in, not sure" hold an answer;
#: "I wasn't in class", "I'm still lost" and "I'm bad at this" hold none.
_ANSWER_ALONE = frozenset(
    """
    even on in some any much still then when hour hours minute minutes start started
    begin up yes no true false hard right both none one bit lot lost solution id us
    impossible forever never before bad good
    """.split()
)
#: What the attempt gate sets aside beside a phrase or plea: _NON_ANSWER plus
#: help, hedge and self-report words A16 keeps (its routing fails toward
#: grading): "one more hint", "I hate this", "never seen this".
_ATTEMPT_FILLER = _NON_ANSWER | frozenset(
    "more believe suppose assume reckon feel hate seen saw heard studied".split()
)
#: What a bare _ANSWER_ALONE answer may stand with: A16's bare-answer and frame
#: words, guess words, articles and prepositions ("at the start", "it's in").
_ALONE_FRAME = (
    _BARE_ANSWER
    | _ANSWER_FRAME
    | _GUESS_WORDS
    | frozenset("the at to of for with from by as about than".split())
)
#: A first-person subject: a part holding one is about the student ("I'm still
#: lost") unless a guess word follows it ("I think it's in").
_SUBJECTS = frozenset({"i", "im", "ive"})


def _plea_spans(words: list[str]) -> list[tuple[int, int, str]]:
    """Every _PLEA match over the joined words as (first word, end word, text)."""
    starts, pos = [], 0
    for word in words:
        starts.append(pos)
        pos += len(word) + 1
    return [
        (
            bisect.bisect_right(starts, m.start()) - 1,
            bisect.bisect_left(starts, m.end()),
            m.group(0),
        )
        for m in _PLEA.finditer(" ".join(words))
    ]


def _kept(words: list[str]) -> list[bool]:
    """Which words of one clause are the student's own (A120): False for every
    NON_ATTEMPT_PATTERNS phrase and _PLEA plea and for what it governs — a
    request's or complaint's object, the rest of its clause; an uncertainty
    phrase's embedded clause, from its opener (an article right after a "know"
    phrase opens its object) — each object ending at the next guess word.
    Linear: one backward pass, then one sweep over the marked ranges."""
    n = len(words)
    next_guess, next_sign = [n] * (n + 1), [n] * (n + 1)
    for k in range(n - 1, -1, -1):
        word = words[k]
        next_guess[k] = k if word in _GUESS_WORDS else next_guess[k + 1]
        significant = (
            word in _EMBEDDED_OPENERS or word in _GUESS_WORDS or word not in _ATTEMPT_FILLER
        )
        next_sign[k] = k if significant else next_sign[k + 1]
    spans = [(s, e, pattern in IDK_PATTERNS) for pattern, s, e in _phrase_spans(words)]
    spans += [(s, e, bool(_UNSURE_PLEA.fullmatch(text))) for s, e, text in _plea_spans(words)]
    marks = [0] * (n + 1)
    for start, end, unsure in spans:
        marks[start] += 1
        marks[end] -= 1
        obj: int | None = end
        if unsure and not (
            end < n
            and words[end] in _KNOW_OBJECT_OPENERS
            and _KNOW_PHRASE.fullmatch(" ".join(words[start:end]))
        ):
            first = next_sign[end]
            obj = first if first < n and words[first] in _EMBEDDED_OPENERS else None
        if obj is not None and obj < next_guess[obj]:
            marks[obj] += 1
            marks[next_guess[obj]] -= 1
    keep, depth = [], 0
    for k in range(n):
        depth += marks[k]
        keep.append(depth == 0)
    return keep


def _alone_answer(words: list[str]) -> bool:
    """A part that answers with _ANSWER_ALONE words standing alone ("even", "at
    the start", "it's in"): every word one of them or _ALONE_FRAME, and no
    first-person subject unless a guess word follows it ("I think it's in"
    answers; "I was lost at the start" does not)."""
    if not any(w in _ANSWER_ALONE for w in words):
        return False
    if not all(w in _ANSWER_ALONE or w in _ALONE_FRAME for w in words):
        return False
    last_guess = max((k for k, w in enumerate(words) if w in _GUESS_WORDS), default=-1)
    return all(w not in _SUBJECTS or k < last_guess for k, w in enumerate(words))


def _parts(words: list[str]) -> list[list[int]]:
    """A clause's word indices, split before a first-person statement ("im",
    "i am", "ive") — A16's _FIRST_PERSON split over words."""
    parts: list[list[int]] = []
    for k, word in enumerate(words):
        starts = word in ("im", "ive") or (word == "i" and "am" in words[k + 1 :][:1])
        if starts or not parts:
            parts.append([])
        parts[-1].append(k)
    return parts


def attempt_content(text: str) -> str:
    """What of `text` counts toward a genuine attempt (spec §3.3, §13 A120).
    With no phrase or plea (has_non_attempt_phrase): the whole stripped text,
    exactly as before A120. With one: its content words, space-joined ("" when
    none) — clause by clause (A16's _CLAUSE split, question labels removed
    first), every word not set aside by `_kept` that is neither
    _ATTEMPT_FILLER nor _ANSWER_ALONE, plus every part (A16's first-person
    split) holding no plea whose kept words are a bare answer: A16's
    `_bare_answer` ("it isn't", "I think so") or `_alone_answer` ("even", "at
    the start"). A digit is a word like any other ("idk 7?"), so it counts
    unless a phrase governs it ("I don't know what 2 + 2 is")."""
    if not has_non_attempt_phrase(text):
        return (text or "").strip()
    return _hedged_content(text)


def _hedged_content(text: str) -> str:
    """attempt_content of a message that holds a phrase or plea."""
    found: list[str] = []
    for clause in _CLAUSE.split(_APOSTROPHES.sub("", _QUESTION_REF.sub(" ", text))):
        words = _norm(clause).split()
        if not words:
            continue
        keep = _kept(words)
        found += [
            w
            for w, kept in zip(words, keep)
            if kept and w not in _ATTEMPT_FILLER and w not in _ANSWER_ALONE
        ]
        in_plea = {k for start, end, _ in _plea_spans(words) for k in range(start, end)}
        for part in _parts(words):
            if in_plea.intersection(part):
                continue  # a part holding a plea is never a bare answer (A16)
            bare = [words[k] for k in part if keep[k]]
            if bare and (_bare_answer(bare) or _alone_answer(bare)):
                found += bare
    return " ".join(found)


def vetoes_attempt(text: str) -> bool:
    """`is_genuine_attempt`'s `matched_non_attempt` (spec §13 A120): True when
    `text` holds a non-attempt phrase or plea and nothing else in it counts
    (`attempt_content` is empty), or when the A16 route would record it as idk
    evidence (an IDK_PATTERNS phrase in `non_attempt_phrases`), so a message
    the route takes as "I don't know" is never an attempt. A plea alone stays
    vetoed ("idk", "no idea lol", "I'm not sure, can I have a hint?", every
    probe plea); a hedge beside an answer does not ("X. I'm not sure what Y
    is called", "the mitochondria idk", "idk maybe 7"). A hedge-free message
    is never vetoed here (the length bar decides it, as before A120)."""
    if not has_non_attempt_phrase(text):
        return False
    if not _hedged_content(text):
        return True
    return any(p in IDK_PATTERNS for p in non_attempt_phrases(text))


def non_attempt_phrases(text: str) -> tuple[str, ...]:
    """The NON_ATTEMPT_PATTERNS (in their order) that route an explicit
    submission away from grading (A16), or () when it is graded (decision (B),
    fail toward grading). Phrases match as in has_non_attempt_phrase.

    - Any digit, or a relation symbol between operands ("F = ma"; an emoticon
      "=(" is not one), anywhere: () — graded. In a message holding a request
      phrase, a question label's number ("the answer to question 3", "part
      2", "the answer for 4b") is no digit: it names what is asked about.
    - A request phrase ("just tell me", "give me the answer", "what's the
      answer") is returned whatever else the message says; the rest of its
      clause is its object, never an answer. Such a message gets no evidence
      and is never graded ("just tell me, is it 7?" is graded: a digit;
      "what's the answer to part 2" is a request).
    - An idk phrase (IDK_PATTERNS: "idk", "i don't know", "no idea",
      "dunno") is returned only when the residue is empty: once the phrases,
      request objects, _PLEA pleas and _NON_ANSWER filler are set aside, no
      word is left, and no part of a clause's
      residue is a bare function-word answer (_BARE_ANSWER, with at most a
      subject, a hedge, an intensifier or chat slang: "it isn't", "or", "I
      think it is", "not really", "it isnt lol", "I think so"; a
      first-person statement starts a new part, so "it isnt im not sure"
      holds one, and a part holding a plea never does). "idk lmao", "idk,
      can I get a hint", "idk, I think" and "idk, where do I start?" are
      idk; "even, idk", "the mitochondria idk" and "it isn't, idk" are
      graded.

    A message holding both routes to idk when the idk phrase is returned (the
    route checks idk first, A16)."""
    if _RELATION.search(text):
        return ()
    found: set[str] = set()
    residue: list[str] = []
    bare = False
    # Apostrophes go before the split, as _norm deletes them over the whole
    # message in has_non_attempt_phrase: "give but`idk" is one word there, so
    # it must be one clause word here (non_attempt_phrases ⇒ has_non_attempt_phrase).
    for clause in _CLAUSE.split(_APOSTROPHES.sub("", text)):
        words = _norm(clause).split()
        keep = [True] * len(words)
        for pattern, start, end in _phrase_spans(words):
            found.add(pattern)
            if pattern in _PLEA_PATTERNS:
                continue
            if pattern in _REQUEST_PATTERNS:
                end = len(words)
            keep[start:end] = [False] * (end - start)
        rest = " ".join(w for w, k in zip(words, keep) if k)
        bare = bare or _holds_bare_answer(rest)
        residue += _PLEA.sub(" ", rest).split()
    if _DIGIT.search(_QUESTION_REF.sub(" ", text) if found & _REQUEST_PATTERNS else text):
        return ()
    idk_holds = not bare and all(w in _NON_ANSWER for w in residue)
    return tuple(
        p for p in NON_ATTEMPT_PATTERNS if p in found and (p in _REQUEST_PATTERNS or idk_holds)
    )


def matches_non_attempt(text: str) -> bool:
    """The A16 routing test: `text` is not graded (idk evidence or a hint
    request) — see non_attempt_phrases. It is NEVER `is_genuine_attempt`'s
    argument: pass vetoes_attempt (spec §13 A120), the fail-closed rule for
    hint unlocking."""
    return bool(non_attempt_phrases(text))


def is_genuine_attempt(
    text_len_chars: int,
    has_shown_work: bool,
    matched_non_attempt: bool,
    independent_seconds: float,
    band: Band,
    *,
    time_scale: float = 1.0,
    variant: str = "A",
) -> bool:
    """Whether an attempt counts toward hint unlocking (spec §3.3). `variant` is
    the concept's within-student arm (PKG-14, `policy.variant_for`); "A" — every
    concept while `loop_arm` is NULL — keeps the §3.3 thresholds. It never
    blocks grading an explicit submission (A16). `matched_non_attempt` is
    DEFINED as `vetoes_attempt(text)` (never `matches_non_attempt`; spec §13
    A120): a phrase or plea vetoes the attempt only when nothing else in the
    text counts (`attempt_content`), so what a hedge leaves must clear the same
    bar a hedge-free attempt clears — some text, or shown work. A plea alone
    fails closed. The caller passes the bool, so only gates' text functions
    see the text."""
    if band not in _BANDS:
        raise ValueError(f"unknown band {band!r}")
    if math.isnan(independent_seconds):
        raise ValueError("independent_seconds is NaN")
    if matched_non_attempt and not has_shown_work:
        return False
    if text_len_chars <= 0 and not has_shown_work:
        return False
    gate = independent_gate(band, variant)  # PKG-14: variant B moves the develop/profic gate
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


def teach_attempt(
    message: str,
    independent_seconds: float | None,
    band: Band,
    *,
    time_scale: float = 1.0,
    variant: str = "A",
) -> bool:
    """PKG-14 (spec §13 A85): whether a teach-phase message counts as a genuine
    attempt for THIS turn's ceiling — the EXISTING rule, is_genuine_attempt with
    vetoes_attempt (the non-attempt list, spec §13 A120: a hedged claim is
    still a claim, a plea alone is none) and the independent-time gate on
    `independent_seconds` (the time since the loop's previous served turn).
    Undecidable (no anchor, NaN, any error) → False: fail closed, no raise."""
    if independent_seconds is None:
        return False
    try:
        return is_genuine_attempt(
            len((message or "").strip()),
            False,
            vetoes_attempt(message or ""),
            independent_seconds,
            band,
            time_scale=time_scale,
            variant=variant,
        )
    except (ValueError, TypeError):
        return False


def teach_turn_ceiling(
    learner: LearnerView,
    message: str,
    independent_seconds: float | None,
    *,
    time_scale: float = 1.0,
    variant: str = "A",
) -> tuple[Rung, CeilingReason]:
    """The ceiling of a teach turn with no active item (A85): the policy's, with
    `teach_attempt` from the existing genuine-attempt rule."""
    attempt = teach_attempt(
        message, independent_seconds, learner.band, time_scale=time_scale, variant=variant
    )
    return ceiling_with_reason(learner, StepState(question_hash=""), teach_attempt=attempt)
