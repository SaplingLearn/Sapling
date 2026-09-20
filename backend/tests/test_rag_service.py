import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


def test_import_succeeds_without_gemini_api_key():
    """#378: rag_service originally built a module-level `genai.Client` at
    import time, and `genai.Client(api_key="")` raises ValueError, so a
    missing GEMINI_API_KEY broke `import main` (via routes/quiz.py ->
    services/rag_service.py) outright.

    #439 went further: client construction is now fully lazy (`_get_client()`,
    reached only from inside a `model_mode() == 'real'` `_embed_*` call), so
    import no longer touches `google.genai.Client` at all regardless of the
    key — `rag._client` starts (and, absent a real-mode embed call, stays) as
    `None`. This pins that behaviour for the whole import graph.

    Run in a subprocess: the modules are already imported in-process, so this is
    the only way to observe import-time behaviour. `load_dotenv` is stubbed out
    first so a developer's backend/.env can't silently re-supply the key and
    make the assertion vacuous.
    """
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    env.update({
        "ENCRYPTION_KEY": "0" * 64,
        "APP_ENV": "test",
        "SUPABASE_URL": "https://dummy.supabase.co",
        "SUPABASE_SERVICE_KEY": "dummy-service-key",
        "SESSION_SECRET": "dummy-session-secret",
    })
    program = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "import os; os.environ.pop('GEMINI_API_KEY', None)\n"
        "import main\n"
        "import services.rag_service as rag\n"
        "assert rag._client is None\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        cwd=backend_root, env=env, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, (
        "importing main without GEMINI_API_KEY failed:\n" + proc.stderr
    )


def _make_embedding_response(vecs: list[list[float]]):
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=v) for v in vecs]
    return resp


def test_client_is_constructed_with_bounded_http_timeout():
    """retrieve_chunks() runs inline on the quiz/tutor request path, so the
    embedding client must carry an explicit HTTP timeout — otherwise a stalled
    Gemini call hangs the request indefinitely."""
    from services.rag_service import _HTTP_TIMEOUT_MS

    assert isinstance(_HTTP_TIMEOUT_MS, int)
    assert 0 < _HTTP_TIMEOUT_MS <= 180_000


@patch("services.rag_service._client")
def test_retrieve_chunks_returns_empty_on_embedding_failure(mock_client):
    """Best-effort contract: a retrieval failure must degrade to [] rather
    than propagating and breaking quiz generation."""
    mock_client.models.embed_content.side_effect = Exception("embed timeout")
    from services.rag_service import retrieve_chunks

    assert retrieve_chunks("dynamic programming", course_id="CAS CS 330") == []


@patch("services.rag_service._client")
def test_retrieve_chunks_uses_retrieval_query_task_type(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.1] * 768])
    with patch("services.rag_service.rpc", return_value=[]):
        from services.rag_service import retrieve_chunks
        retrieve_chunks("what is dynamic programming", course_id="CAS CS 330")

    call_kwargs = mock_client.models.embed_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
    assert config.task_type == "RETRIEVAL_QUERY"


@patch("services.rag_service._client")
def test_index_document_chunks_uses_retrieval_document_task_type(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768])
    with patch("services.rag_service.rpc", return_value=[]), \
         patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-abc",
            uploader_id="user-123",
            chunks=["Dynamic programming covers memoization and tabulation techniques."],
            visibility="shared",
        )

    call_kwargs = mock_client.models.embed_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
    assert config.task_type == "RETRIEVAL_DOCUMENT"


@patch("services.rag_service._client")
def test_index_document_chunks_returns_count(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768] * 3)
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-xyz",
            uploader_id="user-456",
            chunks=["chunk one about sorting", "chunk two about graphs", "chunk three about trees"],
            visibility="shared",
        )
    assert count == 3


@patch("services.rag_service._client")
def test_index_document_chunks_empty_returns_zero(mock_client):
    from services.rag_service import index_document_chunks
    count = index_document_chunks("CAS CS 330", "doc-1", "user-1", [], visibility="shared")
    assert count == 0
    mock_client.models.embed_content.assert_not_called()


@patch("services.rag_service._client")
def test_chunk_ids_are_content_addressed_per_course(mock_client):
    """Identical chunk text in the same course must map to the same chunk id
    regardless of which document or uploader supplied it — 200 students
    uploading the same lecture slides should produce one row per unique
    chunk, not 200 copies of every embedding."""
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768])
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        index_document_chunks("CAS CS 330", "doc-a", "user-1", ["memoization basics"], visibility="shared")
        id_from_doc_a = mock_table.return_value.upsert.call_args[0][0][0]["id"]

        index_document_chunks("CAS CS 330", "doc-b", "user-2", ["memoization basics"], visibility="shared")
        id_from_doc_b = mock_table.return_value.upsert.call_args[0][0][0]["id"]

    assert id_from_doc_a == id_from_doc_b


@patch("services.rag_service._client")
def test_chunk_ids_differ_across_courses(mock_client):
    """The dedup scope is per-course: the same text indexed under two
    different course codes must NOT collide, or one course's doc_id/metadata
    would clobber the other's."""
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768])
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        index_document_chunks("CAS CS 330", "doc-a", "user-1", ["memoization basics"], visibility="shared")
        id_cs330 = mock_table.return_value.upsert.call_args[0][0][0]["id"]

        index_document_chunks("CAS CS 111", "doc-a", "user-1", ["memoization basics"], visibility="shared")
        id_cs111 = mock_table.return_value.upsert.call_args[0][0][0]["id"]

    assert id_cs330 != id_cs111


@patch("services.rag_service._client")
def test_duplicate_chunks_within_one_document_are_deduped(mock_client):
    """A document repeating the same text (boilerplate headers/footers) must
    not emit duplicate ids in a single upsert payload — Postgres rejects
    ON CONFLICT DO UPDATE hitting the same row twice in one statement."""
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768] * 2)
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        count = index_document_chunks(
            "CAS CS 330",
            "doc-a",
            "user-1",
            ["Page header boilerplate", "actual content", "Page header boilerplate"],
            visibility="shared",
        )
        records = mock_table.return_value.upsert.call_args[0][0]

    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)) == 2
    assert count == 2


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_drops_chunks_whose_embedding_failed(mock_embed):
    """A total embedding failure must persist NOTHING and report 0 (#482).

    This test previously asserted the opposite — that the rows were upserted
    with `embedding=None` and the call reported the full chunk count. That was
    pinning a bug, not a contract: `match_course_chunks` ranks by vector
    distance, so a NULL-embedding row can never be returned by retrieval. Those
    rows were unreachable dead weight that still counted toward the "indexed N
    chunks" the caller logs, which is exactly how a total embedding outage read
    as a complete success.
    """
    mock_embed.side_effect = Exception("API error")
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-fail",
            uploader_id="user-xyz",
            chunks=["chunk one", "chunk two", "chunk three"],
            visibility="shared",
        )

        # Still no exception — indexing stays best-effort, as before.
        assert count == 0
        # …but nothing unretrievable is written.
        mock_table.return_value.upsert.assert_not_called()


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_keeps_the_chunks_that_did_embed(mock_embed):
    """A PARTIAL failure keeps the good chunks and drops only the bad ones."""
    # Batch size is 50, so five chunks arrive as one batch; return a short
    # vector list so zip() leaves the tail without an embedding.
    mock_embed.return_value = [[0.1] * 768, [0.2] * 768]
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-partial",
            uploader_id="user-xyz",
            chunks=["one", "two", "three", "four", "five"],
            visibility="shared",
        )

        assert count == 2
        upserted = mock_table.return_value.upsert.call_args[0][0]
        assert len(upserted) == 2
        assert all(rec["embedding"] is not None for rec in upserted)


# ── #439: below-seam RAG embed calls must gate on SAPLING_MODEL_MODE ───────
#
# These call sites (`_embed_query`, `_embed_document`, `_embed_documents_batch`)
# predate the #391 seam and construct a raw `google.genai.Client` directly, so
# they need their own mode check rather than going through `model_for`. In
# non-real mode no client may be constructed and no network call attempted;
# the existing callers' broad try/except (exercised above) then produces the
# exact same deterministic empty/no-op result as an unlucky real-mode
# failure — by design now, not by accident.


def test_embed_query_does_not_construct_client_outside_real_mode(monkeypatch):
    """Force a clean slate (module-level `_client` back to `None`) so this
    exercises the lazy-construction path fresh, rather than reusing whatever
    an earlier real-mode test already cached in the module singleton."""
    import services.rag_service as rag

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setattr(rag, "_client", None)
    ctor = MagicMock(side_effect=AssertionError(
        "genai.Client must not be constructed outside real mode"
    ))
    monkeypatch.setattr(rag.genai, "Client", ctor)

    with pytest.raises(RuntimeError, match="SAPLING_MODEL_MODE"):
        rag._embed_query("dynamic programming")

    ctor.assert_not_called()
    assert rag._client is None


def test_embed_documents_batch_does_not_construct_client_outside_real_mode(monkeypatch):
    import services.rag_service as rag

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setattr(rag, "_client", None)
    ctor = MagicMock(side_effect=AssertionError(
        "genai.Client must not be constructed outside real mode"
    ))
    monkeypatch.setattr(rag.genai, "Client", ctor)

    with pytest.raises(RuntimeError, match="SAPLING_MODEL_MODE"):
        rag._embed_documents_batch(["chunk one", "chunk two"])

    ctor.assert_not_called()
    assert rag._client is None


def test_retrieve_chunks_never_reaches_transport_in_function_mode(monkeypatch, caplog):
    """Pre-#439, retrieve_chunks ignored SAPLING_MODEL_MODE entirely and always
    called through to the real cached client — only the suite's autouse
    `_hermetic_llm_transport` guard (#379) accidentally caught the resulting
    network attempt, producing an 'unstubbed LLM egress' failure message that
    retrieve_chunks' own except then swallowed into `[]`. Post-fix the mode
    gate raises before ever reaching google-genai's transport, so that
    message must never appear — the swallowed message names
    SAPLING_MODEL_MODE instead.

    That message moved from stdout to the logger in #482, and to INFO rather
    than WARNING: the seam firing is by design on every function-mode run, so
    it must not read as a failure or spend an error event.
    """
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    from services.rag_service import retrieve_chunks

    with (
        patch("services.rag_service.rpc") as mock_rpc,
        patch("services.rag_service.log_event") as mock_log_event,
        caplog.at_level("INFO", logger="services.rag_service"),
    ):
        result = retrieve_chunks("dynamic programming", course_id="CAS CS 330")

    assert result == []
    mock_rpc.assert_not_called()
    messages = [r.getMessage() for r in caplog.records]
    assert not any("unstubbed LLM egress" in m for m in messages)
    assert any("SAPLING_MODEL_MODE" in m for m in messages), messages
    # The deliberate seam degrade is not an error — no event, no WARNING.
    mock_log_event.assert_not_called()
    assert not any(r.levelname == "WARNING" for r in caplog.records)


def test_index_document_chunks_never_reaches_transport_in_function_mode(monkeypatch, caplog):
    """Same proof as above for the batch/document embed path used by document
    upload indexing: the mode gate stops it before google-genai's transport.

    The deterministic no-op is now "write nothing, report 0". It used to be
    "write rows with embedding=None and report the full count" — but in
    function mode no embedding can be produced, so those rows were dead on
    arrival: unretrievable by construction, and flagged by the `ragstore`
    oracle. What this test guards is the absence of egress, which is unchanged.

    Per #482 the message is on the logger now, at INFO — dropping every chunk
    is the DESIGNED function-mode outcome, so it must not raise the
    rag.chunks_dropped error event that a real embedding failure does.
    """
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    from services.rag_service import index_document_chunks

    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.log_event") as mock_log_event,
        caplog.at_level("INFO", logger="services.rag_service"),
    ):
        mock_table.return_value.upsert.return_value = []
        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-func-mode",
            uploader_id="user-1",
            chunks=["chunk one", "chunk two"],
            visibility="shared",
        )

    assert count == 0
    mock_table.return_value.upsert.assert_not_called()
    messages = [r.getMessage() for r in caplog.records]
    assert not any("unstubbed LLM egress" in m for m in messages)
    assert any("SAPLING_MODEL_MODE" in m for m in messages), messages
    mock_log_event.assert_not_called()
    assert not any(r.levelname == "WARNING" for r in caplog.records)


def test_document_chunk_ids_never_collide_with_catalog_ids():
    """Document and catalog rows share the course_chunks table and its
    on_conflict=id upsert. The document id keyspace is namespaced with a
    literal "document" segment so a document chunk whose text byte-matches a
    catalog chunk (same course) can never overwrite the catalog row and flip
    its category out from under the category=eq.catalog readers."""
    from scripts.ingest_catalog import chunk_id as catalog_chunk_id
    from services.rag_service import chunk_id as document_chunk_id

    course, text = "CAS CS 132", "This course covers matrices and vector spaces."
    assert document_chunk_id(course, text) != catalog_chunk_id(course, text)
    # Still content-addressed within the document keyspace.
    assert document_chunk_id(course, text) == document_chunk_id(course, text)


# ── #482: RAG failures must reach the app-logging path, not stdout ──────────
#
# retrieve_chunks degrades to [] on ANY failure, and [] is also what "nothing
# relevant matched" looks like. So an ungrounded tutor/quiz turn was
# indistinguishable from a grounded one at every layer above — the only trace
# was a bare `print`, which the app's logging never sees and no rollup can
# count. These pin the degrade as OBSERVABLE; the degrade itself (returning [])
# is pinned by test_retrieve_chunks_returns_empty_on_embedding_failure above
# and deliberately unchanged.


@patch("services.rag_service.log_event")
@patch("services.rag_service._client")
def test_retrieve_chunks_failure_is_logged_and_counted(
    mock_client, mock_log_event, caplog, monkeypatch
):
    # Pin real mode explicitly. _require_real_mode() runs BEFORE the mocked
    # client is reached, so with SAPLING_MODEL_MODE=function exported — which
    # the E2E workflow tells you to export — this would take the
    # _EmbeddingDisabled branch and pass vacuously on an unrelated code path.
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    mock_client.models.embed_content.side_effect = Exception("embed timeout")
    from services.rag_service import retrieve_chunks

    with caplog.at_level("WARNING", logger="services.rag_service"):
        assert retrieve_chunks("dynamic programming", course_id="CAS CS 330") == []

    assert any(
        r.levelname == "WARNING" and "retrieve_chunks failed" in r.getMessage()
        for r in caplog.records
    ), f"expected a WARNING on the app-logging path, got {[r.getMessage() for r in caplog.records]}"

    mock_log_event.assert_called_once()
    event_type = mock_log_event.call_args.args[0]
    assert event_type == "rag.retrieval_failed"
    assert mock_log_event.call_args.kwargs["category"] == "error"


@patch("services.rag_service.log_event")
@patch("services.rag_service.table")
@patch("services.rag_service._embed_documents_batch")
def test_dropped_chunks_are_logged_and_counted(
    mock_embed, mock_table, mock_log_event, caplog
):
    """A failed embed batch drops those chunks rather than persisting
    unretrievable NULL-embedding rows. That drop is silent data loss behind a
    successful-looking upload, so it has to be countable too."""
    mock_embed.side_effect = Exception("embedding backend down")
    from services.rag_service import index_document_chunks

    with caplog.at_level("WARNING", logger="services.rag_service"):
        count = index_document_chunks("CAS CS 330", "doc-1", "user-1", ["alpha", "beta"], visibility="shared")

    # Nothing embedded => nothing persisted, and the caller is told zero.
    assert count == 0
    mock_table.return_value.upsert.assert_not_called()
    assert any("dropped" in r.getMessage() for r in caplog.records), (
        f"expected a WARNING naming the dropped chunks, got "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    assert any(
        c.args and c.args[0] == "rag.chunks_dropped" for c in mock_log_event.call_args_list
    ), "expected a rag.chunks_dropped event"


# --- #628: course relevance over the REAL PostgREST wire format -------------

# PostgREST serialises a pgvector VECTOR column as its TEXT form — a JSON
# *string*, not a JSON array (verified against live staging + prod,
# 2026-09-20). Every fake that hands the code a Python list is testing a
# shape the database never produces, which is how #628 shipped.
def _pgvector_wire(vec: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vec) + "]"


def test_parse_vector_reads_the_postgrest_string_form():
    from services.rag_service import parse_vector

    assert parse_vector("[0.5,-0.25,1.0]") == [0.5, -0.25, 1.0]


def test_parse_vector_passes_a_list_through():
    from services.rag_service import parse_vector

    assert parse_vector([0.5, -0.25]) == [0.5, -0.25]


@patch("services.rag_service.table")
@patch("services.rag_service._embed_document")
def test_course_relevance_scores_against_a_string_catalog_embedding(mock_embed, mock_table):
    mock_embed.return_value = [1.0, 0.0, 0.0]
    mock_table.return_value.select.return_value = [
        {"embedding": _pgvector_wire([1.0, 0.0, 0.0])}
    ]
    from services.rag_service import course_relevance

    assert course_relevance("CAS CS 132", "intro to data structures") == pytest.approx(1.0)


@patch("services.rag_service.table")
@patch("services.rag_service._embed_document")
def test_course_relevance_is_cosine_not_a_raw_dot_product(mock_embed, mock_table):
    """gemini-embedding-001 at 768-d is NOT unit-normalised, and retrieval
    ranks on cosine (`<=>`). A raw dot product here would put the score on a
    different scale from everything else in the system: these two vectors
    point the same way, so the answer is 1.0, not 6.0."""
    mock_embed.return_value = [3.0, 0.0]
    mock_table.return_value.select.return_value = [{"embedding": _pgvector_wire([2.0, 0.0])}]
    from services.rag_service import course_relevance

    assert course_relevance("CAS CS 132", "sample") == pytest.approx(1.0)


@patch("services.rag_service.table")
@patch("services.rag_service._embed_document")
def test_course_relevance_is_none_without_a_catalog_embedding(mock_embed, mock_table):
    """No catalog row => nothing to compare against, and no embed call spent."""
    mock_table.return_value.select.return_value = []
    from services.rag_service import course_relevance

    assert course_relevance("TEST QG 101", "sample") is None
    mock_embed.assert_not_called()


@patch("services.rag_service.table")
@patch("services.rag_service._embed_document")
def test_course_relevance_reads_the_newest_embedded_catalog_row(mock_embed, mock_table):
    """ingest_catalog.py content-addresses catalog rows and never deletes old
    ones, and on a double embed failure it inserts rows with a NULL embedding.
    "First row by sha256 id" could therefore be a stale blurb, or a NULL row
    that silently turns the score into `None` while an embedded row sits right
    beside it. (Semantics pinned for real in the integration lane.)"""
    mock_embed.return_value = [1.0, 0.0]
    select = mock_table.return_value.select
    select.return_value = [{"embedding": _pgvector_wire([1.0, 0.0])}]
    from services.rag_service import course_relevance

    course_relevance("CAS CS 132", "sample")

    kwargs = select.call_args.kwargs
    assert kwargs["filters"]["embedding"] == "not.is.null"
    assert kwargs["order"].startswith("created_at.desc")
    assert kwargs["limit"] == 1


# ── #629: visibility is part of the chunk's identity and of every read ──────
#
# `user_settings.share_class_context` gated the class-aggregate rollup and
# nothing in RAG, so an opted-out student's upload joined the shared course
# pool and surfaced in a classmate's tutor. The persistence half of the fix is
# here: an opted-out upload lands under its own id namespace with
# `visibility='private'`, and every retrieval names the reader so the RPC can
# filter. The policy half (who is opted out, and what the toggle does to rows
# already written) lives in tests/test_chunk_visibility.py.


def test_a_private_chunk_id_never_collides_with_the_shared_one():
    """The whole guarantee rests on this. Shared rows are content-addressed and
    upserted `on_conflict=id` with `resolution=merge-duplicates`, so if an
    opted-out upload hashed to the shared id it would MERGE INTO the classmates'
    row — overwriting its metadata and, worse, leaving the text in the shared
    pool under a row the opt-out cannot reach."""
    from services.rag_service import chunk_id

    course, text = "CAS CS 330", "Dynamic programming trades space for time."
    shared = chunk_id(course, text)
    private = chunk_id(course, text, visibility="private", uploader_id="u1")

    assert private != shared
    # Still content-addressed within the private keyspace...
    assert private == chunk_id(course, text, visibility="private", uploader_id="u1")
    # ...and scoped per uploader, so two opted-out students never share a row.
    assert private != chunk_id(course, text, visibility="private", uploader_id="u2")


def test_the_shared_chunk_id_is_unchanged_by_the_namespace_split():
    """Every shared row already in the table was keyed on this exact string. A
    changed shared hash would silently orphan the entire existing corpus —
    re-uploads would insert duplicates instead of merging."""
    import hashlib

    from services.rag_service import chunk_id

    course, text = "CAS CS 132", "This course covers matrices."
    expected = hashlib.sha256(f"{course}::document::{text}".encode()).hexdigest()
    assert chunk_id(course, text) == expected


def test_a_private_chunk_id_requires_an_uploader():
    """Without one the private namespace would collapse back onto a single
    shared-per-course key, silently re-merging opted-out uploads."""
    from services.rag_service import chunk_id

    with pytest.raises(ValueError):
        chunk_id("CAS CS 330", "text", visibility="private", uploader_id=None)


def test_index_document_chunks_refuses_to_guess_a_visibility():
    """`visibility` is required and keyword-only on purpose. A default would
    make the write side fail OPEN while retrieval fails closed: the next
    indexing surface that forgot the argument would publish to the shared pool
    and reproduce #629 verbatim, with nothing failing in tests because the
    default IS the old behaviour. Omitting it has to be a TypeError."""
    from services.rag_service import index_document_chunks

    with pytest.raises(TypeError):
        index_document_chunks("CAS CS 330", "doc-1", "u1", ["some content"])


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_writes_a_shared_visibility(mock_embed):
    mock_embed.return_value = [[0.1] * 768]
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors"):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["some content"], visibility="shared",
        )
        records = mock_table.return_value.upsert.call_args[0][0]

    assert records[0]["visibility"] == "shared"


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_writes_the_requested_visibility(mock_embed):
    mock_embed.return_value = [[0.1] * 768]
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors"):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["some content"], visibility="private",
        )
        records = mock_table.return_value.upsert.call_args[0][0]

    assert records[0]["visibility"] == "private"
    # …and under the private id namespace, not the shared one.
    from services.rag_service import chunk_id
    assert records[0]["id"] == chunk_id(
        "CAS CS 330", "some content", visibility="private", uploader_id="u1",
    )


@patch("services.rag_service._embed_documents_batch")
def test_a_shared_index_records_the_uploader_as_a_contributor(mock_embed):
    """`uploader_id` is last-writer-wins on a deduped row, so the ledger is the
    only thing that can answer "did this student feed this chunk?" later."""
    mock_embed.return_value = [[0.1] * 768, [0.2] * 768]
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors") as mock_record:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks("CAS CS 330", "doc-1", "u1", ["one", "two"], visibility="shared")
        records = mock_table.return_value.upsert.call_args[0][0]

    mock_record.assert_called_once()
    assert list(mock_record.call_args[0][0]) == [r["id"] for r in records]
    assert mock_record.call_args[0][1] == "u1"


@patch("services.rag_service._embed_documents_batch")
def test_a_private_index_records_no_contributor(mock_embed):
    """Private ids are already uploader-scoped, and keeping them out of the
    ledger is what stops `resync_user_chunk_visibility` from ever flipping one
    back to shared under an id that can never merge."""
    mock_embed.return_value = [[0.1] * 768]
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors") as mock_record:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["one"], visibility="private",
        )

    mock_record.assert_not_called()


@patch("services.rag_service._embed_documents_batch")
def test_nothing_upserted_means_no_contributor_rows(mock_embed):
    mock_embed.side_effect = Exception("API error")
    with patch("services.rag_service.table") as mock_table, \
         patch("services.rag_service.record_contributors") as mock_record:
        from services.rag_service import index_document_chunks
        assert index_document_chunks("CAS CS 330", "doc-1", "u1", ["one"], visibility="shared") == 0

    mock_table.return_value.upsert.assert_not_called()
    mock_record.assert_not_called()


@patch("services.rag_service._client")
def test_retrieve_chunks_passes_the_reader_to_the_rpc(mock_client, monkeypatch):
    """The RPC filters `visibility='shared' OR the reader contributed`, so a
    caller that forgets the reader gets shared rows only — never a leak."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.1] * 768])
    with patch("services.rag_service.rpc", return_value=[]) as mock_rpc:
        from services.rag_service import retrieve_chunks
        retrieve_chunks("query", course_id="CAS CS 330", user_id="u1")

    assert mock_rpc.call_args[0][1]["filter_user_id"] == "u1"


@patch("services.rag_service._client")
def test_retrieve_chunks_without_a_reader_asks_for_shared_rows_only(
    mock_client, monkeypatch
):
    """`None` is the fail-closed default: an offline script or a caller not yet
    threaded through sees the shared pool, not everyone's private uploads."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.1] * 768])
    with patch("services.rag_service.rpc", return_value=[]) as mock_rpc:
        from services.rag_service import retrieve_chunks
        retrieve_chunks("query", course_id="CAS CS 330")

    assert mock_rpc.call_args[0][1]["filter_user_id"] is None


# ── #629 review: the index/opt-out race ─────────────────────────────────────


@patch("services.rag_service._embed_documents_batch")
def test_a_shared_index_reconciles_if_consent_flipped_while_it_ran(mock_embed):
    """Indexing is a detached post-roll thread and the ledger rows cannot be
    written before the chunks they reference (FK), so a student who opts out
    mid-index gets a resync that runs before their ledger rows exist, finds
    nothing, and leaves the chunks published to the class permanently. Re-reading
    consent after the ledger write closes the window."""
    mock_embed.return_value = [[0.1] * 768]
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context", return_value=False),
        patch("services.chunk_visibility.resync_user_chunk_visibility") as mock_resync,
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"], visibility="shared",
        )

    mock_resync.assert_called_once_with("u1")


@patch("services.rag_service._embed_documents_batch")
def test_an_unchanged_consent_costs_no_resync(mock_embed):
    mock_embed.return_value = [[0.1] * 768]
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context", return_value=True),
        patch("services.chunk_visibility.resync_user_chunk_visibility") as mock_resync,
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"], visibility="shared",
        )

    mock_resync.assert_not_called()


@patch("services.rag_service._embed_documents_batch")
def test_a_private_index_never_reconciles(mock_embed):
    """Nothing to withdraw, and a settings round trip per private upload."""
    mock_embed.return_value = [[0.1] * 768]
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context") as mock_consent,
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", ["content"], visibility="private",
        )

    mock_consent.assert_not_called()
