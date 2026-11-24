"""Low-trust next-probe hint from reason / self-explain text (W2.4 / plan S).

Given already-decrypted (or raw) student prose and candidate check items, pick
at most one preferred ``question_hash`` to pose next. Diagnostic routing only:

- never bumps mastery / never touches the graph mutator
- never grades, never writes evidence
- sealed ciphertext is rejected (caller must decrypt; this module stays pure)

Heuristic: significant token overlap between the prose and each candidate's
searchable text (stem / prompt / misconception labels). Deterministic code —
no model client. Empty prose, ciphertext, or no candidate above the overlap
floor → ``None`` (caller keeps its ordinary picker).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: Reject sealed blobs — keyword scoring needs plaintext the caller opened.
_CIPHER_PREFIXES = ("enc:", "enc2:")

#: Drop ultra-common glue so overlap reflects topic words, not "the"/"because".
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "so",
        "because",
        "since",
        "for",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "this",
        "that",
        "these",
        "those",
        "i",
        "we",
        "you",
        "they",
        "my",
        "our",
        "your",
        "their",
        "not",
        "no",
        "yes",
        "just",
        "like",
        "about",
        "into",
        "than",
        "too",
        "very",
        "can",
        "could",
        "would",
        "should",
        "will",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "why",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+", re.ASCII)
_MIN_TOKEN_LEN = 4
_MIN_OVERLAP = 2


def _tokens(text: str) -> frozenset[str]:
    """Significant lowercase tokens for overlap scoring."""
    return frozenset(
        t
        for t in _TOKEN.findall((text or "").lower())
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOP
    )


def _plaintext(text: str | None) -> str:
    """Strip; empty when missing or still sealed (caller must decrypt)."""
    raw = (text or "").strip()
    if not raw or raw.startswith(_CIPHER_PREFIXES):
        return ""
    return raw


def prefer(
    text: str | None,
    candidates: Sequence[tuple[str, str]],
) -> str | None:
    """Preferred next ``question_hash``, or ``None``.

    ``candidates`` are ``(question_hash, searchable_text)`` pairs already
    narrowed by the caller (servable, not excluded). Pure: no I/O, no mastery.
    Ties break on lexicographically smaller ``question_hash``.
    """
    reason = _tokens(_plaintext(text))
    if len(reason) < _MIN_OVERLAP or not candidates:
        return None
    best_qh: str | None = None
    best_score = 0
    for qh, searchable in candidates:
        if not qh:
            continue
        score = len(reason & _tokens(searchable or ""))
        if score < _MIN_OVERLAP:
            continue
        if score > best_score or (score == best_score and (best_qh is None or qh < best_qh)):
            best_score = score
            best_qh = qh
    return best_qh
