"""#482: what `_persist_document` must write so a document is recoverable.

`extracted_text` used to be written by the indexer, which made the recovery
path depend on the thing that failed: a document whose indexer never ran had
no text for a backfill to work from. It is now written at insert, alongside the
classifier confidence a re-drive needs and the row's place in the indexing
queue.
"""
from unittest.mock import MagicMock, patch

from services.encryption import decrypt_if_present


def _result(confidence=0.91):
    result = MagicMock()
    result.classification.category = "lecture_notes"
    result.classification.shareability = "course_material"
    result.classification.confidence = confidence
    result.summary.abstract = "abstract"
    result.concepts.concepts = []
    return result


def _persist(*, extracted_text="gradient descent notes", confidence=0.91,
             insert_side_effect=None):
    from routes.documents import _persist_document

    calls: list[dict] = []

    def _table(name):
        m = MagicMock()
        if name == "documents":
            def _insert(row):
                calls.append(dict(row))
                if insert_side_effect:
                    exc = insert_side_effect(len(calls))
                    if exc:
                        raise exc
                # PostgREST returns the stored row, ciphertext and all.
                return [dict(row)]
            m.insert = _insert
        return m

    with (
        patch("routes.documents.table", side_effect=_table),
        patch("routes.documents.award_xp_safe"),
        patch("routes.documents.events_service.log_event"),
    ):
        doc_id, full_row = _persist_document(
            user_id="u1", offering_id="off-1", filename="f.pdf",
            result=_result(confidence), request_id="req-1",
            course_id="c1", char_count=22, extracted_text=extracted_text,
        )
    return calls, full_row


def test_extracted_text_is_stored_at_insert_and_encrypted():
    """The recovery path must not depend on the indexer having run."""
    calls, _ = _persist()
    stored = calls[-1]["extracted_text"]
    assert stored != "gradient descent notes"
    assert decrypt_if_present(stored) == "gradient descent notes"


def test_extracted_text_ciphertext_never_reaches_the_client():
    """/upload/sync returns this row to the client verbatim (no response
    model). The text is the whole document; its ciphertext has no business in
    an API response."""
    _, full_row = _persist()
    assert "extracted_text" not in full_row


def test_the_classifier_confidence_is_stored():
    """decide_visibility reads a missing confidence as private (#630), so a
    re-drive that cannot read it back would silently privatise a document that
    was correctly shared."""
    calls, _ = _persist(confidence=0.91)
    assert calls[-1]["shareability_confidence"] == 0.91


def test_a_non_numeric_confidence_is_stored_as_absent():
    """Never write something the 0..1 CHECK constraint will reject."""
    calls, _ = _persist(confidence=None)
    assert calls[-1]["shareability_confidence"] is None


def test_the_row_is_enqueued_for_indexing():
    calls, _ = _persist()
    assert calls[-1]["index_status"] == "pending"
    assert calls[-1]["index_attempts"] == 0


def test_the_index_columns_are_droppable_before_their_migration_runs():
    """Code can ship ahead of the migration: each new column the error names
    is dropped and the upload still succeeds."""
    def names(col):
        return Exception(
            "{'code': 'PGRST204', 'message': \"Could not find the "
            f"'{col}' column of 'documents' in the schema cache\"}}"
        )
    absent = {1: names("index_status"), 2: names("index_attempts"),
              3: names("shareability_confidence")}

    calls, _ = _persist(insert_side_effect=lambda n: absent.get(n))

    final = calls[-1]
    assert len(calls) == 4
    for col in ("index_status", "index_attempts", "shareability_confidence"):
        assert col not in final
    # The replay key survives: dropping it would let a same-X-Request-ID
    # retry persist a duplicate document.
    assert final["request_id"] == "req-1"
    # extracted_text predates this migration (0030) and is not droppable.
    assert "extracted_text" in final


def test_no_text_stores_nothing_rather_than_an_empty_ciphertext():
    calls, _ = _persist(extracted_text=None)
    assert calls[-1]["extracted_text"] is None
