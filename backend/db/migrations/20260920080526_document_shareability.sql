-- Store the real document category on chunks, and record what is shareable (#630).
--
-- `rag_service.index_document_chunks` hardcoded `"category": "document"`. The
-- classifier's category DID reach the indexer — it picks the chunking strategy —
-- and was then dropped at the persist call, so every row in `course_chunks`
-- claimed to be the same kind of thing and nothing downstream could tell a
-- syllabus chunk from a problem set.
--
-- The larger problem is what that hid: nothing asked whether a document was the
-- COURSE's to share. `share_class_context` (0037, enforced on RAG by #629)
-- answers "does this student consent to sharing?", which is a different question
-- from "is this the student's own graded homework?". Completed work, graded work
-- and private notes all entered the shared pool on the strength of that one
-- consent flag — an academic-integrity problem as much as a privacy one.

-- ── 1. the stored sharing decision ─────────────────────────────────────────
--
-- NULLable on purpose, and NULL means "never classified" rather than any bucket.
-- Rows written before this migration have no stored answer, and
-- `chunk_visibility.decide_visibility` treats an absent value as private — so a
-- re-index of an old document withdraws it from the class pool until
-- `scripts/backfill_document_shareability.py` has filled this in. That is the
-- right default (a wrongly-private chunk is repaired by a re-index; a wrongly
-- shared one has already been served) but it is a real operational step, not a
-- no-op: run the backfill before re-indexing anything.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS shareability TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_shareability_check'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_shareability_check
            CHECK (shareability IS NULL OR shareability IN
                   ('course_material', 'personal_notes', 'completed_work'));
    END IF;
END $$;

-- ── 2. backfill the chunk category from the parent document ────────────────
--
-- Deterministic, no model call: `documents.category` is the classifier's answer
-- for the same document (user-editable via PATCH /doc/{id}, so not PURE
-- classifier output — still the best record of what the document is).
--
-- Lossy in one known way, recorded rather than papered over: chunk ids are
-- content-addressed, so a passage two students uploaded is ONE row whose
-- `doc_id` names whoever uploaded last (#629). Such a row is categorised from
-- that uploader's document. Both students' documents classified the same passage,
-- so the categories rarely disagree, and where they do the alternative — leaving
-- every existing row labelled "document" — is worse.
--
-- Catalog rows are untouched: they are the BU course-catalog partition that
-- `learn._get_catalog_chunk` and the quiz's catalog de-dup key on.
UPDATE course_chunks c
   SET category = d.category
  FROM documents d
 WHERE c.doc_id = d.id
   AND c.category = 'document'
   AND d.category IS NOT NULL;
