"""Deterministic answer-leak detector + stripper (spec §3.4 LEAK_NGRAM). Pure.

Runs BEFORE any LLM judge on every tutor turn below H6 (research "Guardrails":
the supervisor architecture's deterministic solution stripper). Two rules:

- ngram: any LEAK_NGRAM consecutive tokens of the reference appear
  consecutively in the emitted text (a reference shorter than LEAK_NGRAM
  tokens: its whole token run, as PKG-04's checks.leak_in_prompt compares);
- final_answer: the reference's final answer (the clause after its last '=',
  else its last standalone number that is not a numbered-step label) appears
  as a consecutive token run.

Tokens are ASCII alphanumeric runs, lowercased (`[a-z0-9]+` over lowercase for
ASCII text). The stripper tokenizes the same way over the original text, so
whatever it leaves the detector cannot flag.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

from learning import params
from learning.ladder import Rung

Detector = Literal["none", "ngram", "final_answer"]
WITHHELD = "[withheld]"

_TOKEN = re.compile(r"[A-Za-z0-9]+")
# A number, a thousands-separated one ("1,250") included.
_STANDALONE_NUMBER = re.compile(
    r"(?<!\w)(?<!\d\.)(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:/\d+)?)(?!\w)(?!\.\d)"
)
# A numbered-step label at the start of a line ("2. Use it", "  3) Solve" — the
# stepwise shape of checks._STEP_LINE — "Step 2: divide", "1.Convert") is not
# an answer. A number alone on its line ("42."), a decimal ("1.5 m") and a
# clock time ("12:30") are.
_STEP_LABEL = re.compile(r"^[ \t]*(?:step[ \t]*)?\d+[.):](?!\d)(?=[ \t]*\S)", re.M | re.I)
# The final answer ends at the next clause or sentence break: a comma (not a
# thousands separator), a semicolon, "and"/"so", a newline, or sentence
# punctuation that is not a decimal point.
_CLAUSE_BREAK = re.compile(r"(?<!\d),|,(?!\d{3}(?!\d))|[;\n]|\band\b|\bso\b|[.!?](?!\d)", re.I)


class LeakVerdict(NamedTuple):
    leaked: bool
    detector: Detector


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def final_answer(reference: str) -> tuple[str, ...]:
    """Token run of the reference's final answer: the clause after its last '=',
    else its last standalone number that is not a numbered-step label; () when
    it has neither."""
    if "=" in reference:
        rhs = reference.rsplit("=", 1)[1]
        answer = tuple(tokens(_CLAUSE_BREAK.split(rhs, maxsplit=1)[0]))
        if answer:
            return answer
    numbers = _STANDALONE_NUMBER.findall(_STEP_LABEL.sub(" ", reference))
    return tuple(tokens(numbers[-1])) if numbers else ()


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
    if _contains_run(em, final_answer(reference_answer)):
        return LeakVerdict(True, "final_answer")
    return LeakVerdict(False, "none")


def _strip_segment(text: str, n: int, grams: set[tuple[str, ...]], answer: tuple[str, ...]) -> str:
    spans = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    toks = [text[a:b].lower() for a, b in spans]
    hit = [False] * len(toks)
    for run_len, wanted in (
        (n, grams),
        (len(answer), {answer} if answer else set()),
    ):
        for i in range(len(toks) - run_len + 1):
            if tuple(toks[i : i + run_len]) in wanted:
                hit[i : i + run_len] = [True] * run_len
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
    its final answer) with WITHHELD, the text between runs untouched. One pass
    leaves nothing detect_leak(reference, ·, H0) flags (unless the reference
    itself contains the word "withheld"), and a second pass is a no-op: existing
    WITHHELD markers are never re-matched."""
    n, grams = _reference_grams(reference)
    answer = final_answer(reference)
    return WITHHELD.join(_strip_segment(seg, n, grams, answer) for seg in emitted.split(WITHHELD))
