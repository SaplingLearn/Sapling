"""
Unit tests for services.document_dedup — file-level duplicate detection.

The RAG corpus is shared per course, so the same lecture deck is uploaded by
many students under many different filenames. Chunk-level content addressing
(rag_service.chunk_id) collapses those to one row, but only *after* OCR and
embedding have already been paid for. These helpers catch the duplicate at the
door, keyed on a fingerprint of the raw bytes, so the expensive work is skipped
entirely.

The fingerprint deliberately covers only the file contents — never the
filename — so `lec3.pdf` and `Lecture 3 Slides.pdf` are recognised as the same
upload.
"""
from unittest.mock import patch

from services.document_dedup import (
    chunks_already_exist,
    decode_result,
    file_sha256,
    find_duplicate,
)
from services.encryption import encrypt_if_present, encrypt_json


def _twin_row(**over):
    """A stored documents row as PostgREST would return it: the sensitive
    columns are ciphertext, exactly as they sit on disk."""
    row = {
        "id": "doc-original",
        "offering_id": "off-bio110-f26",
        "category": "slides",
        "extracted_text": encrypt_if_present("photosynthesis converts light"),
        "summary": encrypt_if_present("A deck on photosynthesis."),
        "concept_notes": encrypt_json([{"name": "Photosynthesis", "description": "d"}]),
    }
    row.update(over)
    return row


class TestFindDuplicate:
    def test_returns_none_when_no_document_has_that_fingerprint(self):
        """A first-time upload must fall through to the normal pipeline."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []

            assert find_duplicate("deadbeef") is None

    def test_returns_the_twin_with_its_columns_decrypted(self):
        """Callers copy these values onto the new row, so they must come back
        as plaintext rather than ciphertext."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [_twin_row()]

            twin = find_duplicate("cafe1234")

        assert twin is not None
        assert twin["id"] == "doc-original"
        assert twin["offering_id"] == "off-bio110-f26"
        assert twin["category"] == "slides"
        assert twin["extracted_text"] == "photosynthesis converts light"
        assert twin["summary"] == "A deck on photosynthesis."
        assert twin["concept_notes"] == [
            {"name": "Photosynthesis", "description": "d"}
        ]

    def test_excludes_deleted_documents(self):
        """A soft-deleted document must not be reused as a source of truth —
        its chunks may already have been cleaned up."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []
            find_duplicate("cafe1234")
            filters = t.return_value.select.call_args.kwargs["filters"]

        assert filters["deleted_at"] == "is.null"
        assert filters["file_sha256"] == "eq.cafe1234"

    def test_returns_the_stored_agent_result_ready_to_replay(self):
        """The twin's whole pipeline result comes back decrypted and parsed, so
        the caller can skip the agents entirely — including for a syllabus,
        whose calendar assignments ride along on it."""
        stored = _syllabus_result()
        row = _twin_row(agent_result=encrypt_if_present(stored.model_dump_json()))
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [row]

            twin = find_duplicate("cafe1234")

        assert twin["result"] == stored
        assert twin["result"].syllabus.assignments[0].title == "PS1"

    def test_result_is_none_when_the_twin_predates_the_column(self):
        """Older rows have no stored result; the caller must fall back to
        running the agents rather than treating None as an empty document."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [_twin_row(agent_result=None)]

            twin = find_duplicate("cafe1234")

        assert twin is not None
        assert twin["result"] is None

    def test_requires_the_twin_to_have_extracted_text(self):
        """A twin whose extraction never completed carries nothing worth
        reusing; treating it as a duplicate would skip OCR and leave the new
        document empty."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [_twin_row(extracted_text=None)]

            assert find_duplicate("cafe1234") is None

    def test_the_query_itself_excludes_rows_with_no_extracted_text(self):
        """Order-independence, enforced at the source rather than by scanning.

        The lookup is `LIMIT 1` with no ORDER BY, so if text-less rows could
        match, the planner would be free to hand back the useless one while a
        perfectly good twin sat behind it — and the post-fetch check below would
        then report "no duplicate" for a file that plainly has one. Filtering in
        the query makes that unreachable: whichever single row comes back is
        usable by construction, in any order.

        Scanning client-side would not fix it — `LIMIT 1` means the database
        only ever sends one row, so there is nothing to scan past.
        """
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []
            find_duplicate("cafe1234")
            filters = t.return_value.select.call_args.kwargs["filters"]

        assert filters["extracted_text"] == "not.is.null"

    def test_returns_none_when_the_column_does_not_exist_yet(self):
        """Deployments ship code before migrations run. A missing
        file_sha256 column must degrade to 'no duplicate', never a 500."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.side_effect = Exception("column does not exist")

            assert find_duplicate("cafe1234") is None


def _syllabus_result():
    """A full pipeline result for a syllabus — the hardest case to replay,
    because the calendar assignments exist nowhere else on the row."""
    from datetime import date

    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.document import DocumentProcessingResult
    from agents.summary import Summary
    from agents.syllabus_extraction import SyllabusAssignment, SyllabusAssignments

    return DocumentProcessingResult(
        classification=DocumentClassification(
            category="syllabus", is_syllabus=True, confidence=0.9, rationale="r",
        ),
        summary=Summary(headline="h", abstract="a", key_points=["1", "2", "3"]),
        concepts=ConceptList(
            concepts=[Concept(name="Mitosis", description="d", importance=0.5)],
        ),
        syllabus=SyllabusAssignments(
            course_title="BIO 110",
            instructor=None,
            assignments=[
                SyllabusAssignment(
                    title="PS1", due_date=date(2026, 4, 1), description=None,
                ),
            ],
        ),
    )


class TestDecodeResult:
    """Storing the whole pipeline result is what makes skipping the agents on a
    duplicate lossless. Rebuilding one field-by-field from the row would mean
    inventing `headline`, three `key_points`, and `importance` — none of which
    are stored — and would drop syllabus assignments entirely."""

    def test_round_trips_a_result_including_syllabus_assignments(self):
        original = _syllabus_result()

        restored = decode_result(original.model_dump_json())

        assert restored == original

    def test_preserves_the_due_dates_the_calendar_import_depends_on(self):
        """save_assignments_to_db reads these; a string where a date belongs
        would silently drop the assignment."""
        from datetime import date

        restored = decode_result(_syllabus_result().model_dump_json())

        assert restored.syllabus.assignments[0].due_date == date(2026, 4, 1)

    def test_returns_none_for_a_row_with_no_stored_result(self):
        """Documents written before this column existed must fall back to
        running the agents, not crash."""
        assert decode_result(None) is None

    def test_returns_none_when_the_stored_shape_no_longer_validates(self):
        """The models evolve. A stored result that no longer parses must
        degrade to re-running the agents rather than raising."""
        assert decode_result('{"classification": {"category": "gone"}}') is None


class TestChunksAlreadyExist:
    """Chunk ids are scoped to the course (rag_service.chunk_id hashes the
    course code alongside the text), so reusing a twin's chunks is only valid
    inside the same course."""

    def test_no_twin_means_the_chunks_must_be_built(self):
        assert chunks_already_exist(None, "off-bio110") is False

    def test_twin_in_the_same_course_means_the_chunks_are_already_there(self):
        """The expensive case this whole feature exists for: the twelfth
        student uploading the same deck to the same course embeds nothing."""
        twin = {"id": "doc-original", "offering_id": "off-bio110"}

        assert chunks_already_exist(twin, "off-bio110") is True

    def test_twin_in_a_different_course_still_needs_its_own_chunks(self):
        """Same textbook, two courses. The text is reusable but the chunks are
        not -- a course-scoped id means BIO 110's chunks do not serve CHEM 101,
        and skipping here would leave the second course with no material."""
        twin = {"id": "doc-original", "offering_id": "off-bio110"}

        assert chunks_already_exist(twin, "off-chem101") is False


class TestFileSha256:
    def test_identical_bytes_produce_the_same_fingerprint(self):
        """The fingerprint is a pure function of the bytes, so two uploads of
        the same file agree no matter what they were named."""
        data = b"%PDF-1.7 lecture three: greedy algorithms"

        assert file_sha256(data) == file_sha256(data)

    def test_different_bytes_produce_different_fingerprints(self):
        """A single changed byte must not collide, or unrelated documents
        would be treated as duplicates of each other."""
        assert file_sha256(b"lecture three") != file_sha256(b"lecture four")
