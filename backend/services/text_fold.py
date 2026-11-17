"""Text folding shared by the deterministic screens.

Two pure, regex-based screens read student-written text for meaning:
`services/share_screen.py` (does an upload talk to an AI?) and
`services/crisis_detection.py` (does a message say the student may be in
danger?). Both are defeated by the same cheap tricks, so they share the same
folds:

- ``strip_invisible``: zero-width and other format characters threaded
  through a word ("ig​nore") read identically and dodge every pattern.
- ``fold_confusables``: Latin look-alikes from Cyrillic and Greek
  ("Ignоre" with a Cyrillic o). NFKC folds fullwidth and mathematical
  letters already; it leaves these alone because they are real letters of
  other scripts, so a small built-in table maps the ones that pass for Latin.
- ``fold_leet``: digits and symbols standing in for letters inside a word
  ("k1ll", "mys3lf", "1gnore"). A character is folded only when a letter
  sits right next to it, so numbers ("988", "CS 330", "2 + 2") are left
  alone.

All three are for MATCHING only. Nothing here is ever stored or shown: the
screens fold a copy of the text and read the copy.
"""

from __future__ import annotations

import re

#: Characters that render as nothing: soft hyphen, Mongolian vowel separator,
#: zero-width space/non-joiner/joiner, LRM/RLM, bidi embeddings and isolates,
#: word joiner and the invisible operators, BOM.
INVISIBLE_RE = re.compile(
    "[­᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]"
)

# Cyrillic and Greek letters that pass for Latin ones in common fonts. Not
# the full Unicode confusables list (that is thousands of entries and drags
# in a data file); the letters an attacker reaches for, in both cases.
_CONFUSABLE_PAIRS = {
    # Cyrillic lower case
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k",
    "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "ѕ": "s", "і": "i",
    "ї": "i", "ј": "j", "ԁ": "d", "һ": "h", "ӏ": "l",
    "ԛ": "q", "ԝ": "w", "ь": "b", "ɡ": "g",
    # Cyrillic upper case
    "А": "A", "В": "B", "Е": "E", "Ё": "E", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "У": "Y", "Х": "X", "Ѕ": "S", "І": "I",
    "Ї": "I", "Ј": "J", "Ӏ": "I", "Ԁ": "D", "Ԛ": "Q",
    "Ԝ": "W",
    # Greek lower case
    "α": "a", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ϲ": "c",
    "ϳ": "j",
    # Greek upper case
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "Ϲ": "C",
}
_CONFUSABLES = str.maketrans(_CONFUSABLE_PAIRS)

#: Leetspeak stand-ins. Not "!" or "|": both are punctuation the screens read
#: as sentence boundaries, and a sentence-final "die!" must stay "die".
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
_LEET_RE = re.compile(r"(?<=[^\W\d_])[013457@$]|[013457@$](?=[^\W\d_])")


def strip_invisible(text: str) -> str:
    return INVISIBLE_RE.sub("", text)


def fold_confusables(text: str) -> str:
    """Map Cyrillic/Greek look-alikes to the Latin letters they pass for."""
    return text.translate(_CONFUSABLES)


def fold_leet(text: str) -> str:
    """Fold leetspeak digits/symbols that sit next to a letter.

    "k1ll mys3lf" -> "kill myself", "1gnore" -> "ignore"; "988", "CS 330",
    "x = 5" are unchanged (no letter touches the digit). Runs to a fixed point
    so "l33t" (whose second 3 only touches a letter once the first is folded)
    folds whole; the loop ends as soon as nothing changes.
    """
    for _ in range(8):
        folded = _LEET_RE.sub(lambda m: _LEET[m.group(0)], text)
        if folded == text:
            return folded
        text = folded
    return text
