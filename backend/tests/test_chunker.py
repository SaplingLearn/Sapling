from services.chunker import chunk_document, chunk_prose, chunk_for_category

_MAX_WORDS_BUFFER = 420   # _MAX_WORDS (400) + small slack for a boundary sentence
_MIN_WORDS_FLOOR = 50     # matches chunker._MIN_WORDS


def test_empty_returns_empty():
    assert chunk_document("") == []


def test_single_short_paragraph_returns_one_chunk():
    text = "Dynamic programming is a method for solving complex problems by breaking them into subproblems."
    result = chunk_document(text)
    assert len(result) == 1
    assert "dynamic programming" in result[0].lower()


def test_double_newline_splits_into_chunks():
    text = ("First paragraph about sorting algorithms. It covers quicksort and mergesort in detail.\n\n"
            "Second paragraph about graph algorithms. It explains BFS and DFS traversal methods.\n\n"
            "Third paragraph about dynamic programming. It covers memoization and tabulation.")
    result = chunk_document(text)
    assert len(result) == 3


def test_short_chunks_merged_with_neighbor():
    # Three paragraphs: short + short + normal => first two get merged
    short = "Short."
    normal = " ".join(["word"] * 60)  # 60 words
    text = f"{short}\n\n{short}\n\n{normal}"
    result = chunk_document(text)
    # Both short chunks should merge into one, leaving 2 total
    assert len(result) == 2


def test_long_chunk_split_at_sentence_boundary():
    # Build a single paragraph with 500 words, multiple sentences
    sentences = [f"This is sentence number {i} about algorithms and data structures." for i in range(50)]
    long_para = " ".join(sentences)
    result = chunk_document(long_para)
    assert len(result) > 1
    for chunk in result:
        word_count = len(chunk.split())
        assert word_count <= 420, f"Chunk too long: {word_count} words"


def test_no_empty_chunks():
    text = "\n\n".join(["  ", "actual content here with enough words to matter", "  "])
    result = chunk_document(text)
    for chunk in result:
        assert chunk.strip() != ""


def _prose(n):
    """n distinct sentences, each 10 unique tokens + a period.

    Every token is unique to its sentence, so any token shared between two
    chunks proves a whole sentence overlaps them."""
    return " ".join(
        f"alpha{i} bravo{i} charlie{i} delta{i} echo{i} "
        f"foxtrot{i} golf{i} hotel{i} india{i} juliet{i}."
        for i in range(n)
    )


def test_prose_empty_returns_empty():
    assert chunk_prose("") == []
    assert chunk_prose("   ") == []


def test_prose_short_text_is_single_chunk():
    text = "Photosynthesis converts light into chemical energy. It happens in chloroplasts."
    result = chunk_prose(text)
    assert len(result) == 1
    assert "photosynthesis" in result[0].lower()


def test_prose_no_blank_lines_splits_into_multiple_chunks():
    # ~600 words of continuous prose with NO double-newline boundaries.
    result = chunk_prose(_prose(60))
    assert len(result) >= 2


def test_prose_chunks_respect_max_words():
    for chunk in chunk_prose(_prose(60)):
        assert len(chunk.split()) <= _MAX_WORDS_BUFFER


def test_prose_adjacent_chunks_overlap():
    chunks = chunk_prose(_prose(60))
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:]):
        shared = set(a.split()) & set(b.split())
        assert shared, "expected at least one overlapping sentence between adjacent chunks"


def test_prose_is_deterministic():
    text = _prose(45)
    assert chunk_prose(text) == chunk_prose(text)


def test_prose_splits_oversized_sentence_at_max_words():
    # A single sentence far exceeding _MAX_WORDS (400) must be hard-split so
    # no resulting chunk exceeds the cap. Exercises the _split_at_sentence
    # branch in chunk_prose, which the uniform _prose() fixture never reaches.
    giant = " ".join(f"token{i}" for i in range(500)) + "."
    result = chunk_prose(giant)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk.split()) <= 400


def test_prose_no_tiny_trailing_chunk():
    # 22 sentences (~220 words): the leftover after the first ~200-word window
    # is small and must be absorbed, never emitted as a sub-50-word chunk.
    # Without absorption, this count would yield a sub-50-word trailing chunk.
    for chunk in chunk_prose(_prose(22)):
        assert len(chunk.split()) >= _MIN_WORDS_FLOOR


def test_dispatch_prose_categories_use_prose_chunker():
    text = _prose(40)
    for cat in ("reading", "assignment", "study_guide"):
        assert chunk_for_category(text, cat) == chunk_prose(text)


def test_dispatch_structured_categories_use_block_chunker():
    text = "Block one about sorting.\n\nBlock two about graphs.\n\nBlock three about trees."
    for cat in ("slides", "lecture_notes", "syllabus", "other", "unknown_value"):
        assert chunk_for_category(text, cat) == chunk_document(text)
