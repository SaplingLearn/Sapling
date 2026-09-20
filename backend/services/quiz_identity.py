"""Stable identity for one quiz item (#543 addendum E5).

Before this module a generated question had no identity at all: it was
written into the encrypted `quiz_attempts.questions_json` blob, graded, and
forgotten. Nothing could ask "have we asked this before?" (the repetition
guard, E6), "was this grounded in course material?" (E8), or — the audit's
missing-capture #9 — "how often do students across this course miss THIS
question?", because there was nothing to key such an aggregate on.

`question_hash` is that key. The properties it has to hold:

* **Stable across processes, machines and deploys** — a plain SHA-256 over
  normalized text, no salt, no `hash()`, no randomness. A hash that changed
  per process would silently re-key every historical item.
* **Insensitive to presentation** — whitespace, casing and option ORDER are
  noise: the same item with its options rearranged is a repeat, not a new
  question.
* **Sensitive to content** — a different stem, or genuinely different
  answer choices, is a different item.

The `v1` version tag is part of the hashed body on purpose. If the
normalization above ever has to change, bumping the tag makes old and new
identities visibly disjoint instead of quietly colliding across the change.

Truncated to 64 bits: this is a correlation key, not a security boundary
(same reasoning as services/fingerprint.py, whose SEPARATOR this reuses so
option text containing punctuation can't smear across field boundaries).
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from services.fingerprint import SEPARATOR

# 16 hex chars = 64 bits. Item statistics key on this; 64 bits is far past
# the birthday bound for any plausible question corpus.
QUESTION_HASH_LEN = 16

_HASH_VERSION = "v1"


def normalize_text(value: Any) -> str:
    """Collapse a stem or option to its identity-bearing form.

    `str.split()` with no argument splits on arbitrary runs of whitespace
    (including tabs and newlines), so this folds re-wrapped text to the same
    string. `casefold` rather than `lower` — it is the correct fold for
    non-ASCII text, which concept names genuinely contain.
    """
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def question_hash(
    stem: Any,
    options: Iterable[Any],
    *,
    length: int = QUESTION_HASH_LEN,
) -> str:
    """Return the stable identity of one quiz item.

    Options are sorted after normalization, so option order does not affect
    identity — but duplicates are NOT collapsed, or a malformed item with a
    repeated option would collide with the distinct-option item it was
    derived from.
    """
    parts = [_HASH_VERSION, normalize_text(stem)]
    parts.extend(sorted(normalize_text(o) for o in options))
    body = SEPARATOR.join(parts)
    # errors="replace": lone surrogates from upstream text handling must not
    # raise here. Identity is metadata hanging off generation, never a gate.
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:length]


def wire_question_hash(question: Any) -> str | None:
    """Identity of a question in the STORED wire shape, or None if the shape
    has no usable identity.

    Two callers, two reasons this exists:

    * E6's repetition guard reads attempts written BEFORE E5 shipped, whose
      questions carry no `question_hash` — recomputing from the stored stem
      and options gives the guard retroactive coverage on day one.
    * Rows written after E5 carry their own hash, which is TRUSTED over a
      recompute: if the normalization above is ever revised, stored items
      keep the identity they were written with instead of silently re-keying.
    """
    if not isinstance(question, dict):
        return None
    stored = question.get("question_hash")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    stem = question.get("question")
    options = question.get("options")
    if not stem or not isinstance(options, list) or not options:
        return None
    texts: list[str] = []
    for opt in options:
        if isinstance(opt, dict):
            if "text" not in opt:
                return None
            texts.append(str(opt.get("text") or ""))
        elif isinstance(opt, str):
            texts.append(opt)
        else:
            return None
    return question_hash(stem, texts)
