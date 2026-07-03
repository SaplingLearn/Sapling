from services.chunker import chunk_document


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
    assert len(result) <= 2


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
