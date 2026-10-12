"""Deleting a document withdraws its retrieval chunks (2026-10 audit).

Before this, DELETE /api/documents/doc/{id} only stamped `deleted_at`;
`course_chunks` kept the document's text and embeddings and
`match_course_chunks` kept serving them — to the owner, and from the shared
pool to classmates.

These run the real chunker and the real content-addressed `chunk_id` over a
small in-memory stand-in for the three tables, so the dedup cases (a shared
row another upload last wrote, a row a classmate also contributes) are
exercised the way production computes them.
"""

from unittest.mock import patch

import pytest

from services import document_deletion
from services.chunk_visibility import PRIVATE, SHARED
from services.chunker import chunk_for_category
from services.encryption import encrypt
from services.rag_service import chunk_id

COURSE = "CS112"
TEXT = (
    "Recursion is a function calling itself on a smaller input until it reaches "
    "a base case. " * 30
)


class FakeTable:
    """Just enough PostgREST: eq./in.() filters on select/update/delete."""

    def __init__(self, rows):
        self.rows = rows

    @staticmethod
    def _match(row, filters):
        for col, expr in (filters or {}).items():
            op, _, val = expr.partition(".")
            if op == "eq" and str(row.get(col)) != val:
                return False
            if op == "in" and str(row.get(col)) not in val.strip("()").split(","):
                return False
        return True

    def select(self, columns="*", filters=None, **_):
        return [dict(r) for r in self.rows if self._match(r, filters)]

    def delete(self, filters):
        gone = [r for r in self.rows if self._match(r, filters)]
        self.rows[:] = [r for r in self.rows if not self._match(r, filters)]
        return gone

    def update(self, data, filters, **_):
        for r in self.rows:
            if self._match(r, filters):
                r.update(data)
        return []


@pytest.fixture
def db():
    tables = {"course_chunks": [], "course_chunk_contributors": [], "documents": []}
    fakes = {name: FakeTable(rows) for name, rows in tables.items()}
    with patch("services.document_deletion.table", side_effect=lambda n: fakes[n]), \
         patch("services.document_deletion._course_code", return_value=COURSE):
        yield tables


def _ids(user, visibility):
    return [
        chunk_id(COURSE, c, visibility=visibility, uploader_id=user if visibility == PRIVATE else None)
        for c in chunk_for_category(TEXT, "lecture_notes")
    ]


def _doc(doc_id="d1", user="u1"):
    return {"id": doc_id, "user_id": user, "offering_id": "off-1",
            "category": "lecture_notes", "extracted_text": encrypt(TEXT)}


def test_private_chunks_are_deleted(db):
    ids = _ids("u1", PRIVATE)
    assert ids
    db["course_chunks"] += [{"id": i, "visibility": PRIVATE, "uploader_id": "u1", "doc_id": "d1"} for i in ids]

    counts = document_deletion.withdraw_document_chunks(_doc())

    assert db["course_chunks"] == []
    assert counts["private_deleted"] == len(set(ids))


def test_shared_chunks_with_no_other_contributor_are_deleted(db):
    ids = _ids("u1", SHARED)
    db["course_chunks"] += [{"id": i, "visibility": SHARED, "uploader_id": "u1", "doc_id": "d1"} for i in ids]
    db["course_chunk_contributors"] += [{"chunk_id": i, "user_id": "u1"} for i in ids]

    document_deletion.withdraw_document_chunks(_doc())

    assert db["course_chunks"] == []
    assert db["course_chunk_contributors"] == []


def test_a_shared_row_a_classmate_also_contributes_stays(db):
    # Same text uploaded by u2 later: ONE row, doc_id/uploader_id name u2's
    # document. Found by recomputing ids, not by doc_id. u1 is released from
    # it; the row stays because it is u2's content too.
    ids = _ids("u1", SHARED)
    db["course_chunks"] += [{"id": i, "visibility": SHARED, "uploader_id": "u2", "doc_id": "d2"} for i in ids]
    db["course_chunk_contributors"] += [{"chunk_id": i, "user_id": u} for i in ids for u in ("u1", "u2")]

    counts = document_deletion.withdraw_document_chunks(_doc())

    assert {r["id"] for r in db["course_chunks"]} == set(ids)
    assert {r["user_id"] for r in db["course_chunk_contributors"]} == {"u2"}
    assert counts["shared_deleted"] == 0


def test_another_users_private_rows_are_never_touched(db):
    theirs = _ids("u2", PRIVATE)
    db["course_chunks"] += [{"id": i, "visibility": PRIVATE, "uploader_id": "u2", "doc_id": "d9"} for i in theirs]

    document_deletion.withdraw_document_chunks(_doc())

    assert len(db["course_chunks"]) == len(set(theirs))


def test_purge_clears_content_and_tombstones_the_row(db):
    row = _doc()
    db["documents"].append({**row, "summary": "enc", "concept_notes": "enc", "flashcards": [], "deleted_at": None})

    document_deletion.purge_document(row, "2026-10-12T00:00:00Z")

    stored = db["documents"][0]
    assert stored["deleted_at"] == "2026-10-12T00:00:00Z"
    for col in document_deletion.CONTENT_COLUMNS:
        assert stored[col] is None


def test_undecryptable_text_falls_back_to_the_doc_id_lookup(db):
    db["course_chunks"].append({"id": "x", "visibility": PRIVATE, "uploader_id": "u1", "doc_id": "d1"})
    row = {**_doc(), "extracted_text": "not-ciphertext"}

    document_deletion.withdraw_document_chunks(row)

    assert db["course_chunks"] == []
