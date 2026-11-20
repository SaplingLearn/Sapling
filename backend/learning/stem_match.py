"""Spec §13 A125: does a text a student hands an AI surface OUTSIDE the loop
quote one of their posed-and-ungraded check items? Pure: no I/O, no model.

The item's STEM (the prompt it was posed with) is matched with the leak guards'
own deterministic primitives — nothing new is tuned here:

- every text is read on answer_guard's detection fold (`answer_guard.normalise`:
  NFKD with combining marks and format characters dropped, UTS #39 look-alikes
  mapped, letter-spaced words glued, case folded), so a homoglyph or a
  zero-width character cannot hide a paste; then cut into A34 answer tokens
  (`checks.answer_tokens`: numbers by value, words, math symbols — punctuation
  and whitespace are no token, so re-punctuating or re-wrapping a paste changes
  nothing);
- a stem token is COVERED when it lies in a run of LEAK_PROVENANCE_MIN_TOKENS
  consecutive stem tokens that the text holds consecutively up to inflection —
  leak.py's strict-mode stem rule (`_same_lemma`: equal, or one lemma by a
  shared stem of LEAK_STEM_MIN_CHARS characters covering LEAK_STEM_MIN_SHARE of
  the longer word, "returns"/"return", never "less"/"lesson"), found through its
  exact lemma index (`_lemma_index` / `_lemma_run_hits`); the run length is the
  one served mode's provenance rule reads as "copied";
- the text QUOTES the item when the covered tokens are at least
  INTEGRITY_STEM_MIN_SHARE of the stem's tokens AND at least LEAK_NGRAM of them
  (all of them, for a stem shorter than that): a pasted stem covers all of it
  and an edited word costs about one token, while a shared opening ("Which of
  the following best describes the …", "What is tail …") stays under both.

A stem shorter than LEAK_PROVENANCE_MIN_TOKENS tokens is never quoted: so short
a question cannot be told from a mention of its topic. What the surface then
serves is still scanned (learning.served_scan), so its answer is caught there.

`Folded.holds(run)` also answers whether a text holds a whole phrase — a concept
name the student's own note already contains (services/integrity_guard.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from learning import answer_guard, leak, params
from learning.checks import AnswerToken, answer_tokens


def tokens(text: str | None) -> list[AnswerToken]:
    """The A34 answer tokens of `text`, read on answer_guard's detection fold
    (the spans index the folded copy, never the original)."""
    return answer_tokens(answer_guard.normalise(text or ""))


@dataclass(frozen=True)
class Folded:
    """A text cut ONCE into folded answer tokens, with leak.py's exact lemma
    index, shared by every stem matched against it."""

    toks: list[AnswerToken]
    index: dict[str, list[int]]

    @classmethod
    def of(cls, text: str | None) -> Folded:
        toks = tokens(text)
        return cls(toks, leak._lemma_index(toks))

    def holds(self, run: tuple[str, ...]) -> bool:
        """`run` occurs in the text token by token, up to inflection."""
        return bool(run) and bool(leak._lemma_run_hits(self.toks, run, self.index))


def _need(stem_len: int) -> int:
    """How many of a stem's tokens a quote must cover (module docstring)."""
    return max(
        math.ceil(params.INTEGRITY_STEM_MIN_SHARE * stem_len),
        min(stem_len, params.LEAK_NGRAM),
    )


@dataclass(frozen=True)
class StemSet:
    """The stems of one request's posed items, tokenised once:
    (question_hash, stem tokens) per item whose stem is long enough to quote."""

    entries: list[tuple[str, tuple[str, ...]]]

    @classmethod
    def build(cls, items) -> StemSet:
        entries: list[tuple[str, tuple[str, ...]]] = []
        for item in items or []:
            qh = getattr(item, "question_hash", None)
            stem = tuple(t.value for t in tokens(getattr(item, "prompt", None)))
            if qh and len(stem) >= params.LEAK_PROVENANCE_MIN_TOKENS:
                entries.append((qh, stem))
        return cls(entries)

    def quoted(self, text: str | None) -> list[str]:
        """The sorted question hashes of the items whose stem `text` quotes."""
        if not self.entries or not text:
            return []
        folded = Folded.of(text)
        if not folded.toks:
            return []
        n = params.LEAK_PROVENANCE_MIN_TOKENS
        held: dict[tuple[str, ...], bool] = {}  # one lookup per distinct run
        out: set[str] = set()
        for qh, stem in self.entries:
            covered: set[int] = set()
            for i in range(len(stem) - n + 1):
                run = stem[i : i + n]
                if run not in held:
                    held[run] = folded.holds(run)
                if held[run]:
                    covered.update(range(i, i + n))
            if len(covered) >= _need(len(stem)):
                out.add(qh)
        return sorted(out)
