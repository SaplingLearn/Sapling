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
        )
    assert count == 3


@patch("services.rag_service._client")
def test_index_document_chunks_empty_returns_zero(mock_client):
    from services.rag_service import index_document_chunks
    count = index_document_chunks("CAS CS 330", "doc-1", "user-1", [])
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

        index_document_chunks("CAS CS 330", "doc-a", "user-1", ["memoization basics"])
        id_from_doc_a = mock_table.return_value.upsert.call_args[0][0][0]["id"]

        index_document_chunks("CAS CS 330", "doc-b", "user-2", ["memoization basics"])
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

        index_document_chunks("CAS CS 330", "doc-a", "user-1", ["memoization basics"])
        id_cs330 = mock_table.return_value.upsert.call_args[0][0][0]["id"]

        index_document_chunks("CAS CS 111", "doc-a", "user-1", ["memoization basics"])
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
        )
        records = mock_table.return_value.upsert.call_args[0][0]

    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)) == 2
    assert count == 2


@patch("services.rag_service._embed_documents_batch")
def test_index_document_chunks_handles_embedding_failure(mock_embed):
    """Test that embedding failures are caught and records are still upserted with embedding=None."""
    mock_embed.side_effect = Exception("API error")
    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks

        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-fail",
            uploader_id="user-xyz",
            chunks=["chunk one", "chunk two", "chunk three"],
        )

        # Function completes without raising an exception
        assert count == 3

        # Records were still upserted
        mock_table.return_value.upsert.assert_called_once()
        upsert_records = mock_table.return_value.upsert.call_args[0][0]

        # All records have embedding=None since embedding failed
        assert all(rec["embedding"] is None for rec in upsert_records)
        assert len(upsert_records) == 3


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


def test_retrieve_chunks_never_reaches_transport_in_function_mode(monkeypatch, capsys):
    """Pre-#439, retrieve_chunks ignored SAPLING_MODEL_MODE entirely and always
    called through to the real cached client — only the suite's autouse
    `_hermetic_llm_transport` guard (#379) accidentally caught the resulting
    network attempt, producing an 'unstubbed LLM egress' failure message that
    retrieve_chunks' own except then swallowed into `[]`. Post-fix the mode
    gate raises before ever reaching google-genai's transport, so that
    message must never appear — the swallowed message names
    SAPLING_MODEL_MODE instead.
    """
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    from services.rag_service import retrieve_chunks

    with patch("services.rag_service.rpc") as mock_rpc:
        result = retrieve_chunks("dynamic programming", course_id="CAS CS 330")

    assert result == []
    mock_rpc.assert_not_called()
    captured = capsys.readouterr()
    assert "unstubbed LLM egress" not in captured.out
    assert "SAPLING_MODEL_MODE" in captured.out


def test_index_document_chunks_never_reaches_transport_in_function_mode(monkeypatch, capsys):
    """Same proof as above for the batch/document embed path used by document
    upload indexing — the deterministic no-op is count-with-embedding=None,
    same shape as test_index_document_chunks_handles_embedding_failure, but
    now reached by the mode gate rather than a real API error."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    from services.rag_service import index_document_chunks

    with patch("services.rag_service.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-func-mode",
            uploader_id="user-1",
            chunks=["chunk one", "chunk two"],
        )

    assert count == 2
    upsert_records = mock_table.return_value.upsert.call_args[0][0]
    assert all(rec["embedding"] is None for rec in upsert_records)
    captured = capsys.readouterr()
    assert "unstubbed LLM egress" not in captured.out
    assert "SAPLING_MODEL_MODE" in captured.out
