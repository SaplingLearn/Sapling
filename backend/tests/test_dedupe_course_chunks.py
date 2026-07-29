"""Tests for scripts.dedupe_course_chunks.plan_migration — the pure
regrouping logic of the one-time content-hash id migration."""
from services.rag_service import chunk_id


def _row(rid, course, text, embedding=None, doc="doc-1"):
    return {
        "id": rid,
        "course_id": course,
        "doc_id": doc,
        "uploader_id": "user-1",
        "chunk_index": 0,
        "chunk_text": text,
        "chunk_hash": rid,
        "embedding": embedding,
        "category": "document",
        "semester": "current",
        "section_id": None,
        "school": "",
    }


def test_duplicate_rows_collapse_to_one_content_hash_row():
    """Two legacy rows with identical text in the same course become one
    upsert under the content-hash id and two deletes of the legacy ids."""
    from scripts.dedupe_course_chunks import plan_migration

    rows = [
        _row("legacy-a", "CAS CS 330", "memoization basics", embedding="[0.1,0.2]"),
        _row("legacy-b", "CAS CS 330", "memoization basics", doc="doc-2"),
    ]
    upserts, deletes = plan_migration(rows)

    new_id = chunk_id("CAS CS 330", "memoization basics")
    assert [u["id"] for u in upserts] == [new_id]
    assert upserts[0]["chunk_hash"] == new_id
    assert sorted(deletes) == ["legacy-a", "legacy-b"]


def test_winner_is_a_row_that_already_has_an_embedding():
    """The surviving row must reuse an existing embedding rather than
    leaving the merged chunk unembedded."""
    from scripts.dedupe_course_chunks import plan_migration

    rows = [
        _row("legacy-a", "CAS CS 330", "graph traversal", embedding=None),
        _row("legacy-b", "CAS CS 330", "graph traversal", embedding="[0.3,0.4]", doc="doc-2"),
    ]
    upserts, _ = plan_migration(rows)

    assert upserts[0]["embedding"] == "[0.3,0.4]"
    assert upserts[0]["doc_id"] == "doc-2"


def test_rows_already_on_content_hash_ids_are_untouched():
    """Idempotency: a second run over already-migrated data plans no writes."""
    from scripts.dedupe_course_chunks import plan_migration

    cid = chunk_id("CAS CS 330", "sorting algorithms")
    rows = [_row(cid, "CAS CS 330", "sorting algorithms", embedding="[0.5]")]
    upserts, deletes = plan_migration(rows)

    assert upserts == []
    assert deletes == []


def test_same_text_across_courses_stays_separate():
    from scripts.dedupe_course_chunks import plan_migration

    rows = [
        _row("legacy-a", "CAS CS 330", "big-O notation"),
        _row("legacy-b", "CAS CS 111", "big-O notation"),
    ]
    upserts, deletes = plan_migration(rows)

    assert len(upserts) == 2
    assert len({u["id"] for u in upserts}) == 2
    assert sorted(deletes) == ["legacy-a", "legacy-b"]
