import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from benchmark_quiz import score_retrieval


def test_recall_and_precision():
    concept = {"relevant_chunk_substrings": ["memoization table", "overlapping subproblems"]}
    chunks = [
        {"chunk_text": "A memoization table stores results.", "similarity": 0.8},
        {"chunk_text": "overlapping subproblems recur.", "similarity": 0.7},
        {"chunk_text": "Unrelated text about sorting.", "similarity": 0.6},
    ]
    r = score_retrieval(concept, chunks)
    assert r["recall"] == 1.0          # both expected substrings found
    assert abs(r["precision"] - 2/3) < 1e-6  # 2 of 3 returned chunks relevant


def test_zero_recall_when_missing():
    concept = {"relevant_chunk_substrings": ["red-black tree"]}
    chunks = [{"chunk_text": "quicksort partitions", "similarity": 0.9}]
    r = score_retrieval(concept, chunks)
    assert r["recall"] == 0.0
    assert r["precision"] == 0.0
