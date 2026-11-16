"""Reading a saved `documents` row back out for a client (#116 review).

One decrypt for the two places that hand a stored document back verbatim:
the upload routes' idempotent replay (routes/documents.py::
_existing_doc_by_request_id) and the queued upload's `/upload/sync` answer
(services/document_jobs.py). Both return summary and concept notes in
plaintext, never `extracted_text`, and never a soft-deleted row.
"""
from __future__ import annotations

from db.connection import table
from db.scope import runs_as_service
from services.encryption import decrypt_if_present, decrypt_json


def decrypt_document_row(row: dict) -> dict:
    """A copy of a documents row with `summary` and `concept_notes` decrypted
    (a concept-notes blob that will not decrypt reads as no notes) and
    `extracted_text` dropped."""
    out = dict(row)
    out.pop("extracted_text", None)
    out["summary"] = decrypt_if_present(out.get("summary"))
    notes = out.get("concept_notes")
    if isinstance(notes, str):
        try:
            out["concept_notes"] = decrypt_json(notes)
        except Exception:
            out["concept_notes"] = []
    return out


@runs_as_service  # `*` includes the index/text columns a student's grant does not cover
def saved_document(doc_id: str, user_id: str) -> dict | None:
    """The uploader's live (not soft-deleted) documents row, every column but
    `extracted_text`, decrypted: what the inline `/upload/sync` returns from
    its insert. None when there is no such row."""
    rows = table("documents").select(
        "*",
        filters={"id": f"eq.{doc_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return decrypt_document_row(rows[0])
