"""services/document_indexing.py — the one entry point that indexes a document.

#482: indexing was a fire-and-forget post-roll task on the streaming route
only. A failure left a healthy-looking `documents` row whose content was absent
from retrieval forever, the sync route never indexed at all, and nothing could
re-drive a document because the work lived in a closure over request state.

These tests drive `index_document` against an in-memory `documents` table that
honours the PostgREST filters the module actually sends, so the claim's
compare-and-swap is exercised rather than mocked away.
"""
from dataclasses import dataclass

import httpx
import pytest

from services import document_indexing as di
from services.document_indexing import IndexOutcome, index_document
from services.encryption import encrypt_if_present

TEXT = "Gradient descent minimises a loss. " * 60


# ── in-memory PostgREST ──────────────────────────────────────────────────────


def _match_one(row, col, op, val):
    cur = row.get(col)
    if op == "eq":
        return cur is not None and str(cur) == val
    if op == "neq":
        return str(cur) != val
    if op == "is":
        return cur is None if val == "null" else str(cur).lower() == val
    if op == "in":
        return str(cur) in val.strip("()").split(",")
    if op == "lt":
        return cur is not None and str(cur) < val
    raise AssertionError(f"filter op {op!r} not modelled")


def _matches(row, filters):
    for key, cond in (filters or {}).items():
        if key == "or":
            parts = [p.split(".", 2) for p in cond.strip("()").split(",")]
            if not any(_match_one(row, c, o, v) for c, o, v in parts):
                return False
            continue
        op, _, val = cond.partition(".")
        if not _match_one(row, key, op, val):
            return False
    return True


class FakeDB:
    def __init__(self):
        self.documents: dict[str, dict] = {}
        self.updates: list[tuple[dict, dict]] = []

    def table(self, name):
        db = self

        class _T:
            def select(self, columns="*", filters=None, limit=None, **_):
                if name == "courses":
                    return [{"course_code": "CAS CS 132"}]
                rows = [dict(r) for r in db.documents.values() if _matches(r, filters)]
                return rows[:limit] if limit else rows

            def update(self, data, filters, *, prefer_return_minimal=False):
                assert name == "documents"
                db.updates.append((dict(data), dict(filters)))
                hit = [r for r in db.documents.values() if _matches(r, filters)]
                for r in hit:
                    r.update(data)
                return [] if prefer_return_minimal else [dict(r) for r in hit]

        return _T()


@dataclass
class _Chunks:
    upserted: int
    total: int
    embedding_disabled: bool = False
    embed_error: str | None = None


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(di, "table", fake.table)
    monkeypatch.setattr(di, "offering_course_id", lambda off: "course-1")
    monkeypatch.setattr(di, "_BACKOFF_SECONDS", (0, 0))
    monkeypatch.setattr(di, "_observe_course_relevance", lambda *a, **k: None)
    return fake


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(
        di, "log_event", lambda event_type, **kw: seen.append((event_type, kw))
    )
    return seen


@pytest.fixture
def visibility(monkeypatch):
    seen = {}

    def fake(user_id, *, shareability, confidence):
        seen.update(user_id=user_id, shareability=shareability, confidence=confidence)
        return "shared"

    monkeypatch.setattr(di, "decide_visibility", fake)
    return seen


def _rag(monkeypatch, *results):
    """Script successive rag_service results; an Exception entry is raised."""
    calls = []
    queue = list(results)

    def fake(course_code, doc_id, uploader_id, chunks, *, visibility, category):
        calls.append(dict(course_code=course_code, doc_id=doc_id,
                          uploader_id=uploader_id, n_chunks=len(chunks),
                          visibility=visibility, category=category))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(di, "index_document_chunks_detailed", fake)
    return calls


def _doc(db, doc_id="doc-1", **over):
    row = {
        "id": doc_id, "user_id": "u1", "offering_id": "off-1",
        "category": "lecture_notes", "shareability": "course_material",
        "shareability_confidence": 0.91,
        "extracted_text": encrypt_if_present(TEXT),
        "summary": encrypt_if_present("an abstract"),
        "deleted_at": None,
        "index_status": "pending", "index_attempts": 0,
        "index_leased_at": None, "index_chunk_count": None, "index_error": None,
    }
    row.update(over)
    db.documents[doc_id] = row
    return row


def _http(status):
    req = httpx.Request("POST", "http://localhost:54321/rest/v1/course_chunks")
    return httpx.HTTPStatusError(
        f"{status}", request=req, response=httpx.Response(status, request=req)
    )


# ── the happy path reads everything off the row ─────────────────────────────


def test_reads_everything_off_the_row(db, events, visibility, monkeypatch):
    """A sweeper three days later must reconstruct the identical work."""
    _doc(db)
    calls = _rag(monkeypatch, _Chunks(upserted=4, total=4))

    out = index_document("doc-1")

    assert out == IndexOutcome("indexed", 4)
    assert calls[0]["course_code"] == "CAS CS 132"
    assert calls[0]["uploader_id"] == "u1"
    assert calls[0]["category"] == "lecture_notes"
    assert calls[0]["visibility"] == "shared"
    # The stored text, decrypted, went through the category's chunker.
    from services.chunker import chunk_for_category
    assert calls[0]["n_chunks"] == len(chunk_for_category(TEXT, "lecture_notes"))


def test_success_records_the_count_and_releases_the_lease(db, events, visibility,
                                                          monkeypatch):
    row = _doc(db)
    _rag(monkeypatch, _Chunks(upserted=4, total=4))

    index_document("doc-1")

    assert row["index_status"] == "indexed"
    assert row["index_chunk_count"] == 4
    assert row["index_leased_at"] is None
    assert row["index_error"] is None
    assert row["index_attempts"] == 1


# ── #630's decision is reproduced, never re-made ────────────────────────────


def test_the_stored_confidence_reaches_decide_visibility(db, events, visibility,
                                                          monkeypatch):
    """A re-drive must reproduce the original sharing decision from stored
    values. It never re-runs the classifier."""
    _doc(db)
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1")

    assert visibility == {"user_id": "u1", "shareability": "course_material",
                          "confidence": 0.91}


def test_a_row_with_no_stored_confidence_is_not_granted_one(db, events,
                                                            visibility, monkeypatch):
    """Rows from before #482 have no stored confidence. It must reach
    decide_visibility as None — which it resolves PRIVATE — and never be
    invented. scripts/backfill_document_chunks.py used to pass 1.0 here on the
    premise that a stored shareability was already gated; it is not
    (`_persist_document` stores the classifier's raw label), so that re-index
    would publish a low-confidence document to the whole class."""
    _doc(db, shareability_confidence=None)
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1")

    assert visibility["confidence"] is None


# ── function mode is a designed no-op ───────────────────────────────────────


def test_function_mode_is_a_quiet_skip(db, events, visibility, monkeypatch, caplog):
    """Acceptance: an explicit designed no-op, never a traceback the logscan
    oracle would have to allowlist — the allowlist entry that used to cover
    this case also hid #628."""
    row = _doc(db)
    _rag(monkeypatch, _Chunks(upserted=0, total=4, embedding_disabled=True))

    out = index_document("doc-1")

    assert out.status == "skipped"
    assert row["index_status"] == "skipped"
    assert "Traceback" not in caplog.text
    assert not [e for e, _ in events if e == "rag.index_failed"]


# ── retry is driven by the COUNT ────────────────────────────────────────────


def test_a_transient_embed_failure_retries_then_succeeds(db, events, visibility,
                                                          monkeypatch):
    """rag_service swallows embed errors per batch and returns a lower count;
    a transient Gemini failure therefore arrives as a short count, never as an
    exception. Retry has to read the count."""
    _doc(db)
    calls = _rag(monkeypatch, _Chunks(2, 4), _Chunks(3, 4), _Chunks(4, 4))

    out = index_document("doc-1")

    assert out == IndexOutcome("indexed", 4)
    assert len(calls) == 3


def test_a_persistent_shortfall_ends_partial(db, events, visibility, monkeypatch):
    row = _doc(db)
    calls = _rag(monkeypatch, _Chunks(3, 4, embed_error="ServerError"))

    out = index_document("doc-1")

    assert out.status == "partial"
    assert out.chunk_count == 3
    assert row["index_status"] == "partial"
    assert row["index_error"] == "ServerError"
    assert len(calls) == di._INLINE_TRIES
    assert [kw["payload"]["status"] for e, kw in events if e == "rag.index_failed"] \
        == ["partial"]


def test_nothing_embedded_ends_failed(db, events, visibility, monkeypatch):
    row = _doc(db)
    _rag(monkeypatch, _Chunks(0, 4, embed_error="ClientError"))

    out = index_document("doc-1")

    assert out.status == "failed"
    assert row["index_status"] == "failed"
    assert row["index_error"] == "ClientError"


def test_a_transient_http_error_is_retried(db, events, visibility, monkeypatch):
    _doc(db)
    calls = _rag(monkeypatch, _http(503), _Chunks(4, 4))

    assert index_document("doc-1").status == "indexed"
    assert len(calls) == 2


def test_a_bug_fails_on_the_first_attempt(db, events, visibility, monkeypatch):
    """#628 was a TypeError. Retrying a bug only burns rate limit and delays
    the error."""
    row = _doc(db)
    calls = _rag(monkeypatch, TypeError("can't multiply sequence by non-int"))

    out = index_document("doc-1")

    assert out.status == "failed"
    assert out.error == "TypeError"
    assert len(calls) == 1
    assert row["index_error"] == "TypeError"


def test_a_client_error_from_postgrest_is_not_retried(db, events, visibility,
                                                      monkeypatch):
    _doc(db)
    calls = _rag(monkeypatch, _http(400))

    assert index_document("doc-1").status == "failed"
    assert len(calls) == 1


def test_the_error_column_never_carries_exception_text(db, events, visibility,
                                                       monkeypatch):
    """index_error is plaintext and shown on an admin list; an exception
    message can quote document text."""
    row = _doc(db)
    _rag(monkeypatch, ValueError("chunk said: my SSN is 123-45-6789"))

    index_document("doc-1")

    assert row["index_error"] == "ValueError"


# ── terminal failures are never retried ─────────────────────────────────────


@pytest.mark.parametrize("over,error", [
    ({"extracted_text": None}, "no_extracted_text"),
    ({"extracted_text": encrypt_if_present("   ")}, "no_extracted_text"),
])
def test_a_document_with_nothing_to_index_is_terminal(db, events, visibility,
                                                      monkeypatch, over, error):
    """Prod has two of these. Visible as failed, and spent: the sweeper must
    never claim them again."""
    row = _doc(db, **over)
    calls = _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1")

    assert out == IndexOutcome("failed", 0, error)
    assert row["index_attempts"] == di.INDEX_MAX_ATTEMPTS
    assert calls == []


def test_a_missing_offering_is_terminal(db, events, visibility, monkeypatch):
    row = _doc(db)
    monkeypatch.setattr(di, "offering_course_id", lambda off: None)
    _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1").error == "no_course"
    assert row["index_attempts"] == di.INDEX_MAX_ATTEMPTS


def test_a_deleted_document_is_not_indexed(db, events, visibility, monkeypatch):
    _doc(db, deleted_at="2026-09-21T00:00:00Z")
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1").error == "no_such_document"
    assert calls == []


# ── the claim: one attempt, one increment, one winner ───────────────────────


def test_an_inline_attempt_spends_one_attempt(db, events, visibility, monkeypatch):
    """A document that crashes the worker must be bounded, so the inline
    attempt claims exactly as a sweeper would."""
    row = _doc(db)
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1")

    assert row["index_attempts"] == 1


def test_losing_the_claim_does_nothing(db, events, visibility, monkeypatch):
    """The post-roll and the sweeper can both see a pending row. Whoever flips
    it to 'indexing' first wins; the loser must not index it again."""
    _doc(db, index_status="indexing", index_attempts=1,
         index_leased_at="2999-01-01T00:00:00Z")
    calls = _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1")

    assert out.status == "indexing"
    assert calls == []


def test_the_claim_is_a_compare_and_swap_on_attempts(db, events, visibility,
                                                     monkeypatch):
    """Two claimers that both read attempts=0 cannot both win: the second
    update's `index_attempts=eq.0` no longer matches."""
    _doc(db)
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1")

    claim_filters = db.updates[0][1]
    assert claim_filters["index_attempts"] == "eq.0"
    assert claim_filters["index_status"] == "in.(pending,partial,failed)"


def test_a_sweeper_claimed_row_is_not_claimed_again(db, events, visibility,
                                                    monkeypatch):
    """claimed=True: the SQL claim already incremented index_attempts. A second
    claim would double-count and halve the retry budget."""
    row = _doc(db, index_status="indexing", index_attempts=2,
               index_leased_at="2026-09-21T00:00:00Z")
    _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1", claimed=True)

    assert out.status == "indexed"
    assert row["index_attempts"] == 2


def test_an_exhausted_row_is_not_re_driven(db, events, visibility, monkeypatch):
    _doc(db, index_status="failed", index_attempts=di.INDEX_MAX_ATTEMPTS)
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1").status == "failed"
    assert calls == []


# ── force: the operator's override ──────────────────────────────────────────


def test_indexed_is_a_noop_unless_forced(db, events, visibility, monkeypatch):
    _doc(db, index_status="indexed", index_chunk_count=4, index_attempts=1)
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1") == IndexOutcome("indexed", 4)
    assert calls == []

    assert index_document("doc-1", force=True).status == "indexed"
    assert len(calls) == 1


def test_force_resets_the_budget_of_an_exhausted_row(db, events, visibility,
                                                     monkeypatch):
    row = _doc(db, index_status="failed", index_attempts=di.INDEX_MAX_ATTEMPTS,
               index_error="ClientError")
    _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1", force=True)

    assert out.status == "indexed"
    assert row["index_attempts"] == 1
    assert row["index_error"] is None


def test_force_does_not_steal_a_live_lease(db, events, visibility, monkeypatch):
    """A sweeper actively indexing this row must not be raced by an admin."""
    _doc(db, index_status="indexing", index_attempts=1,
         index_leased_at="2999-01-01T00:00:00Z")
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1", force=True).status == "indexing"
    assert calls == []


def test_force_may_take_an_expired_lease(db, events, visibility, monkeypatch):
    """A crash can strand a row in 'indexing'; force is how an operator frees
    it without waiting for the sweeper."""
    _doc(db, index_status="indexing", index_attempts=1,
         index_leased_at="2000-01-01T00:00:00Z")
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("doc-1", force=True).status == "indexed"
    assert len(calls) == 1


# ── shipping ahead of the migration ─────────────────────────────────────────


def test_without_the_status_columns_it_still_indexes(db, events, visibility,
                                                     monkeypatch):
    """Code ahead of its migration must behave exactly as it did before #482 —
    index the document — rather than silently stop indexing, which is what
    #629's code-ahead-of-migration window did to retrieval on staging."""
    row = _doc(db)
    for col in ("index_status", "index_attempts", "index_leased_at",
                "index_chunk_count", "index_error", "shareability_confidence"):
        row.pop(col)
    calls = _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1")

    assert out.status == "indexed"
    assert len(calls) == 1
    assert db.updates == []


# ── events ──────────────────────────────────────────────────────────────────


def test_a_recovery_is_counted(db, events, visibility, monkeypatch):
    _doc(db, index_status="indexing", index_attempts=2,
         index_leased_at="2026-09-21T00:00:00Z")
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1", claimed=True)

    recovered = [kw for e, kw in events if e == "rag.index_recovered"]
    assert recovered and recovered[0]["payload"] == {
        "doc_id": "doc-1", "attempts": 2, "chunk_count": 4}


def test_a_first_time_success_is_not_a_recovery(db, events, visibility, monkeypatch):
    _doc(db)
    _rag(monkeypatch, _Chunks(4, 4))

    index_document("doc-1")

    assert not [e for e, _ in events if e == "rag.index_recovered"]


def test_events_carry_ids_and_classes_only(db, events, visibility, monkeypatch):
    _doc(db)
    _rag(monkeypatch, ValueError("quoting the document: private text"))

    index_document("doc-1")

    (kw,) = [kw for e, kw in events if e == "rag.index_failed"]
    assert kw["category"] == "error"
    assert kw["payload"] == {"doc_id": "doc-1", "status": "failed",
                             "error_type": "ValueError", "attempts": 1}


def test_the_new_event_types_are_in_the_pinned_taxonomy():
    """log_event never enforces membership, so an unregistered type is simply
    invisible to every rollup — which is how #501's first draft nearly shipped
    blind."""
    from services import events_service

    source = open(events_service.__file__).read()
    for event_type in ("rag.index_failed", "rag.index_recovered"):
        assert f'"{event_type}"' in source, event_type


def test_no_such_document_writes_nothing(db, events, visibility, monkeypatch):
    calls = _rag(monkeypatch, _Chunks(4, 4))

    assert index_document("nope").error == "no_such_document"
    assert calls == [] and db.updates == []


# ── review round 1: nothing escapes unrecorded ──────────────────────────────


def test_a_failure_before_the_rag_call_is_recorded_not_stranded(db, events,
                                                                visibility, monkeypatch):
    """The claim has already spent the attempt and set a lease. An exception
    that escaped here used to skip _finish and _report: the row sat in
    'indexing' with no error class until the lease expired, and once the
    budget was gone it sat there for good, invisible to the admin list's error
    column. The courses read is one such raiser — a transient 5xx."""
    row = _doc(db)
    monkeypatch.setattr(di, "_course_code", lambda off: (_ for _ in ()).throw(_http(503)))
    calls = _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1")

    assert out == IndexOutcome("failed", 0, "HTTPStatusError")
    assert row["index_status"] == "failed"
    assert row["index_error"] == "HTTPStatusError"
    assert row["index_leased_at"] is None
    assert calls == []
    assert [kw["payload"]["error_type"] for e, kw in events if e == "rag.index_failed"] \
        == ["HTTPStatusError"]


def test_text_under_another_key_is_never_indexed_as_content(db, events, visibility,
                                                             monkeypatch):
    """decrypt_if_present falls back to the RAW value on failure. A re-drive
    from a process holding the wrong ENCRYPTION_KEY would then have chunked the
    base64 ciphertext and indexed it as course material. extracted_text has
    been encrypted since the column was added (0030), so there is no legacy
    plaintext to tolerate: decrypt strictly and refuse."""
    row = _doc(db, extracted_text="bm90LXVuZGVyLXRoaXMta2V5LWF0LWFsbA==")
    calls = _rag(monkeypatch, _Chunks(4, 4))

    out = index_document("doc-1")

    assert out.status == "failed"
    assert out.error == "decrypt_failed"
    assert calls == []
    # An environment problem, not the document's: the budget is NOT spent, so
    # the same row indexes the next time a correctly-keyed process drives it.
    assert row["index_attempts"] < di.INDEX_MAX_ATTEMPTS


# ── review round 1: a process that cannot embed changes nothing ─────────────


def test_a_forced_re_drive_that_cannot_embed_leaves_the_row_as_it_was(
        db, events, visibility, monkeypatch):
    """`skipped` is a property of the PROCESS (embedding is off here), not of
    the document. Recorded on a re-drive it was a trap: skipped is terminal, so
    the document left the sweeper's queue, the admin list and the backfill's
    default targets. Running scripts/backfill_document_chunks.py from a shell
    that still had the E2E function-mode export would have moved every
    unfinished document out of every recovery path — while printing that the
    run had failed and should be repeated in real mode."""
    row = _doc(db, index_status="failed", index_attempts=2, index_error="ServerError",
               index_chunk_count=0)
    _rag(monkeypatch, _Chunks(upserted=0, total=4, embedding_disabled=True))

    out = index_document("doc-1", force=True)

    assert out.status == "skipped"          # the caller is told what happened
    assert row["index_status"] == "failed"  # ...and the row is not
    assert row["index_attempts"] == 2
    assert row["index_error"] == "ServerError"
    assert row["index_leased_at"] is None


def test_a_forced_re_drive_of_an_indexed_row_that_cannot_embed_stays_indexed(
        db, events, visibility, monkeypatch):
    row = _doc(db, index_status="indexed", index_attempts=1, index_chunk_count=4)
    _rag(monkeypatch, _Chunks(upserted=0, total=4, embedding_disabled=True))

    index_document("doc-1", force=True)

    assert row["index_status"] == "indexed"
    assert row["index_chunk_count"] == 4


def test_a_sweeper_claim_that_cannot_embed_is_returned_to_the_queue(
        db, events, visibility, monkeypatch):
    """The claim already overwrote the status and spent an attempt. Neither
    was real work: back to pending, with the attempt refunded."""
    row = _doc(db, index_status="indexing", index_attempts=2,
               index_leased_at="2026-09-21T00:00:00Z")
    _rag(monkeypatch, _Chunks(upserted=0, total=4, embedding_disabled=True))

    index_document("doc-1", claimed=True)

    assert row["index_status"] == "pending"
    assert row["index_attempts"] == 1
    assert row["index_leased_at"] is None


def test_a_never_attempted_upload_still_records_skipped(db, events, visibility,
                                                        monkeypatch):
    """The acceptance criterion this must not break: in function-mode E2E an
    upload ends 'skipped', an explicit designed no-op."""
    row = _doc(db)   # pending, attempts 0 — a fresh upload
    _rag(monkeypatch, _Chunks(upserted=0, total=4, embedding_disabled=True))

    index_document("doc-1")

    assert row["index_status"] == "skipped"
