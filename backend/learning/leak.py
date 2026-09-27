"""Deterministic answer-leak detector + stripper (spec §3.4 LEAK_NGRAM). Pure.

Runs BEFORE any LLM judge on every tutor turn below H6 (research "Guardrails":
the supervisor architecture's deterministic solution stripper). Two rules:

- ngram: any LEAK_NGRAM consecutive tokens of the reference appear
  consecutively in the emitted text (a reference shorter than LEAK_NGRAM
  tokens: its whole token run, as PKG-04's checks.leak_in_prompt compares);
- final_answer: the reference's final answer (the clause after its last '=';
  else its last standalone number that is not a numbered-step label, an
  exponent or a power's base, so scientific notation gives its mantissa;
  else its last power term, "3x^2"; Markdown emphasis read as its text)
  appears as a consecutive token run, or with every number compared by value
  ("1,250" = "1250", "2.50" = "2.5"), so a reformatted answer still leaks.

Tokens are ASCII alphanumeric runs, lowercased (`[a-z0-9]+` over lowercase for
ASCII text). The stripper tokenizes the same way over the original text, so
whatever it leaves the detector cannot flag.
"""

from __future__ import annotations

import bisect
import re
import string
from typing import Literal, NamedTuple

from learning import params
from learning.ladder import Rung

Detector = Literal["none", "ngram", "final_answer"]
WITHHELD = "[withheld]"

_TOKEN = re.compile(r"[A-Za-z0-9]+")
# A number, a thousands-separated one ("1,250") included; an e-notation
# exponent ("6.022e23") is part of the match, never of the number (group 1).
_STANDALONE_NUMBER = re.compile(
    r"(?<!\w)(?<!\d\.)(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:/\d+)?)"
    r"(?:[eE][-+]?\d+)?(?!\w)(?!\.\d)"
)
# A numbered-step label at the start of a line ("2. Use it", "  3) Solve" — the
# stepwise shape of checks._STEP_LINE — "Step 2: divide", "1.Convert") is not
# an answer. A number alone on its line ("42."), a decimal ("1.5 m") and a
# clock time ("12:30") are.
_STEP_LABEL = re.compile(r"^[ \t]*(?:step[ \t]*)?\d+[.):](?!\d)(?=[ \t]*\S)", re.M | re.I)
# Markdown emphasis ("**42**", "**Final answer:** 1,250", "__42__", "***x***")
# is read as its text. An opener follows no operand and precedes text, a closer
# follows text and precedes no operand, so an exponent "x**2" is never one; the
# span is bounded, so the scan stays linear.
_EMPHASIS = re.compile(
    r"(?<![A-Za-z0-9)\]}*_])(\*\*\*?|_{1,3})(?=[^\s*_])([^\n]{1,240}?)(?<=[^\s*_])\1"
    r"(?![A-Za-z0-9*_])"
)
_STARSTAR = "**"
# The spaces around an exponent operator and just inside brackets carry nothing
# ("4 ^ ( 2 )" is "4^(2)"). Each alternative starts a whitespace run only at its
# first character, so the substitution is linear.
_POWER_SPACE = re.compile(r"(?<![ \t])[ \t]+(?=\^|\*\*|[)\]}])|(?<=[\^(\[{])[ \t]+|(?<=\*\*)[ \t]+")
# Unspaced scientific notation ("6.02x10^23") reads as spaced ("6.02 x 10^23").
_SCI_TIMES = re.compile(r"(?<=\d)[xX](?=10(?:\^|\*\*))")
# What may stand between an exponent operator ("^", "**" touching its base) and
# its exponent: "10^-3", "4^(2)". A number after one is an exponent ("m/s^2",
# "cm^2", "3x^2"), and a number before one is a power's base ("10^23" of
# "6 x 10^23"); neither is the answer.
_EXPONENT_GAP = " \t({[-−+"
_OPERAND_END = frozenset(string.ascii_letters + string.digits + ")]}")
_BASE_OF = re.compile(r"[)\]}]*(?:\^|\*\*)")
_OPERAND_POWER = re.compile(r"[A-Za-z0-9)\]}]\*\*")
_CHUNK = re.compile(r"\S+")
# The final answer ends at the next clause or sentence break: a comma (not a
# thousands separator), a semicolon, "and"/"so", a newline, or sentence
# punctuation that is not a decimal point.
_CLAUSE_BREAK = re.compile(r"(?<!\d),|,(?!\d{3}(?!\d))|[;\n]|\band\b|\bso\b|[.!?](?!\d)", re.I)


# By-value tokens for the final-answer rule: an ASCII number (thousands
# separators and a decimal part included) is one token, compared by value; a
# word is itself. ASCII only, like _TOKEN, so every by-value token lies inside
# the tokens the stripper masks.
_VALUE_TOKEN = re.compile(
    r"([0-9]{1,3}(?:,[0-9]{3})+(?![0-9])(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)|[A-Za-z0-9]+"
)


class LeakVerdict(NamedTuple):
    leaked: bool
    detector: Detector


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _is_exponent(text: str, start: int) -> bool:
    """Whether the number at text[start:] is an exponent: after "^", or after a
    "**" touching its base, across _EXPONENT_GAP."""
    i = start
    while i and text[i - 1] in _EXPONENT_GAP:
        i -= 1
    if text.endswith("^", 0, i):
        return True
    i -= len(_STARSTAR)
    return i > 0 and text.startswith(_STARSTAR, i) and text[i - 1] in _OPERAND_END


def _final_answer_text(reference: str) -> str:
    reference = _EMPHASIS.sub(r"\2", reference)
    if "=" in reference:
        clause = _CLAUSE_BREAK.split(reference.rsplit("=", 1)[1], maxsplit=1)[0]
        if tokens(clause):
            return clause
    text = _SCI_TIMES.sub(" x ", _POWER_SPACE.sub("", _STEP_LABEL.sub(" ", reference)))
    numbers = [
        m.group(1)
        for m in _STANDALONE_NUMBER.finditer(text)
        if not _is_exponent(text, m.start()) and not _BASE_OF.match(text, m.end())
    ]
    if numbers:
        return numbers[-1]
    powers = [
        chunk
        for chunk in _CHUNK.findall(text)
        if ("^" in chunk or _OPERAND_POWER.search(chunk)) and _TOKEN.search(chunk)
    ]
    return powers[-1] if powers else ""


def final_answer(reference: str) -> tuple[str, ...]:
    """Token run of the reference's final answer: the clause after its last '=';
    else its last standalone number that is not a numbered-step label, an
    exponent (after "^" / a "**" touching its base) or a power's base (so
    "6.02 x 10^23" gives its mantissa); else its last whitespace-delimited power
    term ("3x^2", "cos(x^2)", "5^2"); () when it has none. Markdown emphasis
    ("**42**") is read as its text first."""
    return tuple(tokens(_final_answer_text(reference)))


def _number_value(text: str) -> str:
    """A number's canonical spelling: no separators, leading or trailing zeros."""
    whole, _, frac = text.replace(",", "").partition(".")
    whole, frac = whole.lstrip("0") or "0", frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


class _ValueToken(NamedTuple):
    value: str
    start: int
    end: int
    number: bool


def _value_tokens(text: str) -> list[_ValueToken]:
    out = []
    for m in _VALUE_TOKEN.finditer(text):
        number = m.group(1)
        value = _number_value(number) if number else m.group().lower()
        out.append(_ValueToken(value, m.start(), m.end(), bool(number)))
    return out


def _value_run(reference: str) -> tuple[str, ...]:
    return tuple(t.value for t in _value_tokens(_final_answer_text(reference)))


def _ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)} if n > 0 else set()


def _contains_run(haystack: list[str], run: tuple[str, ...]) -> bool:
    return bool(run) and run in _ngrams(haystack, len(run))


def _reference_grams(reference: str) -> tuple[int, set[tuple[str, ...]]]:
    """(n, the reference's n-grams) with n = LEAK_NGRAM; a shorter reference is
    one gram, its whole token run (else a short reference could never leak)."""
    ref = tokens(reference)
    n = min(params.LEAK_NGRAM, len(ref))
    return n, _ngrams(ref, n)


def detect_leak(reference_answer: str, emitted: str, rung: Rung) -> LeakVerdict:
    """`rung` is the rung the text is served at; at H6 the reference is the
    content (under gates.h6_allowed), so nothing is a leak."""
    if Rung(rung) >= Rung.H6:
        return LeakVerdict(False, "none")
    n, grams = _reference_grams(reference_answer)
    em = tokens(emitted)
    if grams & _ngrams(em, n):
        return LeakVerdict(True, "ngram")
    if _contains_run(em, final_answer(reference_answer)) or _contains_run(
        [t.value for t in _value_tokens(emitted)], _value_run(reference_answer)
    ):
        return LeakVerdict(True, "final_answer")
    return LeakVerdict(False, "none")


def _strip_segment(
    text: str,
    n: int,
    grams: set[tuple[str, ...]],
    answer: tuple[str, ...],
    value_run: tuple[str, ...],
) -> str:
    spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    starts = [a for a, _ in spans]
    toks = [text[a:b].lower() for a, b in spans]
    hit = [False] * len(toks)
    for run_len, wanted in (
        (n, grams),
        (len(answer), {answer} if answer else set()),
    ):
        for i in range(len(toks) - run_len + 1):
            if tuple(toks[i : i + run_len]) in wanted:
                hit[i : i + run_len] = [True] * run_len

    def covering(a: int, b: int) -> list[int]:  # the tokens overlapping text[a:b]
        lo = max(bisect.bisect_right(starts, a) - 1, 0)
        return [t for t in range(lo, bisect.bisect_left(starts, b)) if spans[t][1] > a]

    vals = _value_tokens(text)
    k = len(value_run)
    for i in range(len(vals) - k + 1) if k else ():
        run = vals[i : i + k]
        if tuple(t.value for t in run) == value_run:
            for t in covering(run[0].start, run[-1].end):
                hit[t] = True
    # A number is withheld whole or not at all ("1,250" never becomes "1,[withheld]"),
    # so no number is cut in two and nothing left can match by value.
    for v in vals:
        cover = covering(v.start, v.end)
        if v.number and any(hit[t] for t in cover):
            for t in cover:
                hit[t] = True
    out: list[str] = []
    cursor = i = 0
    while i < len(toks):
        if not hit[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(toks) and hit[j + 1]:
            j += 1
        out.append(text[cursor : spans[i][0]])
        out.append(WITHHELD)
        cursor = spans[j][1]
        i = j + 1
    out.append(text[cursor:])
    return "".join(out)


def strip_leak(emitted: str, reference: str) -> str:
    """Replace every maximal run of leaked tokens (an n-gram of the reference or
    its final answer, a number matched by value) with WITHHELD, the text between
    runs untouched; a number touched by a run is withheld whole. One pass
    leaves nothing detect_leak(reference, ·, H0) flags (unless the reference
    itself contains the word "withheld"), and a second pass is a no-op: existing
    WITHHELD markers are never re-matched."""
    n, grams = _reference_grams(reference)
    answer, value_run = final_answer(reference), _value_run(reference)
    return WITHHELD.join(
        _strip_segment(seg, n, grams, answer, value_run) for seg in emitted.split(WITHHELD)
    )
