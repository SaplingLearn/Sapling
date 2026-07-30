"""Shared keyword-overlap tokenizer.

Factored out of `agents/tools/chat_context.py` (#149) so the graph-context
seed block (`services/graph_context.py`) selects concepts with the SAME
token semantics the course-materials search ranks documents with — one
definition of "does this message mention that term", not two drifting ones.
"""

from __future__ import annotations

import re

# Words that show up in nearly every academic question and would otherwise
# dominate the keyword-overlap score. Filtering them keeps short queries
# like "what is recursion?" from matching every document with the word
# "what" in its summary.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "in", "on", "at", "to", "for", "with", "by", "from", "as",
        "and", "or", "but", "not", "no", "so", "if", "then", "than", "that",
        "this", "these", "those", "it", "its", "i", "you", "we", "they",
        "he", "she", "him", "her", "them", "us", "do", "does", "did", "done",
        "have", "has", "had", "what", "which", "who", "whom", "whose",
        "when", "where", "why", "how", "can", "could", "would", "should",
        "will", "may", "might", "must", "about", "into", "over", "under",
    }
)

# Token = run of word chars, lowercased. Same shape across query and
# document text so overlap math is symmetric.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str | None) -> set[str]:
    """Lowercase and tokenize, dropping stopwords. Returns a set so
    repeated occurrences in the text do not game the overlap score (we
    want to know whether a term is present, not how many times)."""
    if not text:
        return set()
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if t.lower() not in STOPWORDS and len(t) > 1
    }
