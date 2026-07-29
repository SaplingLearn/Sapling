"""Semantic document chunker for RAG indexing.

Splits on double-newline boundaries (the natural block delimiter in
Docling's markdown output), then merges short fragments and splits
over-long blocks at sentence boundaries.

Target: 50–400 words per chunk.
"""

import re

_MIN_WORDS = 50
_MAX_WORDS = 400


def _word_count(text: str) -> int:
    return len(text.split())


def _split_at_sentence(text: str, max_words: int) -> list[str]:
    """Split text at the nearest sentence boundary before max_words."""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        candidate = " ".join(words[start:end])
        # Walk back to find a sentence boundary (". " pattern)
        if end < len(words):
            last_period = candidate.rfind(". ")
            if last_period > 0:
                candidate = candidate[: last_period + 1]
        chunks.append(candidate.strip())
        start += len(candidate.split())
    return [c for c in chunks if c.strip()]


_PROSE_TARGET_WORDS = 200
_PROSE_OVERLAP_WORDS = 40
_PROSE_CATEGORIES = {"reading", "assignment", "study_guide"}

# Split on whitespace that follows sentence-ending punctuation.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split prose into sentences, collapsing all whitespace first.

    Prose (essays, problem-set writeups) has sparse blank lines, so we
    normalize newlines away and segment on sentence punctuation instead of
    on blocks. Deterministic: fixed regex, no model calls.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return []
    return [s for s in _SENTENCE_BOUNDARY.split(normalized) if s]


def chunk_prose(text: str) -> list[str]:
    """Chunk continuous prose into overlapping sentence windows.

    Packs sentences greedily into ~_PROSE_TARGET_WORDS windows, carries a
    ~_PROSE_OVERLAP_WORDS overlap into the next window so ideas straddling a
    boundary appear in both, hard-caps any window at _MAX_WORDS, and absorbs a
    too-small trailing remainder into the final window. Deterministic.
    """
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    counts = [_word_count(s) for s in sentences]
    n = len(sentences)

    # Whole document fits in one window -> single chunk.
    if sum(counts) <= _PROSE_TARGET_WORDS:
        return [" ".join(sentences)]

    chunks: list[str] = []
    start = 0
    while start < n:
        # Grow the window until we reach the word target (or run out).
        end = start
        words = 0
        while end < n and words < _PROSE_TARGET_WORDS:
            words += counts[end]
            end += 1

        # If the leftover tail is too small to stand alone, absorb it here
        # rather than emit a sub-_MIN_WORDS chunk.
        remaining = sum(counts[end:])
        if 0 < remaining < _MIN_WORDS:
            end = n

        piece = " ".join(sentences[start:end])
        if _word_count(piece) > _MAX_WORDS:
            chunks.extend(_split_at_sentence(piece, _MAX_WORDS))
        else:
            chunks.append(piece)

        if end >= n:
            break

        # Step back to create overlap for the next window. Guarantee forward
        # progress: next window always starts at least one sentence past `start`.
        overlap = 0
        next_start = end
        while next_start - 1 > start and overlap < _PROSE_OVERLAP_WORDS:
            next_start -= 1
            overlap += counts[next_start]
        start = next_start

    return [c for c in chunks if c.strip()]


def chunk_for_category(text: str, category: str) -> list[str]:
    """Route to the chunking strategy for a document's classified category.

    Continuous-prose categories use the sentence-window chunker; structured
    markdown (and any unrecognized category) uses the block chunker.
    """
    if category in _PROSE_CATEGORIES:
        return chunk_prose(text)
    return chunk_document(text)


def chunk_document(text: str) -> list[str]:
    """Split document text into RAG-indexable chunks.

    Algorithm:
    1. Split on double newlines (Docling block boundaries)
    2. Coalesce a block into its neighbor when either is tiny (< 10 words) and
       the combined size stays under _MIN_WORDS
    3. Split any chunk over _MAX_WORDS at a sentence boundary
    """
    if not text or not text.strip():
        return []

    # Step 1: split on double newlines
    raw_blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    # Step 2: coalesce a block into its neighbor when either is tiny (< 10 words)
    # and the combined size stays under _MIN_WORDS.
    # This coalesces single-line headers and short captions without eating normal paragraphs.
    merged: list[str] = []
    for block in raw_blocks:
        if (merged
                and min(_word_count(merged[-1]), _word_count(block)) < 10
                and _word_count(merged[-1]) + _word_count(block) < _MIN_WORDS):
            merged[-1] = merged[-1] + " " + block
        else:
            merged.append(block)

    # Step 3: split over-long blocks
    result: list[str] = []
    for block in merged:
        if _word_count(block) > _MAX_WORDS:
            result.extend(_split_at_sentence(block, _MAX_WORDS))
        else:
            result.append(block)

    return [c for c in result if c.strip()]
