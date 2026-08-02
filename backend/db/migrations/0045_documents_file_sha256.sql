-- 0045: file-level duplicate detection — add file_sha256 to documents
--
-- The RAG corpus is shared per course, so the same lecture deck is uploaded by
-- many students under many different filenames. `rag_service.chunk_id` already
-- collapses identical passages to one row, but only at the END of the
-- pipeline: OCR and the embedding batch have both been paid for by then, and
-- the duplicate chunks are simply upserted onto rows that already exist.
--
-- Storing a SHA-256 of the raw uploaded bytes lets the upload path recognise a
-- re-upload at the door and skip that work. The fingerprint covers the file
-- contents ONLY — never the filename — so `lec3.pdf` and
-- `Lecture 3 Slides.pdf` are recognised as the same upload.
--
-- Nullable by design: every row written before this migration has no
-- fingerprint, and `services/document_dedup.py` treats a missing value as
-- "no duplicate" rather than an error. Those rows simply do not participate in
-- dedup until the file is uploaded again.
--
-- NOT unique: the same file legitimately appears once per uploader (each
-- student owns their own documents row) and once per course (chunk ids are
-- course-scoped, so the same textbook indexed for two courses needs two rows).
-- A UNIQUE constraint here would reject those valid uploads.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS file_sha256 TEXT;

-- Supports the equality lookup in document_dedup.find_duplicate, which runs on
-- every upload before any work is done. Partial: rows without a fingerprint
-- are never matched, so they do not belong in the index.
CREATE INDEX IF NOT EXISTS idx_documents_file_sha256
    ON documents (file_sha256)
    WHERE file_sha256 IS NOT NULL;
