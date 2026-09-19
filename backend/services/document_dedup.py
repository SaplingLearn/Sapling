"""File-level duplicate detection for document uploads.

Sapling's RAG corpus is shared per course, so the same lecture deck arrives
many times under many different filenames. `rag_service.chunk_id` already
collapses identical passages to one row, but only at the *end* of the
pipeline — OCR, the classifier/summary/concepts agents, and embedding have all
been paid for by then.

These helpers catch the duplicate at the door instead, keyed on a SHA-256
fingerprint of the raw uploaded bytes. The fingerprint covers the file contents
only, never the filename, so `lec3.pdf` and `Lecture 3 Slides.pdf` are
recognised as the same upload.
"""
from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from db.connection import table
from services.encryption import decrypt_if_present
from services.events_service import log_event

if TYPE_CHECKING:  # import-cycle guard, see decode_result's lazy import
    from agents.document import DocumentProcessingResult

logger = logging.getLogger(__name__)

# Columns read off the twin. Deliberately narrow: the callers reuse the twin's
# text and replay its stored result, and read nothing else. `category`,
# `summary` and `concept_notes` used to ride along — three extra columns plus a
# decrypt each (and a `decrypt_json` round-trip for the notes) on every upload,
# for values both routes take from the replayed result instead.
# `offering_id` stays because `_pick_twin` prefers a same-offering row.
_TWIN_COLUMNS = "id,offering_id,extracted_text,agent_result"

# How many candidate rows `find_duplicate` pulls before picking one. The same
# bytes legitimately appear once per uploader and once per course, so a popular
# deck has many twins and they are NOT interchangeable: one with a stored
# `agent_result` saves four LLM calls that one without does not. A bare
# `LIMIT 1` let the planner hand back whichever it liked. Small window, because
# the ORDER BY already floats the result-bearing rows to the front — this only
# has to be wide enough to see past a few of them for the offering tiebreak.
_TWIN_CANDIDATES = 5


def file_sha256(file_bytes: bytes) -> str:
    """Return the hex SHA-256 fingerprint of an uploaded file's bytes.

    Deliberately takes only the bytes: the filename must never influence the
    fingerprint, or two students' copies of the same deck would look distinct.
    """
    return hashlib.sha256(file_bytes).hexdigest()


def decode_result(raw: str | None) -> DocumentProcessingResult | None:
    """Rebuild a DocumentProcessingResult from the JSON stored on a document.

    Storing the whole result — rather than rebuilding one from the row's
    category/summary/concept_notes — is what makes skipping the agents on a
    duplicate lossless. A field-by-field reconstruction would have to invent
    `Summary.headline`, three `Summary.key_points` (min_length=3), and each
    `Concept.importance`, none of which are persisted, and would drop
    `syllabus.assignments` entirely — the calendar import's only source.

    Returns None when there is nothing stored (documents predating the column)
    or when the stored shape no longer validates against the current models.
    Both degrade to "run the agents", never to an error: a stale payload must
    not be able to fail an upload.
    """
    if not raw:
        return None
    # Imported here, not at module scope: agents/document.py pulls in the whole
    # agent stack, and this module is imported by the upload route at startup.
    from agents.document import DocumentProcessingResult

    try:
        stored = DocumentProcessingResult.model_validate_json(raw)
    except Exception:
        logger.warning(
            "Stored agent result no longer validates — re-running the agents",
            exc_info=True,
        )
        return None
    # `graph_updated` is RUN-scoped state, not a property of the bytes: it
    # records whether the ORIGINAL uploader's knowledge graph gained nodes.
    # Serving it out of a content-addressed cache lets one student's merge
    # suppress the next student's, because `_graph_backstop` returns
    # immediately when it is True. Every replay path recomputes it for the
    # current user, so it is always cleared here.
    return stored.model_copy(update={"graph_updated": False})


def chunks_already_exist(course_code: str, chunks: list[str]) -> bool:
    """True when this document's RAG chunks are already in the shared corpus.

    Asks `course_chunks` itself. The previous version inferred the answer from
    a `documents` row — "a document with these bytes exists in this offering,
    so its chunks must be indexed" — which is false in four ways, each of which
    left a row that suppressed indexing for that material PERMANENTLY (every
    later upload matched the same row):

      * `/upload/sync` persists a row and never indexes anything.
      * `_index_document_chunks` swallows every exception, so a failed index
        leaves an identical-looking row behind.
      * It returns early when chunking yields nothing and when the course
        relevance gate rejects the document, both after the row is written.
      * It is fire-and-forget, so a duplicate arriving seconds later sees the
        row before the task has run.

    That is exactly the "course with no retrievable material" this feature
    exists to avoid, so the signal has to be the chunks themselves.

    Scoped by COURSE CODE rather than by offering, because that is the keyspace
    `rag_service.chunk_id` actually hashes: two offerings of the same course
    share their chunk rows, so an offering-equality test simultaneously missed
    real reuse and claimed reuse the ids do not provide.

    Checks the first AND last chunk id. Embedding runs in batches of 50 and a
    batch that fails is dropped before the single upsert, so a present first
    chunk alone cannot tell a complete index from a truncated one.

    A lookup failure degrades to False, i.e. "index it". That is the safe
    direction: chunk ids are content-addressed and the write is an upsert, so
    a needless re-index costs embeddings, while a wrong "already indexed"
    costs the course its material.
    """
    if not course_code or not chunks:
        return False
    # Imported here, not at module scope: rag_service pulls in google.genai,
    # and this module is imported by the upload route at startup.
    from services.rag_service import chunk_id

    wanted = {chunk_id(course_code, chunks[0]), chunk_id(course_code, chunks[-1])}
    try:
        rows = table("course_chunks").select(
            "id",
            filters={"id": f"in.({','.join(sorted(wanted))})"},
            limit=len(wanted),
        )
    except Exception:
        logger.warning(
            "[RAG] chunk-existence lookup failed for %s — indexing anyway",
            course_code, exc_info=True,
        )
        return False
    if not isinstance(rows, list):
        return False
    found = {r.get("id") for r in rows if isinstance(r, dict)}
    return wanted <= found


def _pick_twin(rows: list, offering_id: str | None) -> dict | None:
    """Choose the most useful candidate from an unordered set of twins.

    Ranked, highest first:

      1. A row with a stored `agent_result`. Without one the caller re-runs the
         classifier, summary, concepts and syllabus agents for nothing — the
         single most expensive thing this module exists to prevent.
      2. Among those, a row from the offering being uploaded to, so a replay
         reproduces what this course's other students already see.

    Rows with no `extracted_text` are skipped outright: reusing one would skip
    OCR and leave the new document empty. The query filters them too, but the
    filter alone is not enough — it is what makes the row we *do* get usable,
    while this is what makes the CHOICE among several deterministic.
    """
    best: dict | None = None
    best_rank: tuple[int, int] = (-1, -1)
    for row in rows:
        if not isinstance(row, dict) or not row.get("extracted_text"):
            continue
        rank = (
            1 if row.get("agent_result") else 0,
            1 if offering_id and row.get("offering_id") == offering_id else 0,
        )
        # Strictly greater, so ties keep the first row of the query's own
        # deterministic order rather than the last.
        if rank > best_rank:
            best, best_rank = row, rank
    return best


def find_duplicate(file_hash: str, offering_id: str | None = None) -> dict | None:
    """Return an already-processed document with this fingerprint, or None.

    The lookup is deliberately **global** rather than course-scoped: the
    extracted text, category, summary and concepts are pure functions of the
    file's bytes (the classifier/summary/concepts agents carry static system
    prompts and no user context), so a twin from any course is a valid source.
    `offering_id` is a preference, not a filter — see `_pick_twin`.

    Returns the twin with its encrypted columns decrypted, ready to copy onto
    the new row. Never raises: a missing `file_sha256` column — deployments ship
    code before migrations run — degrades to "no duplicate" so uploads keep
    working on the un-migrated schema.
    """
    if not file_hash:
        return None
    try:
        rows = table("documents").select(
            _TWIN_COLUMNS,
            filters={
                "file_sha256": f"eq.{file_hash}",
                "deleted_at": "is.null",
                # Pushed into the query as well as into `_pick_twin`, so the
                # candidate window is never spent on rows that could not be
                # used anyway.
                "extracted_text": "not.is.null",
            },
            # `nullslast` floats the rows that can actually be replayed to the
            # front of the window; `created_at` makes the rest reproducible
            # instead of planner-dependent.
            order="agent_result.asc.nullslast,created_at.asc",
            limit=_TWIN_CANDIDATES,
        )
    except Exception as e:
        # WARNING plus a countable event, not debug: None is also the NORMAL
        # answer here, and debug sits below production log level, so a dropped
        # column, a PostgREST 400 from a filter typo, or sustained timeouts
        # would leave dedup permanently dead while every upload looked healthy.
        # Same treatment as rag_service.retrieve_chunks' identical ambiguity
        # (#482).
        logger.warning("file_sha256 duplicate lookup failed: %s", e, exc_info=True)
        log_event(
            "document.dedup_lookup_failed",
            category="error",
            payload={"error_type": type(e).__name__},
        )
        return None
    if not isinstance(rows, list):
        return None
    twin = _pick_twin(rows, offering_id)
    if twin is None:
        return None

    extracted = decrypt_if_present(twin.get("extracted_text"))
    # A twin whose extraction never landed carries nothing worth reusing.
    # Treating it as a duplicate would skip OCR and leave the new document
    # empty, which is worse than simply re-processing the file.
    if not extracted:
        return None

    return {
        "id": twin.get("id"),
        "offering_id": twin.get("offering_id"),
        "extracted_text": extracted,
        # None for rows written before the column existed, or whose stored
        # shape no longer validates. Callers treat that as "run the agents".
        "result": decode_result(decrypt_if_present(twin.get("agent_result"))),
    }
