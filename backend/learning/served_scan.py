"""PKG-14 final fix round (spec §13 A101; focused review M2 + minor 1): the
served-text scan of one tutor turn, compiled ONCE per turn.

A93 scans every served tutor text, as it is relayed, against every item posed
to the student and not yet graded (up to LOOP_SCAN_POSED_MAX), so an answer the
tutor states is recorded as help before the next chunk goes out. The first
build re-ran `detect_leak` per item per scan over the WHOLE text so far —
tokenising the text, the given text and every item's rules again each time —
which the review measured at ~62 s of event-loop time for 200 items and a 4.3k
reply. Here:

- (a) every item's strict served-mode rules are built ONCE per turn
  (`leak.served_rules`); the given text's provenance grams once per turn;
- (b) a scan reads only the new suffix plus an OVERLAP (`window_start`): it
  reaches back over twice the longest answer form among the items in WORD
  TOKENS (at least LEAK_NGRAM; A105 — the rules read tokens and skip
  punctuation, so padding between the words cannot outrun it), then twice the
  longest form in non-space characters (so stretched whitespace cannot outrun
  it), the served-mode
  answer-position look-back (LEAK_POSITION_WINDOW_CHARS) and
  LOOP_SCAN_CONTEXT_CHARS more, then snaps back to the start of that sentence
  (a genuine clause start, so the cut adds no spurious "clause-initial" hit) or,
  failing a sentence end within LOOP_SCAN_CONTEXT_CHARS, to a word boundary;
- the text-only work (tokens, copied runs, number words, the folded copy) is
  done once per scanned window (`leak.served_text`), shared by every item;
- an item already stated this turn is not scanned again (it is recorded).

Same verdicts: `served_leaked` is `detect_leak(strict=True, given=…)` below H6
on the same rules and the same text (tests pin the equivalence). An item whose
rules cannot be built (`detect_leak` would raise) counts as stated — fail
closed on the evidence side; a non-servable item is skipped. The window can
only ADD hits at its edge relative to a whole-text scan (a cut copy run, an
enumeration cut short) — never drop one shorter than the overlap — and the
turn's final text is scanned WHOLE once more at completion (`_LoopTurn.complete`,
A105), so no windowing gap survives the turn."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from learning import leak, params
from learning.checks import is_servable

_SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*\s+|\n+")


def _option_text(item) -> str | None:
    """The text of an mc_reason item's correct option (routes.learn_loop.option_text)."""
    for option in getattr(item, "options", None) or []:
        if option.letter == getattr(item, "correct_option", None):
            return option.text
    return None


def _nonspace(text: str | None) -> int:
    return sum(1 for ch in text or "" if not ch.isspace())


def _ngram_chars(reference: str | None) -> int:
    """The most non-space characters any LEAK_NGRAM consecutive reference tokens
    span (the n-gram rule's longest form; a shorter reference: all of it)."""
    spans = [(m.start(), m.end()) for m in leak._TOKEN.finditer(reference or "")]
    if not spans:
        return 0
    n = min(params.LEAK_NGRAM, len(spans))
    return max(
        _nonspace(reference[spans[i][0] : spans[i + n - 1][1]]) for i in range(len(spans) - n + 1)
    )


def _tokens(text: str | None) -> int:
    return len(leak._TOKEN.findall(text or ""))


def form_tokens(item) -> int:
    """The longest answer form of `item` in WORD TOKENS (spec §13 A105): its
    final answer, canonical answer, correct option text, or a reference n-gram
    (LEAK_NGRAM tokens; a shorter reference: all of it). The rules match word
    tokens and skip punctuation, so this — not characters — is what a padded
    answer cannot outrun."""
    return max(
        _tokens(getattr(item, "final_answer", None)),
        _tokens(getattr(item, "canonical_answer", None)),
        _tokens(_option_text(item)),
        min(params.LEAK_NGRAM, _tokens(getattr(item, "reference_answer", None))),
    )


def _word_char(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def form_chars(item) -> int:
    """The longest answer form of `item` any served-mode rule matches, in
    non-space characters: its final answer, canonical answer, correct option
    text, or a reference n-gram."""
    return max(
        _nonspace(getattr(item, "final_answer", None)),
        _nonspace(getattr(item, "canonical_answer", None)),
        _nonspace(_option_text(item)),
        _ngram_chars(getattr(item, "reference_answer", None)),
    )


@dataclass
class ScanSet:
    """One turn's scan set, compiled: (question_hash, rules | None) per servable
    item — None when the rules cannot be built (always stated) — the given
    text's provenance data, and the overlap a windowed scan keeps."""

    entries: list[tuple[str, object | None]]
    given: leak.GivenText
    overlap: int
    hashes: list[str] = field(default_factory=list)
    #: A105: the word tokens a window reaches back over before the char overlap
    overlap_tokens: int = 2 * params.LEAK_NGRAM

    @classmethod
    def build(cls, items, *, given: str) -> ScanSet:
        entries: list[tuple[str, object | None]] = []
        longest = 0
        longest_tokens = params.LEAK_NGRAM
        for item in items or []:
            if not is_servable(item):
                continue
            try:
                rules = leak.served_rules(
                    reference=item.reference_answer,
                    final_answer=item.final_answer,
                    canonical_answer=item.canonical_answer,
                    correct_option=item.correct_option,
                    option_text=_option_text(item),
                )
            except (ValueError, TypeError):
                rules = None  # detect_leak would raise: counts as stated (fail closed)
            entries.append((item.question_hash, rules))
            try:
                longest = max(longest, form_chars(item))
                longest_tokens = max(longest_tokens, form_tokens(item))
            except (TypeError, AttributeError):
                longest = max(longest, params.LEAK_POSITION_WINDOW_CHARS)
        overlap = 2 * longest + params.LEAK_POSITION_WINDOW_CHARS + params.LOOP_SCAN_CONTEXT_CHARS
        return cls(
            entries,
            leak.given_text(given or ""),
            overlap,
            [h for h, _ in entries],
            overlap_tokens=2 * longest_tokens,
        )

    def window_start(self, text: str, upto: int) -> int:
        """Where a scan of `text` that has already scanned `text[:upto]` starts:
        back from `upto` over `overlap_tokens` words (A105: the rules match word
        tokens and skip punctuation, so an answer padded with punctuation
        between its words is measured as the rules read it), then `overlap`
        more non-space characters (the answer-position look-back and the
        context), then back to the start of that sentence (a sentence end
        within LOOP_SCAN_CONTEXT_CHARS before it), else to a word boundary.
        0 when the text is shorter.

        A "word" is a whitespace-delimited run holding an ASCII letter or digit:
        every such run holds at least one rule token, so the count never
        exceeds the tokens passed (the window is never too short)."""
        i = min(max(upto, 0), len(text))
        words, in_word = 0, False
        while i > 0 and words < self.overlap_tokens:
            i -= 1
            ch = text[i]
            if ch.isspace():
                if in_word:
                    words += 1
                in_word = False
            elif _word_char(ch):
                in_word = True
        if in_word and i == 0:
            words += 1
        seen = 0
        while i > 0 and seen < self.overlap:
            i -= 1
            if not text[i].isspace():
                seen += 1
        if i == 0:
            return 0
        lo = max(0, i - params.LOOP_SCAN_CONTEXT_CHARS)
        last = None
        for m in _SENTENCE_END.finditer(text, lo, i):
            last = m
        if last is not None:
            return last.end()
        while i > 0 and not text[i - 1].isspace():
            i -= 1
        return i

    def stated(self, text: str, *, start: int = 0, skip=()) -> list[str]:
        """The sorted hashes of the items `text[start:]` states (strict served
        mode, below H6), skipping the hashes in `skip` (already stated)."""
        todo = [(h, r) for h, r in self.entries if h not in skip]
        if not todo or not text:
            return []
        prepared = leak.served_text(text[start:], self.given)
        out = set()
        for qh, rules in todo:
            try:
                hit = rules is None or leak.served_leaked(prepared, rules)
            except (ValueError, TypeError):
                hit = True  # an item the check raises on counts as stated (fail closed)
            if hit:
                out.add(qh)
        return sorted(out)
