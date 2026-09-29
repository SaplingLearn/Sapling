"""Deterministic answer-leak detector + stripper (spec §3.4 LEAK_NGRAM, §13 A34). Pure.

Runs BEFORE any LLM judge on every tutor turn below H6 (research "Guardrails":
the supervisor architecture's deterministic solution stripper). Two rules:

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

- option (owner decision A38, 06 gap): for an mc_reason item whose caller
  passes `correct_option`, that letter as a capital in an option context —
  "(C)", "C)", "option/options/choice/letter C", "answer (is/was/…) C",
  "pick/choose/select/go with C" (keywords any case, an optional ":" or "-",
  and an opening quote or bracket between). A bare capital never counts, so
  the article "A" is no leak when the key is A, and neither is a lowercase
  letter ("option a student picks").

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
from decimal import Decimal, InvalidOperation
from typing import Literal, NamedTuple

from learning import params
from learning.checks import (
    AnswerToken,
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


# The option-context keywords before a letter (owner decision A38, 06 gap).
_OPTION_KEYWORDS = (
    r"options?|choices?|letter"
    r"|answer(?:\s+(?:is|was|would\s+be|should\s+be|must\s+be|has\s+to\s+be))?"
    r"|pick|choose|select|go\s+with"
)


def _option_pattern(correct_option: str | None) -> re.Pattern[str] | None:
    """The compiled option-context rule for the key letter, or None when the
    caller passed no correct_option. ValueError on anything but one ASCII
    letter (case-insensitive: "c" is key C)."""
    if correct_option is None:
        return None
    letter = str(correct_option).strip().upper()
    if not re.fullmatch(r"[A-Z]", letter):
        raise ValueError(f"correct_option {correct_option!r} is not one option letter")
    # group "span" is what the stripper withholds: the letter with its own
    # brackets, never the keyword (the rest of the sentence stays readable).
    return re.compile(
        rf"(?i:\b(?:{_OPTION_KEYWORDS})\b)\s*(?:[:\-]\s*)?[\"'‘“]?(?P<span>\(?{letter}\)?)(?![A-Za-z0-9])"
        rf"|(?<![A-Za-z0-9])(?P<bracket>\(?{letter}\))"
    )


def _option_hits(text: str, option: re.Pattern[str] | None) -> list[tuple[int, int]]:
    if option is None:
        return []
    return [m.span("span") if m.group("span") else m.span("bracket") for m in option.finditer(text)]


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


def _ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)} if n > 0 else set()


def _reference_grams(reference: str) -> tuple[int, set[tuple[str, ...]]]:
    """(n, the reference's n-grams) with n = LEAK_NGRAM; a shorter reference is
    one gram, its whole token run (else a short reference could never leak)."""
    ref = tokens(reference)
    n = min(params.LEAK_NGRAM, len(ref))
    return n, _ngrams(ref, n)


def detect_leak(
    reference_answer: str,
    emitted: str,
    rung: Rung,
    *,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
) -> LeakVerdict:
    """`rung` is the rung the text is served at; at H6 the reference is the
    content (under gates.h6_allowed), so nothing is a leak. `final_answer` is
    the item's decrypted check_items.final_answer and `canonical_answer` its
    decrypted numeric canonical_answer (None for a free item).
    `correct_option` is an mc_reason item's key letter (None otherwise: the
    option rule is off). ValueError on a missing or empty final_answer, or a
    correct_option that is not one letter, at every rung."""
    answer = _answer(final_answer, canonical_answer)
    option = _option_pattern(correct_option)
    if Rung(rung) >= Rung.H6:
        return LeakVerdict(False, "none")
    n, grams = _reference_grams(reference_answer)
    if grams & _ngrams(tokens(emitted), n):
        return LeakVerdict(True, "ngram")
    if _answer_hits(answer_tokens(emitted), answer):
        return LeakVerdict(True, "final_answer")
    if _option_hits(emitted, option):
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


def _strip_segment(
    text: str,
    n: int,
    grams: set[tuple[str, ...]],
    answer: _Answer,
    option: re.Pattern[str] | None = None,
) -> str:
    ascii_spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    words = [text[a:b].lower() for a, b in ascii_spans]
    hits = [
        (ascii_spans[i][0], ascii_spans[i + n - 1][1])
        for i in range(len(words) - n + 1)
        if grams and tuple(words[i : i + n]) in grams
    ]
    toks = answer_tokens(text)
    hits += _answer_hits(toks, answer)
    hits += _option_hits(text, option)
    if not hits:
        return text
    atoms = _atoms(ascii_spans + [(t.start, t.end) for t in toks])
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
    emitted: str,
    reference_answer: str,
    *,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
) -> str:
    """Replace every maximal run of leaked text (an n-gram of the reference, a
    final-answer run, a number of the canonical value, the key letter in an
    option context — `final_answer`, `canonical_answer` and `correct_option`
    as in detect_leak) with WITHHELD, widened to whole
    tokens so no number or word is cut in two, and over the partner of a
    bracket it holds unpaired when only whitespace parts them (a bracket is
    no token, so this withholds nothing the detector reads); the text between
    runs is otherwise untouched. One pass leaves nothing detect_leak(reference_answer, ·, H0,
    final_answer=<same>, canonical_answer=<same>, correct_option=<same>) flags (unless the reference
    or the final answer itself holds the word "withheld"), and a second pass
    is a no-op: existing WITHHELD markers are never re-matched. ValueError on a
    missing or empty final_answer, or a correct_option that is not one letter."""
    answer = _answer(final_answer, canonical_answer)
    option = _option_pattern(correct_option)
    n, grams = _reference_grams(reference_answer)
    return WITHHELD.join(
        _strip_segment(seg, n, grams, answer, option) for seg in emitted.split(WITHHELD)
    )
