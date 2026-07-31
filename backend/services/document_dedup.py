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
import hashlib
import logging

from db.connection import table
from services.encryption import decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)

# Columns copied onto the new row when a duplicate is found. `offering_id` is
# not copied — it tells the caller which course the twin was indexed for, so it
# can decide whether the shared chunks already exist.
_TWIN_COLUMNS = "id,offering_id,category,extracted_text,summary,concept_notes"


def file_sha256(file_bytes: bytes) -> str:
    """Return the hex SHA-256 fingerprint of an uploaded file's bytes.

    Deliberately takes only the bytes: the filename must never influence the
    fingerprint, or two students' copies of the same deck would look distinct.
    """
    return hashlib.sha256(file_bytes).hexdigest()


def chunks_already_exist(twin: dict | None, offering_id: str) -> bool:
    """True when this upload's RAG chunks are already in the shared corpus.

    `rag_service.chunk_id` hashes the course code alongside the chunk text, so
    identical text in a DIFFERENT course produces different ids and genuinely
    needs its own embeddings. Reuse is therefore valid only within the course
    the twin was indexed for — skipping across courses would leave the second
    course with no retrievable material at all.
    """
    if not twin:
        return False
    return bool(offering_id) and twin.get("offering_id") == offering_id


def find_duplicate(file_hash: str) -> dict | None:
    """Return an already-processed document with this fingerprint, or None.

    The lookup is deliberately **global** rather than course-scoped: the
    extracted text, category, summary and concepts are pure functions of the
    file's bytes (the classifier/summary/concepts agents carry static system
    prompts and no user context), so a twin from any course is a valid source.
    Whether the *chunks* can be reused is a separate, course-scoped question the
    caller answers using the returned `offering_id`.

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
            },
            limit=1,
        )
    except Exception:
        logger.debug("file_sha256 duplicate lookup unavailable", exc_info=True)
        return None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None

    extracted = decrypt_if_present(first.get("extracted_text"))
    # A twin whose extraction never landed carries nothing worth reusing.
    # Treating it as a duplicate would skip OCR and leave the new document
    # empty, which is worse than simply re-processing the file.
    if not extracted:
        return None

    notes = first.get("concept_notes")
    if isinstance(notes, str):
        try:
            notes = decrypt_json(notes)
        except Exception:
            notes = []
    return {
        "id": first.get("id"),
        "offering_id": first.get("offering_id"),
        "category": first.get("category"),
        "extracted_text": extracted,
        "summary": decrypt_if_present(first.get("summary")),
        "concept_notes": notes if isinstance(notes, list) else [],
    }
