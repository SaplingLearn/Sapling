"""What deleting a document actually deletes.

`DELETE /api/documents/doc/{id}` used to stamp `documents.deleted_at` and stop.
Nothing touched `course_chunks`, and `match_course_chunks` never joins
`documents`, so a deleted document kept answering its owner's tutor — and,
when its chunks were in the shared pool, every classmate's tutor and quiz —
indefinitely. The FAQ promised "Delete a document and its data goes with it".

`purge_document` makes that true:

* **Private chunks** (the uploader's own id namespace) are deleted outright —
  exactly one user can own a private id (`rag_service.chunk_id`).
* **Shared chunks** are jointly owned (identical text from two uploaders is ONE
  row). The deleter's row in `course_chunk_contributors` is removed; a row left
  with no contributors is deleted, and a row another student still contributes
  stays — it is their content too. Same rule the opt-out resync uses
  (`chunk_visibility`): a shared row lives while one contributor remains.
* **The document's text** — `extracted_text`, `summary`, `concept_notes`,
  `flashcards` — is cleared. The row itself stays as a tombstone (file name,
  dates, `deleted_at`) because the soft-delete filter is what every reader keys
  on; it carries no content.

Finding the chunks. `course_chunks.doc_id` names only the LAST document to
write a row, so it misses a deduplicated row this document shared with an
earlier upload. The ids are content-addressed, so they are recomputed from the
document's own text, chunked exactly as `document_indexing._run` chunks it,
in both namespaces (shared, and this uploader's private one). The union of
the two lookups is the document's footprint.

Known limit: if the same user uploaded byte-identical text in two documents
of the same course, both map to the same chunk ids, and deleting one
withdraws the shared text the other also produced. Re-indexing the surviving
document (admin re-index) restores it. Not worth an extra decrypt-and-chunk of
every other document on every delete.

What is deliberately NOT removed: concepts the document added to the
knowledge graph (they are the student's, and the wiki says so), flashcards or
quizzes already generated from it, and aggregate class statistics.
"""

from __future__ import annotations

import logging

from db.connection import table
from services.chunker import chunk_for_category
from services.document_indexing import _course_code
from services.chunk_visibility import PRIVATE, SHARED
from services.encryption import decrypt
from services.rag_service import chunk_id

logger = logging.getLogger(__name__)

# Chunk ids are 64 hex chars; 100 per `in.()` keeps the PostgREST URL ~7 KB.
_ID_BATCH = 100

# The encrypted content columns of `documents`, cleared on delete.
CONTENT_COLUMNS = ("extracted_text", "summary", "concept_notes", "flashcards")


def _batches(ids: list[str]):
    for i in range(0, len(ids), _ID_BATCH):
        yield ids[i:i + _ID_BATCH]


def _in(ids: list[str]) -> str:
    return f"in.({','.join(ids)})"


def _recomputed_ids(row: dict) -> set[str]:
    """Every id this document's text hashes to, in both namespaces."""
    stored = row.get("extracted_text")
    if not stored:
        return set()
    try:
        # Strict decrypt, as indexing does: under the wrong key the fallback
        # would chunk ciphertext and compute ids that match nothing.
        text = decrypt(stored)
    except Exception:
        logger.warning("[delete] extracted_text for doc %s does not decrypt; "
                       "falling back to the doc_id lookup only", row.get("id"))
        return set()
    course_code = _course_code(row.get("offering_id"))
    if not course_code or not text.strip():
        return set()
    user_id = row["user_id"]
    ids: set[str] = set()
    for chunk in chunk_for_category(text, row.get("category") or "other"):
        ids.add(chunk_id(course_code, chunk, visibility=SHARED))
        ids.add(chunk_id(course_code, chunk, visibility=PRIVATE, uploader_id=user_id))
    return ids


def withdraw_document_chunks(row: dict) -> dict:
    """Remove this document's footprint from `course_chunks`.

    `row` is the `documents` row with at least id, user_id, offering_id,
    category and extracted_text. Returns counts for logging and tests.
    """
    doc_id, user_id = row["id"], row["user_id"]

    found: dict[str, dict] = {
        r["id"]: r
        for r in table("course_chunks").select(
            "id,visibility,uploader_id", filters={"doc_id": f"eq.{doc_id}"},
        ) or []
    }
    missing = sorted(_recomputed_ids(row) - found.keys())
    for batch in _batches(missing):
        for r in table("course_chunks").select(
            "id,visibility,uploader_id", filters={"id": _in(batch)},
        ) or []:
            found[r["id"]] = r

    private = sorted(i for i, r in found.items()
                     if r.get("visibility") == PRIVATE and r.get("uploader_id") == user_id)
    shared = sorted(i for i, r in found.items() if r.get("visibility") != PRIVATE)

    for batch in _batches(private):
        table("course_chunks").delete(
            filters={"id": _in(batch), "uploader_id": f"eq.{user_id}"},
        )

    orphaned: list[str] = []
    for batch in _batches(shared):
        table("course_chunk_contributors").delete(
            filters={"user_id": f"eq.{user_id}", "chunk_id": _in(batch)},
        )
        still_contributed = {
            r["chunk_id"] for r in table("course_chunk_contributors").select(
                "chunk_id", filters={"chunk_id": _in(batch)},
            ) or []
        }
        orphaned.extend(i for i in batch if i not in still_contributed)
    for batch in _batches(orphaned):
        table("course_chunks").delete(filters={"id": _in(batch)})

    return {
        "private_deleted": len(private),
        "shared_withdrawn": len(shared),
        "shared_deleted": len(orphaned),
    }


def purge_document(row: dict, deleted_at: str) -> dict:
    """Withdraw the document's chunks, then tombstone the row and clear its
    content. Chunks go first: if that step fails, the row is still live and
    the delete can simply be retried, rather than leaving content behind a
    row every reader already treats as gone."""
    counts = withdraw_document_chunks(row)
    table("documents").update(
        {"deleted_at": deleted_at, **{c: None for c in CONTENT_COLUMNS}},
        filters={"id": f"eq.{row['id']}", "user_id": f"eq.{row['user_id']}"},
    )
    logger.info("[delete] doc %s purged: %s", row["id"], counts)
    return counts
