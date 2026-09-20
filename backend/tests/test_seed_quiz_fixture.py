"""Unit test for scripts/seed_quiz_fixture.py::main.

Pins the per-file chunking contract: each fixture doc must be chunked
independently so a chunk never straddles a file boundary (which would blur
per-concept retrieval). No network / Supabase — everything external is mocked.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import seed_quiz_fixture as seed


def test_main_chunks_each_doc_independently():
    doc_files = sorted((seed.FIX / "docs").glob("*"))
    assert len(doc_files) >= 2  # need >1 file for the boundary concern to bite

    # One distinct chunk per file, so we can prove the merge order + per-file split.
    def fake_chunk(text: str) -> list[str]:
        return [f"chunk::{len(text)}::{text[:12]}"]

    with patch.object(seed, "seed_fixture_course"), \
         patch.object(seed, "chunk_document", side_effect=fake_chunk) as m_chunk, \
         patch.object(
             seed, "index_document_chunks", autospec=True, return_value=0,
         ) as m_index:
        seed.main()

    # chunk_document called once PER FILE, never once on a joined blob.
    assert m_chunk.call_count == len(doc_files)
    for call in m_chunk.call_args_list:
        (arg,) = call.args
        assert isinstance(arg, str)

    # The merged chunk list handed to indexing is the per-file chunks concatenated.
    expected = []
    for p in doc_files:
        expected.extend(fake_chunk(p.read_text(encoding="utf-8")))
    passed_chunks = m_index.call_args.args[3]
    assert passed_chunks == expected


def test_main_calls_indexing_with_a_signature_that_actually_binds():
    """#630 review: `index_document_chunks` gained two REQUIRED keyword-only
    args (`visibility`, `category`) and this caller was updated for the first
    but not the second — a plain `TypeError` the moment anyone seeds the
    benchmark fixture. A bare MagicMock swallows any signature, so the patch
    above is `autospec=True` and this pins the two kwargs by name: they are the
    privacy and the catalog-disjointness decisions, and a caller that guesses
    them is the failure mode both were made required to prevent."""
    with patch.object(seed, "seed_fixture_course"), \
         patch.object(seed, "chunk_document", return_value=["c"]), \
         patch.object(
             seed, "index_document_chunks", autospec=True, return_value=0,
         ) as m_index:
        seed.main()

    assert m_index.call_args.kwargs["visibility"] == "shared"
    assert m_index.call_args.kwargs["category"] == "lecture_notes"
