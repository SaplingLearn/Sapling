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
    _TWIN_COLUMNS,
    chunks_already_exist,
    decode_result,
    file_sha256,
    find_duplicate,
)
from services.encryption import encrypt_if_present


def _twin_row(**over):
    """A stored documents row as PostgREST would return it: the sensitive
    columns are ciphertext, exactly as they sit on disk.

    Only the four columns the lookup actually selects — the routes reuse the
    twin's text and replay its stored result, and read nothing else off it."""
    row = {
        "id": "doc-original",
        "offering_id": "off-bio110-f26",
        "extracted_text": encrypt_if_present("photosynthesis converts light"),
        "agent_result": None,
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
        assert twin["extracted_text"] == "photosynthesis converts light"

    def test_does_not_select_columns_no_caller_reads(self):
        """`category`, `summary` and `concept_notes` used to ride along on every
        lookup — three extra columns and a decrypt each (plus a decrypt_json
        round-trip for the notes) for values both routes take from the replayed
        result instead."""
        for unread in ("category", "summary", "concept_notes"):
            assert unread not in _TWIN_COLUMNS

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
        """Belt and braces with `_pick_twin`'s own check: the candidate window
        is small, so spending a slot on a row that could never be used could
        push the usable twin out of it entirely."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []
            find_duplicate("cafe1234")
            filters = t.return_value.select.call_args.kwargs["filters"]

        assert filters["extracted_text"] == "not.is.null"

    def test_asks_for_several_candidates_in_a_deterministic_order(self):
        """The same bytes legitimately produce many rows (one per uploader, one
        per course) and they are NOT interchangeable — one with a stored
        `agent_result` saves four LLM calls that one without does not. A bare
        unordered `LIMIT 1` let the planner pick; this pins both halves of the
        fix: fetch more than one, and fetch them in a fixed order."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []
            find_duplicate("cafe1234")
            kwargs = t.return_value.select.call_args.kwargs

        assert kwargs["limit"] > 1
        assert kwargs["order"] == "agent_result.asc.nullslast,created_at.asc"

    def test_returns_none_when_the_column_does_not_exist_yet(self):
        """Deployments ship code before migrations run. A missing
        file_sha256 column must degrade to 'no duplicate', never a 500."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.side_effect = Exception("column does not exist")

            assert find_duplicate("cafe1234") is None

    def test_a_lookup_failure_is_logged_and_counted(self, caplog):
        """A permanently broken lookup used to be invisible: the catch logged at
        DEBUG, which sits below production log level, and `None` is ALSO the
        normal answer — so a dropped column, a PostgREST 400 from a filter
        typo, or sustained timeouts left dedup never firing while every upload
        looked healthy. Same WARNING-plus-countable-event treatment
        rag_service.retrieve_chunks gives the identical ambiguity (#482)."""
        with (
            patch("services.document_dedup.table") as t,
            patch("services.document_dedup.log_event") as log_event,
            caplog.at_level("WARNING", logger="services.document_dedup"),
        ):
            t.return_value.select.side_effect = RuntimeError("read timed out")

            assert find_duplicate("cafe1234") is None

        assert any(
            r.levelname == "WARNING" and "duplicate lookup failed" in r.getMessage()
            for r in caplog.records
        ), f"expected a WARNING, got {[r.getMessage() for r in caplog.records]}"
        log_event.assert_called_once()
        assert log_event.call_args.args[0] == "document.dedup_lookup_failed"
        assert log_event.call_args.kwargs["category"] == "error"
        assert log_event.call_args.kwargs["payload"]["error_type"] == "RuntimeError"


class TestFindDuplicateChoosesAmongCandidates:
    """The same bytes legitimately produce MANY rows — one per uploader, one per
    course — and they are not interchangeable. Every test here runs the rows in
    both orders, because the point is that the choice does not depend on the
    order PostgREST happens to return.
    """

    @staticmethod
    def _find(rows, offering_id=None):
        """Run the lookup against `rows` in the given order."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = list(rows)
            return find_duplicate("cafe1234", offering_id)

    def _both_orders(self, rows, offering_id=None):
        return self._find(rows, offering_id), self._find(reversed(rows), offering_id)

    def test_a_row_with_text_wins_over_one_without(self):
        """A text-less row is worthless — reusing it would skip OCR and leave
        the new document empty — so it must never win the slot, even though the
        query already filters for text (a row can also decrypt to nothing)."""
        rows = [
            _twin_row(id="doc-empty", extracted_text=None),
            _twin_row(id="doc-usable"),
        ]

        for twin in self._both_orders(rows):
            assert twin is not None
            assert twin["id"] == "doc-usable"
            assert twin["extracted_text"] == "photosynthesis converts light"

    def test_a_row_with_a_stored_result_wins_over_one_without(self):
        """The expensive difference. Picking the result-less row re-runs the
        classifier, summary, concepts and syllabus agents for nothing."""
        stored = _syllabus_result()
        rows = [
            _twin_row(id="doc-no-result", agent_result=None),
            _twin_row(
                id="doc-replayable",
                agent_result=encrypt_if_present(stored.model_dump_json()),
            ),
        ]

        for twin in self._both_orders(rows):
            assert twin["id"] == "doc-replayable"
            assert twin["result"] is not None

    def test_a_same_offering_row_wins_the_tiebreak(self):
        """Among equally replayable twins, the one from the offering being
        uploaded to wins, so a replay reproduces what this course's other
        students already see."""
        stored = encrypt_if_present(_syllabus_result().model_dump_json())
        rows = [
            _twin_row(id="doc-elsewhere", offering_id="off-chem101", agent_result=stored),
            _twin_row(id="doc-here", offering_id="off-bio110", agent_result=stored),
        ]

        for twin in self._both_orders(rows, offering_id="off-bio110"):
            assert twin["id"] == "doc-here"

    def test_a_stored_result_outranks_the_offering_preference(self):
        """Ordering of the two preferences, pinned: the offering is a tiebreak,
        not the primary key. Preferring the local row here would trade four
        skipped LLM calls for a cosmetic match."""
        rows = [
            _twin_row(id="doc-here-no-result", offering_id="off-bio110", agent_result=None),
            _twin_row(
                id="doc-elsewhere-replayable",
                offering_id="off-chem101",
                agent_result=encrypt_if_present(_syllabus_result().model_dump_json()),
            ),
        ]

        for twin in self._both_orders(rows, offering_id="off-bio110"):
            assert twin["id"] == "doc-elsewhere-replayable"

    def test_every_candidate_being_unusable_is_no_duplicate(self):
        """Not "the first row, empty" — the caller must re-extract."""
        rows = [
            _twin_row(id="doc-a", extracted_text=None),
            _twin_row(id="doc-b", extracted_text=None),
        ]

        for twin in self._both_orders(rows):
            assert twin is None


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

    def test_clears_the_graph_updated_flag_the_original_uploader_left(self):
        """`graph_updated` is run-scoped: it says whether the ORIGINAL uploader's
        knowledge graph gained nodes. Served out of a content-addressed cache it
        would suppress the NEXT student's merge outright — `_graph_backstop`
        returns immediately when it is True — so a replayed result must always
        arrive with it cleared and let its caller recompute it."""
        original = _syllabus_result().model_copy(update={"graph_updated": True})

        restored = decode_result(original.model_dump_json())

        assert restored.graph_updated is False
        # Nothing else is touched: the point is one field, not a re-run.
        assert restored.concepts == original.concepts
        assert restored.syllabus == original.syllabus


class TestChunksAlreadyExist:
    """Whether the chunks can be reused is asked of `course_chunks` itself.

    It used to be inferred from a `documents` row ("these bytes exist in this
    offering, so their chunks must be indexed"), which is false whenever a
    /upload/sync row was written (that route never indexes), whenever
    _index_document_chunks swallowed a failure, whenever it returned early on
    empty chunking or the relevance gate, and whenever a duplicate arrived
    before the fire-and-forget task ran. Each of those left a row that
    suppressed indexing for that material permanently.

    Scoped by COURSE CODE, which is what rag_service.chunk_id actually hashes —
    two offerings of the same course share their chunk rows.
    """

    @staticmethod
    def _ids(course_code, chunks):
        from services.rag_service import chunk_id

        return [chunk_id(course_code, c) for c in chunks]

    def test_nothing_to_look_up_is_not_a_reason_to_skip(self):
        assert chunks_already_exist("CAS BI 110", []) is False
        assert chunks_already_exist("", ["a chunk"]) is False

    def test_the_chunks_being_present_means_they_are_already_there(self):
        """The expensive case this whole feature exists for: the twelfth student
        uploading the same deck to the same course embeds nothing."""
        chunks = ["light reactions", "calvin cycle", "photorespiration"]
        present = self._ids("CAS BI 110", [chunks[0], chunks[-1]])
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [{"id": i} for i in present]

            assert chunks_already_exist("CAS BI 110", chunks) is True
            filters = t.return_value.select.call_args.kwargs["filters"]

        # Queried by the real chunk ids, in course_chunks — not by a documents row.
        assert t.call_args[0][0] == "course_chunks"
        for chunk_hash in present:
            assert chunk_hash in filters["id"]

    def test_a_course_with_no_chunks_indexes_even_when_the_bytes_are_known(self):
        """The regression that made this rewrite necessary: A uploads a syllabus
        through /upload/sync, which persists text + fingerprint and indexes
        nothing, then B uploads the same bytes to the same course. The old check
        saw A's row and skipped, so the course held ZERO chunks for that
        material forever — every later upload matched the same row."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = []

            assert chunks_already_exist("CAS BI 110", ["light reactions"]) is False

    def test_a_truncated_index_is_not_treated_as_complete(self):
        """Embedding runs in batches of 50 and a batch that fails is dropped
        before the upsert, so the first chunk landing proves nothing about the
        rest. Both ends are checked, and a half-indexed document re-indexes."""
        chunks = [f"chunk {i}" for i in range(120)]
        with patch("services.document_dedup.table") as t:
            t.return_value.select.return_value = [
                {"id": self._ids("CAS BI 110", [chunks[0]])[0]},
            ]

            assert chunks_already_exist("CAS BI 110", chunks) is False

    def test_a_different_course_needs_its_own_chunks(self):
        """Same textbook, two courses. The text is reusable but the chunks are
        not -- the ids hash the course code, so BIO 110's chunks do not serve
        CHEM 101, and skipping would leave CHEM 101 with no material."""
        chunks = ["light reactions", "calvin cycle"]
        with patch("services.document_dedup.table") as t:
            # The corpus holds BIO 110's ids; CHEM 101 asks for its own, which
            # do not match, so PostgREST returns nothing.
            t.return_value.select.return_value = []

            assert chunks_already_exist("CAS CH 101", chunks) is False
            assert self._ids("CAS CH 101", chunks)[0] != self._ids("CAS BI 110", chunks)[0]

    def test_a_failed_lookup_indexes_rather_than_skipping(self):
        """The degrade direction matters: chunk ids are content-addressed and the
        write is an upsert, so a needless re-index costs embeddings, while a
        wrong "already indexed" costs the course its material."""
        with patch("services.document_dedup.table") as t:
            t.return_value.select.side_effect = RuntimeError("read timed out")

            assert chunks_already_exist("CAS BI 110", ["light reactions"]) is False


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
