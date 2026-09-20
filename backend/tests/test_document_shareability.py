"""#630: the real document category on chunks, and what may be shared at all.

`index_document_chunks` hardcoded `"category": "document"`. The classifier's
category did reach the indexer — it picks the chunking strategy — and was then
dropped at the persist call, so every chunk in the store claimed to be the same
kind of thing. Worse, nothing asked whether the document was the *course's* to
share: completed homework, graded work and private notes all entered the shared
pool on the strength of the uploader's consent flag alone, which is an
academic-integrity problem as well as a privacy one.

The policy matrix lives in tests/test_chunk_visibility.py
(`TestDecideVisibility`). These pin the plumbing: the classifier's new field,
the category reaching the row, and the route feeding both into the decision.
"""
from unittest.mock import MagicMock, patch

import pytest


# ── The classifier's new field ───────────────────────────────────────────────


def test_classifier_declares_the_three_shareability_buckets():
    """One flat Literal, per the #153 output-schema budget — and the same three
    values the service layer decides on. Two lists that must agree, pinned so
    a value added on one side cannot silently become "unknown" (and therefore
    private) on the other."""
    from typing import get_args

    from agents.classifier import DocumentClassification
    from services.chunk_visibility import SHAREABILITY_VALUES

    field = DocumentClassification.model_fields["shareability"]
    # `Shareability | None`, so the Literal sits one level inside the union —
    # and that optionality is itself deliberate: Gemini can omit a
    # non-required field, and an omission has to arrive as None (private,
    # logged) rather than as a value nobody produced.
    members = get_args(field.annotation)
    assert type(None) in members
    literal = [
        a for m in members for a in get_args(m) if isinstance(a, str)
    ]
    assert set(literal) == set(SHAREABILITY_VALUES)


def test_shareability_is_absent_rather_than_guessed():
    """The field has no shareable default. A cassette or a model response that
    omits it must arrive as None — which `decide_visibility` treats as private
    and logs — rather than as a value nobody produced."""
    from agents.classifier import DocumentClassification

    parsed = DocumentClassification.model_validate({
        "category": "lecture_notes",
        "is_syllabus": False,
        "confidence": 0.9,
        "rationale": "narrative notes",
    })
    assert parsed.shareability is None


def test_the_classifier_prompt_defines_every_bucket():
    """A Literal the prompt never explains is a coin flip. The model has to be
    told what each value means, or the field measures nothing."""
    from agents.classifier import _SYSTEM_PROMPT
    from services.chunk_visibility import SHAREABILITY_VALUES

    for value in SHAREABILITY_VALUES:
        assert value in _SYSTEM_PROMPT, value


# ── The category reaching the row ───────────────────────────────────────────


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_stores_the_category_it_is_given(mock_embed):
    mock_embed.return_value = [[0.1] * 768]
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors"), \
         patch("services.chunk_visibility.shares_class_context", return_value=True):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"],
            visibility="shared", category="lecture_notes",
        )
        records = mock_table.return_value.upsert.call_args[0][0]

    assert records[0]["category"] == "lecture_notes"


def test_index_document_chunks_refuses_the_catalog_category():
    """`category='catalog'` is the partition two readers key on —
    `learn._get_catalog_chunk` and the quiz's catalog de-dup. A document row
    claiming it would be served as official BU course data, and the id
    namespaces that keep the two apart would no longer be visible in the row."""
    from services.rag_service import index_document_chunks

    with pytest.raises(ValueError, match="catalog"):
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"],
            visibility="shared", category="catalog",
        )


def test_index_document_chunks_refuses_to_guess_a_category():
    """Required, for the same reason `visibility` is: a `= "document"` default
    would let a new indexing surface reinstate the hardcoded value silently,
    and every existing test would still pass."""
    from services.rag_service import index_document_chunks

    with pytest.raises(TypeError):
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"], visibility="shared",
        )


# ── The route feeds the decision ────────────────────────────────────────────


def _tables_for(courses_rows):
    def _table(name):
        m = MagicMock()
        if name == "courses":
            m.select.return_value = courses_rows
        elif name == "course_chunks":
            m.select.return_value = []
        else:
            m.select.return_value = []
        return m
    return _table


def _run_indexer(**kw):
    from routes.documents import _index_document_chunks

    args = dict(
        doc_id="doc-1",
        course_id="course-uuid-1",
        user_id="user-1",
        extracted_text="some extracted text",
        category="lecture_notes",
        doc_summary="",
        shareability="course_material",
        confidence=0.9,
    )
    args.update(kw)
    _index_document_chunks(**args)


class TestRouteWiring:
    def test_the_classifier_category_reaches_the_chunk_row(self):
        fake = _tables_for([{"course_code": "BIO-101"}])
        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1) as mock_index,
            patch("services.chunk_visibility.decide_visibility", return_value="shared"),
            patch("routes.documents.events_service.log_event"),
        ):
            _run_indexer(category="slides")

        assert mock_index.call_args.kwargs["category"] == "slides"

    def test_shareability_and_confidence_reach_the_decision(self):
        fake = _tables_for([{"course_code": "BIO-101"}])
        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1),
            patch("services.chunk_visibility.decide_visibility", return_value="private") as decide,
            patch("routes.documents.events_service.log_event"),
        ):
            _run_indexer(shareability="completed_work", confidence=0.42)

        assert decide.call_args.args == ("user-1",)
        assert decide.call_args.kwargs == {
            "shareability": "completed_work", "confidence": 0.42,
        }

    def test_completed_work_is_indexed_private_end_to_end(self):
        """No mock on the decision: the route's inputs alone must produce a
        private index for a student's own answers, even though this uploader has
        consented to sharing."""
        fake = _tables_for([{"course_code": "BIO-101"}])
        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1) as mock_index,
            patch("services.chunk_visibility.shares_class_context", return_value=True),
            patch("routes.documents.events_service.log_event"),
        ):
            _run_indexer(shareability="completed_work", confidence=1.0)

        assert mock_index.call_args.kwargs["visibility"] == "private"

    def test_course_material_from_a_consenting_uploader_is_indexed_shared(self):
        fake = _tables_for([{"course_code": "BIO-101"}])
        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1) as mock_index,
            patch("services.chunk_visibility.shares_class_context", return_value=True),
            patch("routes.documents.events_service.log_event"),
        ):
            _run_indexer(shareability="course_material", confidence=0.9)

        assert mock_index.call_args.kwargs["visibility"] == "shared"


# ── The stored decision ─────────────────────────────────────────────────────


def test_the_documents_row_records_its_shareability():
    """Without a stored value, a re-index or backfill has nothing to reproduce
    the decision from, and `decide_visibility(None)` privatises everything —
    exactly the silent corpus loss #628 was."""
    from routes.documents import _persist_document

    inserted: dict = {}

    def _table(name):
        m = MagicMock()
        if name == "documents":
            def _insert(row):
                inserted.update(row)
                return [dict(row)]
            m.insert = _insert
        return m

    result = MagicMock()
    result.classification.category = "assignment"
    result.classification.shareability = "completed_work"
    result.summary.abstract = "abstract"
    result.concepts.concepts = []

    with (
        patch("routes.documents.table", side_effect=_table),
        patch("routes.documents.award_xp_safe"),
        patch("routes.documents.events_service.log_event"),
    ):
        _persist_document(
            user_id="u1", offering_id="off-1", filename="hw4.pdf",
            result=result, request_id=None, course_id="c1", char_count=10,
        )

    assert inserted["shareability"] == "completed_work"


# ── The function-mode seam ──────────────────────────────────────────────────


def test_the_e2e_classifier_handler_supplies_a_shareability():
    """An unsupplied field would make every E2E upload index private — which no
    function-mode assertion would notice, because embedding is disabled below
    the seam and nothing is indexed at all. Keeping the constant honest is the
    only thing that keeps the handler a faithful stand-in."""
    from agents.function_handlers_e2e import E2E_DOC_SHAREABILITY
    from services.chunk_visibility import SHAREABILITY_VALUES

    assert E2E_DOC_SHAREABILITY in SHAREABILITY_VALUES


if __name__ == "__main__":
    pytest.main([__file__])
