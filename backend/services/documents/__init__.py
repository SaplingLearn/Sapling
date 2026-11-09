"""
backend/services/documents/ — the documents domain (#118).

- ``upload``: the usable-text floor, the unreadable / failed wording and the
  LLM-budget terminal SSE pair.
- ``persistence``: idempotent replay, the documents insert, and the syllabus /
  graph post-steps.
- ``post_roll``: an upload's best-effort side effects and the SSE route's
  post-roll tasks (``drain_post_roll`` runs at shutdown).
- ``library``: list / soft-delete / update an owned document (async, ``a*``).
- ``scan``: the concept scan (concept_scan_agent -> apply_graph_update).
- ``stream``: the streaming upload's SSE event stream.
- ``errors``: domain errors ``routes/documents.py`` maps to HTTP statuses.

The upload pipeline itself is ``agents/document.py::run_document_agents``;
indexing (``services/document_indexing.py``), the queued upload
(``services/document_jobs.py``), the row read-back
(``services/documents_read.py``) and the progress vocabulary
(``services/document_pipeline.py``) stay flat. Names keep their leading
underscores from the route they came out of, so open PRs against
``routes/documents.py`` re-apply onto the moved bodies; the route re-exports
every one of them.
"""
from __future__ import annotations

from services.documents.errors import ConceptScanFailed, DocumentError
from services.documents.library import (
    list_user_documents,
    soft_delete_document,
    update_document_row,
)
from services.documents.persistence import _existing_doc_by_request_id, _persist_document
from services.documents.post_roll import drain_post_roll
from services.documents.scan import _scan_concepts_for_course
from services.documents.stream import upload_event_stream
from services.documents.upload import (
    MIN_EXTRACTED_CHARS,
    UNREADABLE_DOCUMENT_DETAIL,
    UPLOAD_FAILED_DETAIL,
)

__all__ = [
    "ConceptScanFailed",
    "DocumentError",
    "MIN_EXTRACTED_CHARS",
    "UNREADABLE_DOCUMENT_DETAIL",
    "UPLOAD_FAILED_DETAIL",
    "_existing_doc_by_request_id",
    "_persist_document",
    "_scan_concepts_for_course",
    "drain_post_roll",
    "list_user_documents",
    "soft_delete_document",
    "update_document_row",
    "upload_event_stream",
]
