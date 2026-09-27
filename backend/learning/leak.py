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
  its canonical_answer occurs.

The reference is never parsed for a final answer (A34): extracting one from
free text is an unbounded heuristic, and the generator knows the answer, so
it states it. A missing or empty final_answer is a programmer error
(ValueError): callers hold only items that passed selection
(checks.is_servable).

The n-gram rule's tokens are ASCII alphanumeric runs, lowercased. The
stripper widens every leaked span to whole tokens of both tokenizations and
replaces it, so whatever it leaves the detector cannot flag.
"""

from __future__ import annotations

import bisect
import re
from typing import Literal, NamedTuple

from learning import params
from learning.checks import AnswerToken, answer_run, answer_tokens, find_runs, number_value
from learning.ladder import Rung

Detector = Literal["none", "ngram", "final_answer"]
WITHHELD = "[withheld]"

_TOKEN = re.compile(r"[A-Za-z0-9]+")
# PKG-04's canonical_answer is "one number as plain decimal text" (float()-
# parseable at write time). A sign and an e-notation exponent are not part of
# the matched value (group 1): "-3" matches a "3", "6.022e23" a "6.022".
_CANONICAL = re.compile(
    r"[-+]?((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
)


class LeakVerdict(NamedTuple):
    leaked: bool
    detector: Detector


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class _Answer(NamedTuple):
    run: tuple[str, ...]  # the final answer as answer-token values
    canonical: str | None  # the canonical_answer's value, when it is a number


def _canonical_value(canonical_answer: str | None) -> str | None:
    if canonical_answer is None:
        return None
    m = _CANONICAL.fullmatch(str(canonical_answer).strip())
    return number_value(m.group(1)) if m else None


def _answer(final_answer: str | None, canonical_answer: str | None) -> _Answer:
    if not isinstance(final_answer, str):
        raise ValueError("final_answer is required (A34): pass the item's decrypted final_answer")
    run = answer_run(final_answer)
    if not run:
        raise ValueError(f"final_answer {final_answer!r} holds no answer token (A34)")
    return _Answer(run, _canonical_value(canonical_answer))


def _answer_hits(toks: list[AnswerToken], answer: _Answer) -> list[tuple[int, int]]:
    """The spans of every final-answer run in `toks` and, for a numeric item,
    of every number with the canonical value."""
    values = [t.value for t in toks]
    k = len(answer.run)
    hits = [(toks[i].start, toks[i + k - 1].end) for i in find_runs(values, answer.run)]
    if answer.canonical is not None:
        hits += [(t.start, t.end) for t in toks if t.number and t.value == answer.canonical]
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
) -> LeakVerdict:
    """`rung` is the rung the text is served at; at H6 the reference is the
    content (under gates.h6_allowed), so nothing is a leak. `final_answer` is
    the item's decrypted check_items.final_answer and `canonical_answer` its
    decrypted numeric canonical_answer (None for a free item). ValueError on a
    missing or empty final_answer, at every rung."""
    answer = _answer(final_answer, canonical_answer)
    if Rung(rung) >= Rung.H6:
        return LeakVerdict(False, "none")
    n, grams = _reference_grams(reference_answer)
    if grams & _ngrams(tokens(emitted), n):
        return LeakVerdict(True, "ngram")
    if _answer_hits(answer_tokens(emitted), answer):
        return LeakVerdict(True, "final_answer")
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


def _strip_segment(text: str, n: int, grams: set[tuple[str, ...]], answer: _Answer) -> str:
    ascii_spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    words = [text[a:b].lower() for a, b in ascii_spans]
    hits = [
        (ascii_spans[i][0], ascii_spans[i + n - 1][1])
        for i in range(len(words) - n + 1)
        if grams and tuple(words[i : i + n]) in grams
    ]
    toks = answer_tokens(text)
    hits += _answer_hits(toks, answer)
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
    for start, end in runs:
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
) -> str:
    """Replace every maximal run of leaked text (an n-gram of the reference, a
    final-answer run, a number of the canonical value — `final_answer` and
    `canonical_answer` as in detect_leak) with WITHHELD, widened to whole
    tokens so no number or word is cut in two; the text between runs is
    untouched. One pass leaves nothing detect_leak(reference_answer, ·, H0,
    final_answer=<same>, canonical_answer=<same>) flags (unless the reference
    or the final answer itself holds the word "withheld"), and a second pass
    is a no-op: existing WITHHELD markers are never re-matched. ValueError on a
    missing or empty final_answer."""
    answer = _answer(final_answer, canonical_answer)
    n, grams = _reference_grams(reference_answer)
    return WITHHELD.join(_strip_segment(seg, n, grams, answer) for seg in emitted.split(WITHHELD))
