-- #758: a deleted document leaves the RAG corpus.
--
-- `DELETE /api/documents/doc/{id}` only stamped `documents.deleted_at`, and
-- `match_course_chunks` never looks at `documents` at all — so a deleted upload,
-- private ones included, kept grounding the uploader's and (for shared rows)
-- every classmate's tutor and quizzes. Nothing could even say which chunks a
-- document had produced: chunk ids are content-addressed per course, so a row
-- deduped across uploads carries only its LAST writer in `course_chunks.doc_id`.
--
-- Two objects close it:
--   1. `course_chunk_sources`, the chunk <-> document ledger. It is what the
--      delete path (services/chunk_visibility.py::withdraw_document_chunks)
--      reads to find a document's chunks, and what tells it whether another
--      live document still produces the same text.
--   2. `match_course_chunks`, replaced with the same signature, now refuses a
--      chunk whose every recorded source document is deleted. Defence in depth:
--      the delete path withdraws the rows, and this keeps a withdrawal that
--      failed half-way (or a document deleted mid-index) out of retrieval.
--
-- Safe in either deploy order. Code ahead of this migration: writing a source
-- row 404s and is swallowed (best-effort, logged), the delete path finds its
-- candidates through `course_chunks.doc_id`, and retrieval is today's.
-- Migration ahead of code: nothing writes sources yet, the seed below covers
-- every existing row, and retrieval only gets stricter.

-- ── 1. the ledger ──────────────────────────────────────────────────────────
--
-- No foreign key to documents, ON PURPOSE. Documents are soft-deleted, so the
-- rows must outlive the deletion for (2) to see it; and should a document ever
-- be hard-deleted, an FK cascade would erase the only evidence that the chunk
-- came from it, turning it into an unsourced row (which retrieval serves, like
-- a catalog row). A source naming a document that no longer exists counts as
-- dead, which is the safe reading. Only services/document_indexing.py writes
-- here, and only for a real `documents` row.
--
-- The FK to course_chunks DOES cascade: when a chunk is withdrawn its sources
-- go with it.
CREATE TABLE IF NOT EXISTS course_chunk_sources (
    chunk_id   TEXT NOT NULL REFERENCES course_chunks(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, doc_id)
);

-- The delete path reads one document's chunks; the PK covers (chunk_id, …).
CREATE INDEX IF NOT EXISTS idx_course_chunk_sources_doc
    ON course_chunk_sources (doc_id);

-- Seed from what the table already knows: the last writer of each document
-- row. Soft-deleted documents included — that is what takes chunks of
-- documents deleted BEFORE this migration out of retrieval the moment it runs.
-- Joined to documents so that a `doc_id` naming no document (a seeded fixture,
-- e.g. scripts/seed_quiz_fixture.py) stays unsourced rather than being read as
-- "every source is gone". Under-records co-uploaders of a deduped row, exactly
-- like the contributor seed in 20260920072705; the effect is a chunk withheld
-- when its last writer deletes while another live document still has the text
-- — the safe direction. scripts/backfill_course_chunk_sources.py re-derives the
-- full set from each live document's own text.
INSERT INTO course_chunk_sources (chunk_id, doc_id)
SELECT c.id, c.doc_id
  FROM course_chunks c
  JOIN documents d ON d.id = c.doc_id
 WHERE c.category IS DISTINCT FROM 'catalog'
ON CONFLICT DO NOTHING;

-- Backend-only, like every RAG table: the API is the one client.
ALTER TABLE course_chunk_sources ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON course_chunk_sources FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON course_chunk_sources TO service_role;
    END IF;
END $$;

-- ── 2. the retrieval RPC ───────────────────────────────────────────────────
--
-- CREATE OR REPLACE with the IDENTICAL signature, defaults and result columns
-- as 20260920072705: a changed signature would leave the old function as a
-- live overload (the shape #629 had to DROP to close), and PostgREST resolves
-- by argument names, so every caller keeps resolving to this one.
CREATE OR REPLACE FUNCTION match_course_chunks(
    query_embedding  VECTOR(768),
    match_count      INTEGER DEFAULT 5,
    filter_course_id TEXT DEFAULT NULL,
    filter_user_id   TEXT DEFAULT NULL
)
RETURNS TABLE (
    id         TEXT,
    course_id  TEXT,
    chunk_text TEXT,
    category   TEXT,
    similarity FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.course_id,
        c.chunk_text,
        c.category,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM course_chunks c
    WHERE c.embedding IS NOT NULL
      AND (filter_course_id IS NULL OR c.course_id = filter_course_id)
      -- Unchanged from 20260920072705: NULL reader = shared rows only.
      AND (
        c.visibility = 'shared'
        OR (
          filter_user_id IS NOT NULL
          AND (
            c.uploader_id = filter_user_id
            OR EXISTS (
              SELECT 1 FROM course_chunk_contributors k
               WHERE k.chunk_id = c.id AND k.user_id = filter_user_id
            )
          )
        )
      )
      -- #758: a chunk with recorded sources is served only while at least one
      -- of them is a live document. A row with NO source (catalog text, a
      -- fixture) is unaffected.
      AND (
        NOT EXISTS (
          SELECT 1 FROM course_chunk_sources s WHERE s.chunk_id = c.id
        )
        OR EXISTS (
          SELECT 1
            FROM course_chunk_sources s
            JOIN documents d ON d.id = s.doc_id
           WHERE s.chunk_id = c.id
             AND d.deleted_at IS NULL
        )
      )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
