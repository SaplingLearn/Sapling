"""Semantic document chunker for RAG indexing.

Splits on double-newline boundaries (the natural block delimiter in
Docling's markdown output), then merges short fragments and splits
over-long blocks at sentence boundaries.

Target: 50–400 words per chunk.
"""

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
