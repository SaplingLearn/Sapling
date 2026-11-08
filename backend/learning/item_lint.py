"""Item-flaw linter for check items (spec §13 A113).

Pure: imports learning.params and learning.checks only (both pure), so it is
listed in tests/test_learning_loop_invariants.py::PURE_MODULES.

LLM-written selected-response items carry known item-writing flaws that raise
scores without raising knowledge — they look like learning (the 2026-11-07
direction audit, "Item quality"; Haladyna, Downing & Rodriguez 2002). The
linter names five of them by a stable code:

- ``correct_longest``: the correct option is uniquely the longest, by at least
  ITEM_LINT_LONGEST_MARGIN of the longest distractor — "pick the longest" finds
  the key;
- ``correct_repeats_stem``: the correct option repeats at least
  ITEM_LINT_STEM_OVERLAP_MARGIN more of the stem's content words than any
  distractor — the key echoes the question;
- ``all_or_none_of_above``: an option is "all/none of the above" (or "of
  these");
- ``duplicate_options``: two options say the same thing — equal once case,
  punctuation, articles and regular plurals are set aside;
- ``negative_stem``: a negatively worded stem ("Which … is NOT …", "All of
  the following … except", "Which statement is false?").

The first four read the options, so only an item with options (mc_reason) can
carry them; the stem rule reads every format. The linter FLAGS: it never drops
or rewrites an item (code cannot shorten an option, and a drop rule cost most
of the mc_reason yield in the A37 review). The flags are stored on
check_items.lint_flags when an item is written
(services/check_item_service.py) and by scripts/backfill_check_item_lint.py;
the delayed post-test prefers items without them (learning/checks.py::
posttest_reserve_hashes and choose_posttest_item) and the admin review queue
lists every flagged item.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from learning.checks import _STOPWORDS
from learning.params import ITEM_LINT_LONGEST_MARGIN, ITEM_LINT_STEM_OVERLAP_MARGIN

CORRECT_LONGEST = "correct_longest"
CORRECT_REPEATS_STEM = "correct_repeats_stem"
ALL_OR_NONE_OF_ABOVE = "all_or_none_of_above"
DUPLICATE_OPTIONS = "duplicate_options"
NEGATIVE_STEM = "negative_stem"
#: Every flag, in the order lint_item reports them (the stored order too).
LINT_FLAGS = (
    CORRECT_LONGEST,
    CORRECT_REPEATS_STEM,
    ALL_OR_NONE_OF_ABOVE,
    DUPLICATE_OPTIONS,
    NEGATIVE_STEM,
)

_WORD = re.compile(r"\w+")
# A content word is at least this long (the checks.py ranking floor, "of",
# "to" and "a" say nothing about what an option claims) and not a function word.
_MIN_CONTENT_LEN = 3
_ARTICLES = frozenset({"a", "an", "the"})
# "All of the above", "none of these", "both of the above", "all the above".
_ALL_OR_NONE = re.compile(
    r"\b(?:all|none|both|neither)\s+of\s+(?:the\s+)?(?:above|these|those)\b"
    r"|\ball\s+the\s+above\b",
    re.IGNORECASE,
)
# A negatively worded stem: "all/each/every … except", a which-question asking
# for the exception ("Which … is not …", "Which statement is false?"), or "is
# not true/correct". It reads selection stems, where the negative is the cue a
# skimming student misses: a question that merely contains "not" ("Why does the
# loop not stop?") is not one, and neither is a bare capitalised keyword (a
# "NOT gate", SQL's EXCEPT), so no rule reads capitals alone.
_NEGATIVE_STEM = re.compile(
    r"\b(?:all|each|every)\b[^?.!\n]*?\bexcept\b"
    r"|\bwhich\b[^?.!\n]*?\b(?:not|least|false|incorrect|untrue)\b"
    r"|\b(?:is|are)\s+not\s+(?:true|correct)\b",
    re.IGNORECASE,
)


def _folded(text: str | None) -> str:
    """NFKC-folded, casefolded text (curly quotes and full-width forms aside)."""
    return unicodedata.normalize("NFKC", text or "").casefold()


def _forms(word: str) -> frozenset[str]:
    """`word` and every singular it could be the regular plural of ("sizes" →
    size, siz; "classes" → classe, class; "fallacies" → fallacy). Two words
    are one when their forms meet, so a plural matches its singular whichever
    side has it, with no guess at which "-es" plural drops its "e"."""
    forms = {word}
    if len(word) > _MIN_CONTENT_LEN and word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])
        if word.endswith("es"):
            forms.add(word[:-2])
        if word.endswith("ies"):
            forms.add(word[:-3] + "y")
    return frozenset(forms)


def _same_word(a: str, b: str) -> bool:
    return bool(_forms(a) & _forms(b))


def _content_words(text: str | None) -> list[str]:
    """The distinct content words of `text`, in order: at least
    _MIN_CONTENT_LEN long and not an English function word (checks._STOPWORDS)."""
    return list(
        dict.fromkeys(
            w
            for w in _WORD.findall(_folded(text))
            if len(w) >= _MIN_CONTENT_LEN and w not in _STOPWORDS
        )
    )


def _length(text: str | None) -> int:
    """Characters with whitespace runs collapsed (the eval's measure)."""
    return len(" ".join((text or "").split()))


def _words(text: str | None) -> list[str]:
    """What an option says once case, punctuation and articles are set aside."""
    return [w for w in _WORD.findall(_folded(text)) if w not in _ARTICLES]


def _correct_longest(options: Sequence[str], correct: int) -> bool:
    right = _length(options[correct])
    longest_other = max(_length(o) for i, o in enumerate(options) if i != correct)
    return right > longest_other and right >= longest_other * (1 + ITEM_LINT_LONGEST_MARGIN)


def _correct_repeats_stem(prompt: str, options: Sequence[str], correct: int) -> bool:
    stem = frozenset().union(*(_forms(w) for w in _content_words(prompt)))
    overlap = [sum(1 for w in _content_words(o) if _forms(w) & stem) for o in options]
    most_other = max(n for i, n in enumerate(overlap) if i != correct)
    return overlap[correct] - most_other >= ITEM_LINT_STEM_OVERLAP_MARGIN


def _duplicate_options(options: Sequence[str]) -> bool:
    """Two options that say one thing: word for word the same once case,
    punctuation and articles are set aside, a word matching its regular plural
    ("The base case." / "the base cases")."""
    said = [w for w in (_words(o) for o in options) if w]
    return any(
        len(a) == len(b) and all(_same_word(x, y) for x, y in zip(a, b))
        for i, a in enumerate(said)
        for b in said[i + 1 :]
    )


def lint_item(
    prompt: str | None, options: Sequence[str] = (), correct: int | None = None
) -> list[str]:
    """The flags (LINT_FLAGS codes, in that order) of one item: its stem, its
    options' texts in their stored order, and the index of the correct one.
    An item without options is read for the stem rule only; the two rules
    about the correct option need a valid `correct` and a distractor."""
    flags: set[str] = set()
    if _NEGATIVE_STEM.search(prompt or ""):
        flags.add(NEGATIVE_STEM)
    texts = [o or "" for o in options]
    if texts:
        if any(_ALL_OR_NONE.search(t) for t in texts):
            flags.add(ALL_OR_NONE_OF_ABOVE)
        if _duplicate_options(texts):
            flags.add(DUPLICATE_OPTIONS)
        if correct is not None and 0 <= correct < len(texts) and len(texts) > 1:
            if _correct_longest(texts, correct):
                flags.add(CORRECT_LONGEST)
            if _correct_repeats_stem(prompt or "", texts, correct):
                flags.add(CORRECT_REPEATS_STEM)
    return [f for f in LINT_FLAGS if f in flags]


def lint_check_item(item) -> list[str]:
    """`lint_item` over a stored item (a decrypted learning.checks.CheckItem,
    or anything with its prompt / options / correct_option): the stored
    options in letter order, the correct one found by its letter. The write
    path lints the same stored shape, so a backfill agrees with it."""
    options = list(getattr(item, "options", None) or [])
    letter = getattr(item, "correct_option", None)
    correct = next((i for i, o in enumerate(options) if o.letter == letter), None)
    return lint_item(getattr(item, "prompt", ""), [o.text for o in options], correct)
