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


# ── #630 review: the not-yet-migrated retry must stay an escape hatch ───────


class TestPersistRetry:
    """`_persist_document` retries the INSERT without `request_id` /
    `shareability` so code can ship ahead of its migration. Keyed on which
    columns happen to be in the row, that became a UNIVERSAL retry the moment
    `shareability` started being set unconditionally: any insert failure would
    trigger a blind second insert with `request_id` STRIPPED — defeating the
    idempotent-replay detection it exists for — and would surface the retry's
    exception instead of the real one."""

    @staticmethod
    def _result():
        result = MagicMock()
        result.classification.category = "lecture_notes"
        result.classification.shareability = "course_material"
        result.summary.abstract = "abstract"
        result.concepts.concepts = []
        return result

    def _persist(self, insert_side_effect):
        from routes.documents import _persist_document

        calls: list[dict] = []

        def _table(name):
            m = MagicMock()
            if name == "documents":
                def _insert(row):
                    calls.append(dict(row))
                    exc = insert_side_effect(len(calls))
                    if exc:
                        raise exc
                    return [dict(row)]
                m.insert = _insert
            return m

        with (
            patch("routes.documents.table", side_effect=_table),
            patch("routes.documents.award_xp_safe"),
            patch("routes.documents.events_service.log_event"),
        ):
            _persist_document(
                user_id="u1", offering_id="off-1", filename="f.pdf",
                result=self._result(), request_id="req-1",
                course_id="c1", char_count=10,
            )
        return calls

    def test_a_missing_column_error_retries_without_THAT_column(self):
        """Only the column the error names is dropped. This test used to assert
        both went — which was pinning the defect the #484 review found: losing
        `request_id` stops a same-X-Request-ID retry from being recognised as a
        replay, so the orchestrator re-runs and persists a duplicate document."""
        def fail_first(n):
            if n == 1:
                return Exception(
                    "{'code': 'PGRST204', 'message': \"Could not find the "
                    "'shareability' column of 'documents' in the schema cache\"}"
                )
            return None

        calls = self._persist(fail_first)

        assert len(calls) == 2
        assert "shareability" in calls[0]
        assert "shareability" not in calls[1]
        assert calls[1]["request_id"] == "req-1"

    def test_an_unrelated_insert_failure_is_raised_not_retried(self):
        """An FK violation or a transport error must surface as itself. Retrying
        it silently strips `request_id`, and the caller is then told about the
        second failure rather than the first."""
        from routes.documents import _persist_document  # noqa: F401

        boom = Exception(
            'insert or update on table "documents" violates foreign key '
            'constraint "documents_offering_id_fkey"'
        )

        with pytest.raises(Exception, match="foreign key"):
            self._persist(lambda n: boom)

    def test_the_retry_happens_at_most_once(self):
        """A second missing-column failure is a real problem, not another
        column to drop."""
        missing = Exception("PGRST204 could not find the column")

        with pytest.raises(Exception, match="PGRST204"):
            self._persist(lambda n: missing)


# ── #484 review: the escape hatch was dead code ─────────────────────────────


class TestMissingColumnDetection:
    """`db/connection.py` raises through httpx's `raise_for_status()`, whose
    message is only `Client error '400 Bad Request' for url …` plus an MDN link.
    The PostgREST payload naming the absent column is in the RESPONSE BODY and
    never in the exception string — so the first version of this guard, which
    read `str(exc)`, could never fire. That made the ship-code-before-migration
    escape hatch it was written to preserve into dead code, and left every
    upload failing where the older key-based retry had succeeded."""

    @staticmethod
    def _http_400(body: str):
        import httpx

        req = httpx.Request("POST", "http://localhost:54321/rest/v1/documents")
        resp = httpx.Response(400, request=req, text=body)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return e
        raise AssertionError("expected raise_for_status to raise")

    def test_the_column_is_read_off_the_response_body(self):
        from routes.documents import _missing_column

        exc = self._http_400(
            '{"code":"PGRST204","message":"Could not find the '
            "'shareability' column of 'documents' in the schema cache\"}"
        )
        assert _missing_column(exc) == "shareability"

    def test_request_id_is_named_when_it_is_the_absent_one(self):
        from routes.documents import _missing_column

        exc = self._http_400(
            '{"code":"PGRST204","message":"Could not find the '
            "'request_id' column of 'documents' in the schema cache\"}"
        )
        assert _missing_column(exc) == "request_id"

    def test_an_unrelated_failure_names_no_column(self):
        from routes.documents import _missing_column

        exc = self._http_400(
            '{"code":"23503","message":"insert or update on table '
            '\\"documents\\" violates foreign key constraint"}'
        )
        assert _missing_column(exc) is None

    def test_a_missing_column_we_do_not_drop_names_nothing(self):
        """Only the two columns this route is willing to ship ahead of are
        droppable. Anything else absent is a real schema problem and must
        surface, not be retried away."""
        from routes.documents import _missing_column

        exc = self._http_400(
            '{"code":"PGRST204","message":"Could not find the '
            "'offering_id' column of 'documents' in the schema cache\"}"
        )
        assert _missing_column(exc) is None

    def test_an_exception_with_no_response_falls_back_to_its_text(self):
        from routes.documents import _missing_column

        assert _missing_column(
            Exception("PGRST204 Could not find the 'shareability' column")
        ) == "shareability"


class TestRetryDropsOnlyTheNamedColumn:
    """In the window this exists for, exactly ONE column is absent. Dropping
    both loses `request_id` — so a client retrying with the same X-Request-ID is
    no longer recognised as a replay, the whole orchestrator re-runs and a
    duplicate document is persisted. That defeats the only thing `request_id`
    is for."""

    @staticmethod
    def _result():
        result = MagicMock()
        result.classification.category = "lecture_notes"
        result.classification.shareability = "course_material"
        result.summary.abstract = "abstract"
        result.concepts.concepts = []
        return result

    def _persist(self, body):
        import httpx

        from routes.documents import _persist_document

        calls: list[dict] = []

        def _table(name):
            m = MagicMock()
            if name == "documents":
                def _insert(row):
                    calls.append(dict(row))
                    if len(calls) == 1:
                        req = httpx.Request("POST", "http://x/rest/v1/documents")
                        httpx.Response(400, request=req, text=body).raise_for_status()
                    return [dict(row)]
                m.insert = _insert
            return m

        with (
            patch("routes.documents.table", side_effect=_table),
            patch("routes.documents.award_xp_safe"),
            patch("routes.documents.events_service.log_event"),
        ):
            _persist_document(
                user_id="u1", offering_id="off-1", filename="f.pdf",
                result=self._result(), request_id="req-1",
                course_id="c1", char_count=10,
            )
        return calls

    def test_a_missing_shareability_keeps_request_id(self):
        calls = self._persist(
            '{"code":"PGRST204","message":"Could not find the '
            "'shareability' column of 'documents' in the schema cache\"}"
        )
        assert len(calls) == 2
        assert "shareability" not in calls[1]
        assert calls[1]["request_id"] == "req-1"

    def test_a_missing_request_id_keeps_shareability(self):
        calls = self._persist(
            '{"code":"PGRST204","message":"Could not find the '
            "'request_id' column of 'documents' in the schema cache\"}"
        )
        assert len(calls) == 2
        assert "request_id" not in calls[1]
        assert calls[1]["shareability"] == "course_material"


def test_every_registered_classifier_handler_answers_shareability():
    """#484 review: `function_handlers_showcase.py` has its own `classifier`
    handler and was missed, so every showcase upload stored NULL, logged a
    WARNING and indexed private. Pinning one module's constant could not catch
    that; pinning the invariant across both modules can."""
    import importlib

    from services.chunk_visibility import SHAREABILITY_VALUES

    for module in (
        "agents.function_handlers_e2e",
        "agents.function_handlers_showcase",
    ):
        mod = importlib.import_module(module)
        names = [n for n in dir(mod) if n.endswith("_DOC_SHAREABILITY")]
        assert names, f"{module} declares no *_DOC_SHAREABILITY constant"
        for name in names:
            assert getattr(mod, name) in SHAREABILITY_VALUES, f"{module}.{name}"
