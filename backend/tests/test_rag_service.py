from unittest.mock import MagicMock, patch


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
