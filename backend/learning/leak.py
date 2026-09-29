"""Deterministic answer-leak detector + stripper (spec §3.4 LEAK_NGRAM, §13 A34). Pure.

Runs BEFORE any LLM judge on every tutor turn below H6 (research "Guardrails":
the supervisor architecture's deterministic solution stripper). Three rules:

- ngram: any LEAK_NGRAM consecutive tokens of the reference appear
  consecutively in the emitted text (a reference shorter than LEAK_NGRAM
  tokens: its whole token run, as PKG-04's checks.leak_in_prompt compares);
- final_answer: the item's STRUCTURED final answer — check_items.final_answer
  (A34), stated by the check-item generator verbatim from its reference and
  decrypted by the caller — occurs as a run of answer tokens
  (checks.answer_tokens: numbers compared by value, whitespace, '**' as '^',
  unicode superscripts, unicode minus, multiplication signs and surrounding
  punctuation normalised), or, for a numeric item, a number with the value of
  its canonical_answer occurs: its mantissa (a sign and an e-notation exponent
  are not part of it), or its full value written in any notation (a number
  with an exponent right after it: "2.5 × 10^-3" and "2.5e-3" are 0.0025).

- option (owner decision A38, 06 gap; A38 fix round M1): for an mc_reason
  item whose caller passes `correct_option`, the key letter in an option
  context, read on an NFKC-decomposed copy with combining marks and format
  characters dropped and look-alikes folded (learning._confusables, the table
  answer_guard reads; "Ｃ", Cyrillic "С" and "C\u200b" are C):
  A38 fix round 4 replaced every word-list reading with position and
  punctuation (the only lists: the option keywords and the closed class of
  copulas/modals):
  1. keyword context — the letter is the pick, any case, whatever follows:
     after "option", "opt.", "choice", "letter", "correct/right option",
     "pick", "choose", "select", "go with", "it's/it is/it was" (a copula
     and separators may come between), and after "answer", "key",
     "correct", "correct/right one" only with a copula/modal ("the answer
     must be A", "so the answer's C") or a punctuation separator ("answer:
     A", "answer => C") between — so "the answer I gave" and "answer A
     works" are clean; after an arrow that starts its clause or follows a
     list of letters ("A/B/C/D → C", never "x → c" or "f(x) -> c").
  2. otherwise, in default mode, only (a) a capital in brackets, quotes or
     emphasis ("(C)", "[C]", "'C'", "**C**"), (b) a capital list label "C)"
     first on its line or after a sentence's end, or (c) a clause-initial
     letter followed by a clause break (":", ".", ",", ";", a dash, the end)
     or a copula/modal ("C is right", "A seems best", "I would …", "C.").
  Never: a letter followed by "+" or "#" ("C++", "C#"), one of an
  enumeration ("(A, B, C)", "a, b or c"). No article or pronoun reading in
  default mode: rule 1 flags "It's A good idea", "Choose a function",
  "Answer: A function maps…" (accepted false positives, structurally a
  pick); rule 2 cannot fire on "A student…", "A base case…", "I think…",
  "What would I expect", "Plan A is the best", "vitamin C".

  `strict=True` (the grader hint, where a false positive only drops a hint)
  adds: EVERY standalone key letter, any case, except a capital "A"/"I"
  before a lowercase word or a lowercase "a"/"i" before any word outside a
  keyword context ("A base case…", "Check whether a stopping rule exists.",
  "What would I expect…" are kept); the key's ordinal position
  ("the third one", "second choice", "the 3rd option" for C);
  the correct option's text (`option_text`) as a run of answer tokens; and,
  when the answer is numeric (its canonical_answer, else the value its
  final_answer states), that value written as a number word ("seven", "one
  hundred and five", "one half", "three quarters"), a LaTeX fraction
  ("\\frac{1}{2}"), a percentage ("50%" or "fifty percent" for 0.5; a plain
  0.5 when the final answer is itself a percentage) or an equivalent fraction
  ("5/10"). A verbal paraphrase ("linear time" for O(n)) is no token rule's
  to catch: the residual is judge_leak's.

The reference is never parsed for a final answer (A34): extracting one from
free text is an unbounded heuristic, and the generator knows the answer, so
it states it. A missing or empty final_answer is a programmer error
(ValueError): callers hold only items that passed selection
(checks.is_servable).

The n-gram rule's tokens are ASCII alphanumeric runs, lowercased. The
stripper widens every leaked span to whole tokens of both tokenizations and
replaces it, so whatever it leaves the detector cannot flag; it also withholds
the partner of a bracket the span holds unpaired when only whitespace parts
the two, so "10^(-3)" or "$6x^{2}$" leaves no stray ")" or "}".
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal, NamedTuple

from learning import _number_words as nw
from learning import params
from learning._confusables import CONFUSABLES
from learning.checks import (
    AnswerToken,
    _stated_value,
    answer_run,
    answer_tokens,
    find_runs,
    number_value,
    written_value,
)
from learning.ladder import Rung

Detector = Literal["none", "ngram", "final_answer", "option"]
WITHHELD = "[withheld]"

_TOKEN = re.compile(r"[A-Za-z0-9]+")
# Bracket pairs a withheld run keeps whole (_paired): no token of either
# tokenization, so masking one never changes what the detector reads.
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {closer: opener for opener, closer in _OPENERS.items()}
# PKG-04's canonical_answer is "one number as plain decimal text" (float()-
# parseable at write time). A sign and an e-notation exponent are not part of
# the matched mantissa (group 1): "-3" matches a "3", "6.022e23" a "6.022";
# the whole match, unsigned, is the magnitude a number written in any
# notation is compared with.
_CANONICAL = re.compile(
    r"[-+]?((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
)


# ── the option rule (owner decision A38, 06 gap; A38 fix round M1) ──────────

# The detection copy the option rule reads: NFKD per character with combining
# marks and format characters (zero-width space, joiners, bidi) dropped, then
# the UTS #39 look-alikes folded to ASCII (the table answer_guard reads). Case
# is kept (a bare capital is no context, so case matters). Per character, so
# every character of the copy maps back to the one it came from.
_LOOKALIKES = str.maketrans(CONFUSABLES)
_DROPPED_CATEGORIES = frozenset({"Mn", "Me", "Cf"})


def _folded(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if ch.isascii():
            piece = ch
        else:
            piece = "".join(
                c
                for c in unicodedata.normalize("NFKD", ch)
                if unicodedata.category(c) not in _DROPPED_CATEGORIES
            ).translate(_LOOKALIKES)
        out.append(piece)
        origin.extend([i] * len(piece))
    return "".join(out), origin


# ── keyword contexts (A38 fix round 4: position and punctuation only) ───────
# The one word list besides the keywords: the closed class of copulas and
# modals that may part a keyword from its letter ("the answer must be A").
_COPULA = (
    r"(?:\s{0,4}'s|\s{1,4}(?:is|was|are|were|would\s+be|should\s+be|must\s+be"
    r"|has\s+to\s+be|will\s+be|might\s+be|could\s+be|can\s+be|seems(?:\s+to\s+be)?))"
)
# Strong keywords: the letter may follow directly ("option C", "choose A over
# B", "go with a"), a copula and punctuation optional.
_STRONG_KEYWORDS = (
    rf"(?:options?|opt\.?|choices?|letters?"
    rf"|(?:correct|right)\s{{1,4}}(?:option|choice|letter)){_COPULA}?"
    r"|pick|choose|select|go\s+with"
    r"|it(?:'s|\s{1,4}(?:is|was|would\s+be|should\s+be|must\s+be))"
)
# Weak keywords need a copula or a punctuation separator before the letter:
# "the answer is A", "answer: A", "so the answer's A" — never "the answer I
# gave" or "answer a smaller question".
_WEAK_KEYWORDS = r"answers?|keys?|correct|(?:correct|right)\s{1,4}(?:one|answer)"
_PUNCTUATION_SEPARATOR = r"\s{0,4}[:=>\-–—→⇒][\s:=>\-–—→⇒]{0,11}"
_NOT_ALNUM_BEFORE = r"(?<![A-Za-z0-9])"
# After the letter: no letter or digit, and no "+" or "#" ("C++", "C#").
_NOT_ALNUM_AFTER = r"(?![A-Za-z0-9+#])"
# An enumeration of letters is no pick of one ("(A, B, C)", "a, b or c"):
# neither a letter an enumeration continues after, nor (_enumerated) one it
# reaches.
_NOT_ENUM_AFTER = (
    r"(?![\"'`)\]*_]{0,4}\s{0,2}[,/|]\s{0,2}[\"'`(\[*_]{0,4}[A-Za-z](?![A-Za-z0-9]))"
    r"(?!\s{1,3}(?:or|and|/)\s{1,3}[A-Za-z](?![A-Za-z0-9]))"
)
# A masked token (_MASKED) may have been a letter: after a strip, the letter
# it parted from another keeps its enumeration reading, so a second pass
# finds nothing new.
_ENUM_BEFORE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]|x{%d})[\"'`)\]*_]{0,4}\s{0,2}(?:[,/|]|\s(?:or|and))"
    r"\s{0,2}[\"'`(\[*_]{0,4}$" % len(WITHHELD)
)
# What may part a keyword from its letter: separators, then opening markup.
# Bounded and disjoint, so no pattern backtracks more than a few characters.
_SEPARATORS = r"[\s:=>\-–—→⇒]{0,12}"
_OPENING = r"[\"'`(\[*_#]{0,4}"
_CLOSING = r"[\"'`)\]*_]{0,4}"
_ARROW = r"(?:→|⇒|=>|->)"
# The letter starts its clause: the text's start, or only spaces and opening
# markup after punctuation — never a word, a closing bracket or a math
# operator ("Plan A is the best", "x → c", "f(x) -> c", "x = c").
_CLAUSE_START = r"(?:(?<![\s\S])|(?<=[^\sA-Za-z0-9\"'`(\[*_#)\]}<>=+\-/^~|→⇒]))\s{0,4}"
# After a clause-initial letter: a clause break (":", ".", ",", ";", "!",
# "?", a dash, the end) or a copula/modal ("C is", "A seems", "I would").
_CLAUSE_BREAK = r"\s{0,4}(?:[:,;!?—–]|\.(?![A-Za-z0-9])|$)"
_CLAUSE_VERB = (
    r"(?:'s|\s{1,4}(?:is|was|would|should|must|seems|could|might|will|can)(?![A-Za-z0-9]))"
)
# A list of option letters before an arrow ("A/B/C/D → C").
_LETTER_LIST = r"(?<![A-Za-z0-9])[A-Z](?:\s{0,2}[/,|]\s{0,2}[A-Z]){1,25}(?![A-Za-z0-9])\s{0,4}"
_POSITION_NOUNS = r"one|option|choice|answer|letter"
# Strict mode's one exemption: a capital A/I before a lowercase word, or a
# lowercase a/i before any word, outside a keyword context ("A base case…",
# "I think…", "Check whether a stopping rule exists.").
_ARTICLE_AFTER = {True: re.compile(r"\s{1,8}[a-z]"), False: re.compile(r"\s{1,8}[A-Za-z]")}


def _enumerated(text: str, start: int) -> bool:
    """The letter at `start` continues an enumeration ("A, B", "b or c")."""
    return bool(_ENUM_BEFORE.search(text, max(0, start - params.LEAK_ENUM_LOOKBACK_CHARS), start))


class _OptionRule(NamedTuple):
    context: tuple[re.Pattern[str], ...]  # group "span" (or the whole match) is withheld
    label: re.Pattern[str]  # "C)" as a list label, never "(see part C)"
    standalone: re.Pattern[str]  # strict mode: any standalone key letter
    position: re.Pattern[str] | None  # strict mode: "the third one" for key C
    article: bool  # the key is A or I: strict mode's article/pronoun exemption


def _position_pattern(index: int) -> re.Pattern[str] | None:
    """Strict mode: the key's position by ordinal ("the third option",
    "second choice", "the 3rd one"); None past the listed ordinals."""
    if index >= len(nw.ORDINALS):
        return None
    ordinal = f"{nw.ORDINALS[index]}|{index + 1}{nw.ORDINAL_SUFFIXES[index]}"
    return re.compile(rf"(?i:\b(?:{ordinal})\s{{1,4}}(?:{_POSITION_NOUNS})s?\b)")


def _option_rule(correct_option: str | None) -> _OptionRule | None:
    """The compiled option rules for the key letter, or None when the caller
    passed no correct_option. ValueError on anything but one ASCII letter
    (case-insensitive: "c" is key C)."""
    if correct_option is None:
        return None
    upper = str(correct_option).strip().upper()
    if not re.fullmatch(r"[A-Z]", upper):
        raise ValueError(f"correct_option {correct_option!r} is not one option letter")
    lower = upper.lower()
    letter = f"[{upper}{lower}]"
    b, a, e = _NOT_ALNUM_BEFORE, _NOT_ALNUM_AFTER, _NOT_ENUM_AFTER
    pick = rf"{_OPENING}(?P<span>{letter}){a}{e}"
    context = (
        # 1. keyword context: the letter is the pick, whatever follows it
        re.compile(rf"(?i:{b}(?:{_STRONG_KEYWORDS})(?![A-Za-z0-9])){_SEPARATORS}{pick}"),
        re.compile(
            rf"(?i:{b}(?:{_WEAK_KEYWORDS})(?:{_COPULA}{_SEPARATORS}|{_PUNCTUATION_SEPARATOR}))"
            rf"{pick}"
        ),
        # an arrow that starts its clause or follows a list of letters
        re.compile(rf"(?:{_CLAUSE_START}|{_LETTER_LIST}){_ARROW}\s{{0,4}}{pick}"),
        # 2a. a capital inside brackets, quotes or emphasis
        re.compile(rf"{b}(?:\(\s?{upper}\s?\)|\[\s?{upper}\s?\])(?![+#])"),
        re.compile(rf"{b}([\"'`]){upper}\1(?![A-Za-z0-9\"'`+#])"),
        re.compile(rf"(?<![A-Za-z0-9*_])(\*{{1,2}}|_{{1,2}}){upper}\1(?![A-Za-z0-9*_+#])"),
        # 2c. clause-initial, then a clause break or a copula/modal
        re.compile(
            rf"{_CLAUSE_START}{_OPENING}(?P<span>{letter}){a}{e}{_CLOSING}"
            rf"(?:{_CLAUSE_BREAK}|(?i:{_CLAUSE_VERB}))"
        ),
    )
    # 2b. a list label: "C)" first on its line or right after a sentence's end
    label = re.compile(rf"(?:(?<=[\n.;:!?])|(?<![\s\S]))[ \t]{{0,4}}(?P<span>{upper}\))")
    standalone = re.compile(rf"{b}{letter}(?![A-Za-z0-9])")
    position = _position_pattern(ord(upper) - ord("A"))
    return _OptionRule(context, label, standalone, position, upper in "AI")


# A WITHHELD marker reads as one lowercase word: what the stripper masked was
# a token, so the letters around a marker keep the context they had ("9.8(A)"
# is no bracketed "(A)", and "a [withheld]" keeps its article reading).
_MASKED = "x" * len(WITHHELD)


def _folded_token_spans(text: str) -> list[tuple[int, int]]:
    """The spans (in `text`) of the alphanumeric runs the option rule reads."""
    folded, origin = _folded(text)
    return [(origin[m.start()], origin[m.end() - 1] + 1) for m in _TOKEN.finditer(folded)]


def _option_hits(
    text: str, option: _OptionRule | None, *, strict: bool = False
) -> list[tuple[int, int]]:
    """The spans (in `text`) of the key letter in an option context — any
    standalone key letter too when `strict` — read on the folded copy, where
    every WITHHELD marker reads as one lowercase word (_MASKED).
    strip_leak reads it on the WHOLE text, markers and all, as detect_leak
    does, so the two always agree."""
    if option is None:
        return []
    folded, origin = _folded(text)
    folded = folded.replace(WITHHELD, _MASKED)
    found: list[tuple[int, int]] = []
    for pattern in option.context:
        for m in pattern.finditer(folded):
            if "span" in pattern.groupindex:
                if not _enumerated(folded, m.start("span")):
                    found.append(m.span("span"))
            else:
                found.append(m.span())
    found += [m.span("span") for m in option.label.finditer(folded)]
    if strict:
        for m in option.standalone.finditer(folded):
            # 3. every standalone key letter but the article/pronoun reading
            # (a keyword context was flagged above, whatever follows it)
            if option.article and _ARTICLE_AFTER[m.group().isupper()].match(folded, m.end()):
                continue
            found.append(m.span())
        if option.position is not None:
            found += [m.span() for m in option.position.finditer(folded)]
    return [(origin[start], origin[end - 1] + 1) for start, end in found if end > start]


class LeakVerdict(NamedTuple):
    leaked: bool
    detector: Detector


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class _Answer(NamedTuple):
    run: tuple[str, ...]  # the final answer as answer-token values
    canonical: str | None  # the canonical_answer's mantissa, when it is a number
    magnitude: Decimal | None  # the canonical_answer's full value, unsigned


def _canonical_value(canonical_answer: str | None) -> tuple[str | None, Decimal | None]:
    if canonical_answer is None:
        return None, None
    m = _CANONICAL.fullmatch(str(canonical_answer).strip())
    if not m:
        return None, None
    try:
        magnitude = abs(Decimal(m.group(0).replace(",", "")))
    except InvalidOperation:
        magnitude = None
    return number_value(m.group(1)), magnitude


def _answer(final_answer: str | None, canonical_answer: str | None) -> _Answer:
    if not isinstance(final_answer, str):
        raise ValueError("final_answer is required (A34): pass the item's decrypted final_answer")
    run = answer_run(final_answer)
    if not run:
        raise ValueError(f"final_answer {final_answer!r} holds no answer token (A34)")
    return _Answer(run, *_canonical_value(canonical_answer))


def _answer_hits(toks: list[AnswerToken], answer: _Answer) -> list[tuple[int, int]]:
    """The spans of every final-answer run in `toks` and, for a numeric item,
    of every number with the canonical mantissa, of every number whose written
    value (its exponent included, spanned too) is the canonical value, and of
    every number that is that value without its exponent."""
    values = [t.value for t in toks]
    k = len(answer.run)
    hits = [(toks[i].start, toks[i + k - 1].end) for i in find_runs(values, answer.run)]
    if answer.canonical is not None:
        hits += [(t.start, t.end) for t in toks if t.number and t.value == answer.canonical]
    if answer.magnitude is not None:
        for i, t in enumerate(toks):
            if not t.number:
                continue
            value, last = written_value(values, i)
            if value == answer.magnitude:
                hits.append((t.start, toks[last].end))
            elif Decimal(t.value) == answer.magnitude:
                # The bare number counts too, whatever exponent follows it (as
                # the mantissa rule does): masking can only cut an exponent
                # off a number, never add one, so what the stripper leaves is
                # clean.
                hits.append((t.start, t.end))
    return hits


# ── strict mode: a numeric answer's value in other notations (A38 fix round, m7) ──

_WORD = re.compile(r"[A-Za-z]+")
_WORD_GAP = re.compile(r"[\s-]{1,4}")
_LATEX_FRACTION = re.compile(
    r"\\[dt]?frac\s{0,4}\{\s{0,4}(?P<num>[0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,4}\}"
    r"\s{0,4}\{\s{0,4}(?P<den>[0-9]{1,12}(?:\.[0-9]{1,12})?)\s{0,4}\}"
)


class _Numeric(NamedTuple):
    value: Fraction  # the answer's magnitude
    percent: bool  # the final answer is itself a percentage


def _numeric(final_answer: str, answer: _Answer) -> _Numeric | None:
    """The numeric answer strict mode compares against: the canonical_answer's
    magnitude, else the value the final answer states; None for a free answer."""
    toks = answer_tokens(final_answer)
    percent = any(t.value in ("%", "percent") for t in toks)
    if answer.magnitude is not None:
        return _Numeric(Fraction(answer.magnitude), percent)
    try:
        stated = _stated_value(toks)
    except (ArithmeticError, ValueError):
        return None
    return None if stated is None else _Numeric(abs(Fraction(stated)), percent)


class _Word(NamedTuple):
    text: str  # lowercased
    start: int
    end: int


def _integer_phrase(words: list[_Word], i: int, text: str) -> tuple[int, int]:
    """(index after, value) of the number-word phrase starting at words[i]
    ("seven", "twenty-five", "one hundred and five"); index i when none."""
    total = current = 0
    j = i
    last = ""  # "unit" | "tens" | "scale"
    while j < len(words):
        w = words[j].text
        if j > i and not _WORD_GAP.fullmatch(text[words[j - 1].end : words[j].start]):
            break
        if w == "and" and last == "scale" and j + 1 < len(words):
            nxt = words[j + 1].text
            if nxt in nw.UNITS or nxt in nw.TENS:
                j += 1
                continue
            break
        if w in nw.UNITS and last in ("", "tens", "scale"):
            if last == "tens" and nw.UNITS[w] >= nw.TEN:
                break
            current += nw.UNITS[w]
            last = "unit"
        elif w in nw.TENS and last in ("", "scale"):
            current += nw.TENS[w]
            last = "tens"
        elif w in nw.SCALES and last in ("unit", "tens"):
            scale = nw.SCALES[w]
            if scale == nw.HUNDRED:
                current *= nw.HUNDRED
            else:
                total += current * scale
                current = 0
            last = "scale"
        else:
            break
        j += 1
    return j, total + current


def _number_word_values(text: str) -> list[tuple[Fraction, int, int]]:
    """Every number written in words in `text`, with its span: integers,
    fractions ("one half", "a quarter", "three quarters", a bare "half") and
    percentages ("fifty percent" is 0.5; its integer 50 counts too)."""
    words = [_Word(m.group().lower(), m.start(), m.end()) for m in _WORD.finditer(text)]
    out: list[tuple[Fraction, int, int]] = []

    def next_is(k: int, table) -> bool:
        """words[k] exists, is in `table`, and only a word gap parts it from words[k-1]."""
        return (
            k < len(words)
            and words[k].text in table
            and bool(_WORD_GAP.fullmatch(text[words[k - 1].end : words[k].start]))
        )

    i = 0
    while i < len(words):
        word = words[i]
        j, value = _integer_phrase(words, i, text)
        if j == i:
            if word.text in ("a", "an") and next_is(i + 1, nw.DENOMINATORS):
                denominator = words[i + 1]
                out.append(
                    (Fraction(1, nw.DENOMINATORS[denominator.text]), word.start, denominator.end)
                )
                i += 1
            elif word.text in nw.HALF_WORDS:
                out.append((Fraction(1, nw.DENOMINATORS[word.text]), word.start, word.end))
            i += 1
            continue
        if next_is(j, nw.DENOMINATORS):
            denominator = words[j]
            out.append(
                (Fraction(value, nw.DENOMINATORS[denominator.text]), word.start, denominator.end)
            )
            i = j + 1
            continue
        out.append((Fraction(value), word.start, words[j - 1].end))
        if next_is(j, nw.PERCENT_WORDS):
            out.append((Fraction(value, nw.PERCENT), word.start, words[j].end))
        i = j
    return out


def _numeric_hits(
    text: str, toks: list[AnswerToken], numeric: _Numeric | None
) -> list[tuple[int, int]]:
    """Strict mode: the spans where `text` writes the numeric answer's value
    as a number word, a LaTeX fraction, a percentage or a fraction a/b."""
    if numeric is None:
        return []
    target = numeric.value
    hits = [(a, b) for value, a, b in _number_word_values(text) if value == target]
    for m in _LATEX_FRACTION.finditer(text):
        denominator = Fraction(m.group("den"))
        if denominator and Fraction(m.group("num")) / denominator == target:
            hits.append(m.span())
    for t, nxt in zip(toks, toks[1:]):
        if t.number and nxt.value in ("%", "percent") and Fraction(t.value) / nw.PERCENT == target:
            hits.append((t.start, nxt.end))
    rest = toks[1:]
    for t, slash, den in zip(toks, rest, rest[1:]):
        if t.number and slash.value == "/" and den.number and Fraction(den.value):
            if Fraction(t.value) / Fraction(den.value) == target:
                hits.append((t.start, den.end))
    if numeric.percent:
        hits += [
            (t.start, t.end) for t in toks if t.number and Fraction(t.value) * nw.PERCENT == target
        ]
    return hits


class _Rules(NamedTuple):
    """Everything one detect/strip call checks, built once per call."""

    grams: set[tuple[str, ...]]
    n: int
    answer: _Answer
    option: _OptionRule | None
    strict: bool
    option_run: tuple[str, ...]  # strict: the correct option's text as answer tokens
    numeric: _Numeric | None  # strict: the numeric answer's value


def _rules(
    reference: str,
    final_answer: str,
    canonical_answer: str | None,
    correct_option: str | None,
    strict: bool,
    option_text: str | None,
) -> _Rules:
    answer = _answer(final_answer, canonical_answer)
    option = _option_rule(correct_option)
    n, grams = _reference_grams(reference)
    option_run = answer_run(option_text) if strict and option_text else ()
    numeric = _numeric(final_answer, answer) if strict else None
    return _Rules(grams, n, answer, option, strict, option_run, numeric)


def _final_hits(text: str, toks: list[AnswerToken], rules: _Rules) -> list[tuple[int, int]]:
    hits = _answer_hits(toks, rules.answer)
    if rules.strict:
        hits += _numeric_hits(text, toks, rules.numeric)
    return hits


def _option_text_hits(toks: list[AnswerToken], rules: _Rules) -> list[tuple[int, int]]:
    hits: list[tuple[int, int]] = []
    if rules.option_run:
        k = len(rules.option_run)
        values = [t.value for t in toks]
        hits += [(toks[i].start, toks[i + k - 1].end) for i in find_runs(values, rules.option_run)]
    return hits


def _ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)} if n > 0 else set()


def _reference_grams(reference: str) -> tuple[int, set[tuple[str, ...]]]:
    """(n, the reference's n-grams) with n = LEAK_NGRAM; a shorter reference is
    one gram, its whole token run (else a short reference could never leak)."""
    ref = tokens(reference)
    n = min(params.LEAK_NGRAM, len(ref))
    return n, _ngrams(ref, n)


def detect_leak(
    *,
    reference: str,
    emitted: str,
    rung: Rung,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
    strict: bool = False,
    option_text: str | None = None,
) -> LeakVerdict:
    """Every parameter is keyword-only (A38 fix round, m6): detect_leak and
    strip_leak name `reference` and `emitted` in opposite orders, so a
    positional call could swap them silently. `reference` is the item's
    decrypted reference answer. `rung` is the rung the text is served at; at
    H6 the reference is the content (under gates.h6_allowed), so nothing is a
    leak. `final_answer` is the item's decrypted check_items.final_answer and
    `canonical_answer` its decrypted numeric canonical_answer (None for a free
    item). `correct_option` is an mc_reason item's key letter (None otherwise:
    the option rule is off). `strict` is the grader hint's mode (see the
    module docstring): any standalone key letter, `option_text` (the correct
    option's text; ignored unless strict) and a numeric answer's other
    notations leak too. ValueError on a missing or empty final_answer, or a
    correct_option that is not one letter, at every rung."""
    rules = _rules(reference, final_answer, canonical_answer, correct_option, strict, option_text)
    if Rung(rung) >= Rung.H6:
        return LeakVerdict(False, "none")
    if rules.grams & _ngrams(tokens(emitted), rules.n):
        return LeakVerdict(True, "ngram")
    toks = answer_tokens(emitted)
    if _final_hits(emitted, toks, rules):
        return LeakVerdict(True, "final_answer")
    if _option_hits(emitted, rules.option, strict=rules.strict) or _option_text_hits(toks, rules):
        return LeakVerdict(True, "option")
    return LeakVerdict(False, "none")


def _atoms(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Disjoint, sorted unions of overlapping token spans: masking a whole
    atom never leaves part of a token of either tokenization ("1,250" is one
    number but two ASCII tokens; "6x" one ASCII token but two answer tokens)."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _paired(text: str, start: int, end: int) -> tuple[int, int]:
    """The run text[start:end] widened over the partners of the brackets it
    holds unpaired: a closer right after it (whitespace aside) for each opener
    left open, innermost first, and an opener right before it for each closer
    with no opener inside, so "10^(-3" takes its ")" and "x-3)^2" its "(".
    Brackets and whitespace are no token of either tokenization, so the
    widened run withholds no more of what the detector reads."""
    opened: list[str] = []
    unopened: list[str] = []
    for ch in text[start:end]:
        if ch in _OPENERS:
            opened.append(ch)
        elif ch in _CLOSERS:
            if opened and opened[-1] == _CLOSERS[ch]:
                opened.pop()
            elif not opened:
                unopened.append(ch)
    for opener in reversed(opened):
        at = end
        while at < len(text) and text[at].isspace():
            at += 1
        if at == len(text) or text[at] != _OPENERS[opener]:
            break
        end = at + 1
    for closer in unopened:
        at = start
        while at > 0 and text[at - 1].isspace():
            at -= 1
        if at == 0 or text[at - 1] != _CLOSERS[closer]:
            break
        start = at - 1
    return start, end


def _strip_segment(text: str, rules: _Rules, option_hits: list[tuple[int, int]]) -> str:
    """`option_hits`: the option rule's hits in this segment, read on the whole text."""
    n, grams = rules.n, rules.grams
    ascii_spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    words = [text[a:b].lower() for a, b in ascii_spans]
    hits = [
        (ascii_spans[i][0], ascii_spans[i + n - 1][1])
        for i in range(len(words) - n + 1)
        if grams and tuple(words[i : i + n]) in grams
    ]
    toks = answer_tokens(text)
    hits += _final_hits(text, toks, rules)
    hits += option_hits + _option_text_hits(toks, rules)
    if not hits:
        return text
    spans = ascii_spans + [(t.start, t.end) for t in toks]
    if rules.option is not None:
        # the option rule's own tokens too: "A¹" folds to one token "A1", so
        # masking its "¹" alone would expose a standalone "A"
        spans += _folded_token_spans(text)
    atoms = _atoms(spans)
    starts = [a for a, _ in atoms]

    def widen(start: int, end: int) -> tuple[int, int]:
        lo = max(bisect.bisect_right(starts, start) - 1, 0)
        hi = bisect.bisect_left(starts, end)
        covered = [atoms[i] for i in range(lo, hi) if atoms[i][1] > start]
        return min([start] + [a for a, _ in covered]), max([end] + [b for _, b in covered])

    # Maximal runs: widened hits that overlap, or that only separators part
    # (no token between them), become ONE marker; the text between runs stays.
    runs: list[tuple[int, int]] = []
    for start, end in sorted(widen(a, b) for a, b in hits):
        if runs:
            nxt = bisect.bisect_left(starts, runs[-1][1])
            if start <= runs[-1][1] or nxt >= len(starts) or starts[nxt] >= start:
                runs[-1] = (runs[-1][0], max(runs[-1][1], end))
                continue
        runs.append((start, end))
    out: list[str] = []
    cursor = 0
    # Widening a run over bracket partners never reaches another run: runs
    # that only separators part were merged above, so a token parts them.
    for start, end in (_paired(text, a, b) for a, b in runs):
        out.append(text[cursor:start])
        out.append(WITHHELD)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def strip_leak(
    *,
    emitted: str,
    reference: str,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
    strict: bool = False,
    option_text: str | None = None,
) -> str:
    """Replace every maximal run of leaked text (an n-gram of the reference, a
    final-answer run, a number of the canonical value, the key letter in an
    option context; in strict mode also any standalone key letter, the
    option text and a numeric answer's other notations — every parameter as
    in detect_leak) with WITHHELD, widened to whole
    tokens so no number or word is cut in two, and over the partner of a
    bracket it holds unpaired when only whitespace parts them (a bracket is
    no token, so this withholds nothing the detector reads); the text between
    runs is otherwise untouched. One pass leaves nothing detect_leak(reference=<same>,
    emitted=·, rung=H0, <every other parameter the same>) flags (unless the
    reference or the final answer itself holds the word "withheld"), and a
    second pass is a no-op: existing WITHHELD markers are never re-matched.
    ValueError on a missing or empty final_answer, or a correct_option that is
    not one letter."""
    rules = _rules(reference, final_answer, canonical_answer, correct_option, strict, option_text)
    option_hits = _option_hits(emitted, rules.option, strict=rules.strict)
    out: list[str] = []
    offset = 0
    for seg in emitted.split(WITHHELD):
        end = offset + len(seg)
        local = [(a - offset, b - offset) for a, b in option_hits if offset <= a and b <= end]
        out.append(_strip_segment(seg, rules, local))
        offset = end + len(WITHHELD)
    return WITHHELD.join(out)
