"""Content-addressed `course_chunks` ids, the embedding dimension and the
`course_chunks.visibility` values (PKG-13 fix round: moved verbatim out of
services/rag_service.py, which re-exports the id and the dimension). No SDK
import: rag_service pulls google-genai (~1.4 s) through agents._providers, and
the rich seed — a fresh process before every Playwright test — needs only
these to write chunk rows.

In db/ (spec §13 A149), not services/: the row-id scheme and the column's
domain are facts of the `course_chunks` table, and the rich seed
(db/seed_local_rich.py) writes chunk rows — a db module must not import
services (backend/.importlinter). services/chunk_visibility.py re-exports
SHARED / PRIVATE from here.
"""

from __future__ import annotations

import hashlib

#: `course_chunks.visibility`. Mirrors the CHECK constraint in the migration.
SHARED = "shared"
PRIVATE = "private"

#: gemini-embedding-001's output_dimensionality in every embed call.
EMBED_OUTPUT_DIM = 768


def chunk_id(
    course_code: str,
    chunk_text: str,
    *,
    visibility: str = SHARED,
    uploader_id: str | None = None,
) -> str:
    """Content-addressed chunk id, scoped per course and per row kind.

    Identical text in the same course maps to one row no matter which
    document or uploader supplied it, so N students uploading the same
    slides dedup to one embedding instead of N. doc_id/uploader_id/
    chunk_index on the row are last-writer-wins metadata; retrieval only
    reads course_id + chunk_text.

    The literal "document" segment keeps this keyspace DISJOINT from
    catalog rows: scripts/ingest_catalog.py ids category=catalog rows as
    sha256(course::text) in the SAME course_chunks table (on_conflict=id),
    so an un-namespaced hash would let a document chunk whose text
    byte-matches a catalog chunk silently overwrite the catalog row and
    flip its category — dropping it from every category=eq.catalog reader.

    A PRIVATE chunk gets a third namespace segment plus its uploader (#629),
    for the same structural reason: the shared upsert merges on id under
    `resolution=merge-duplicates`, so an opted-out upload that hashed to the
    shared id would merge INTO the classmates' row — leaving the opted-out
    student's text in the shared pool under a row they can no longer withdraw.
    Per-uploader, not merely per-visibility, so two opted-out students who
    upload the same handout do not end up sharing one row with each other.
    """
    if visibility == PRIVATE:
        if not uploader_id:
            raise ValueError(
                "a private chunk id needs its uploader_id: without one the "
                "private keyspace collapses back onto one key per course and "
                "opted-out uploads re-merge with each other (#629)"
            )
        return hashlib.sha256(
            f"{course_code}::document::private::{uploader_id}::{chunk_text}".encode()
        ).hexdigest()
    return hashlib.sha256(f"{course_code}::document::{chunk_text}".encode()).hexdigest()
