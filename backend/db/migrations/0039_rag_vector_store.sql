-- 0039: codify the RAG vector store that only ever existed as dashboard DDL (#481).
--
-- `course_chunks`, the `match_course_chunks` RPC and `CREATE EXTENSION vector`
-- appear in ZERO .sql files in this repo, yet all three are live in staging and
-- production. A database replayed purely from `python -m db.migrate` — local
-- Supabase, the E2E stack, any fresh environment — therefore has RAG silently
-- dead end to end:
--
--   * retrieve_chunks() swallows the RPC failure into []  (rag_service.py)
--   * _get_catalog_chunk() degrades to ""
--   * indexing failures vanish into a fire-and-forget log line
--
-- so the tutor answers ungrounded with no error, no metric and no user-visible
-- signal, and nothing in the suites or oracles asserts the table exists.
--
-- Shape verified against LIVE production and staging on 2026-07-31 by reading a
-- real row and calling the RPC (columns, the 768-dim embedding, and the RPC's
-- exact parameter and return names), rather than from the design doc alone —
-- the doc describes intent, the database is what the code actually talks to.
--
-- IF NOT EXISTS throughout, mirroring 0032's reconcile pattern: this must be a
-- no-op on staging and production, where every object below already exists.

CREATE EXTENSION IF NOT EXISTS vector;

-- Chunk ids are content-addressed (sha256 hex) so a re-upload of the same text
-- merges instead of duplicating — see rag_service.chunk_id.
CREATE TABLE IF NOT EXISTS course_chunks (
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL,
    doc_id      TEXT,
    uploader_id TEXT,
    chunk_index INTEGER,
    chunk_text  TEXT,
    chunk_hash  TEXT,
    embedding   VECTOR(768),
    category    TEXT,
    semester    TEXT,
    section_id  TEXT,
    school      TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Retrieval always filters by course before ranking.
CREATE INDEX IF NOT EXISTS idx_course_chunks_course_id ON course_chunks (course_id);
CREATE INDEX IF NOT EXISTS idx_course_chunks_doc_id    ON course_chunks (doc_id);

-- ANN index. ivfflat needs training data to be worth building, and `lists`
-- wants tuning against real row counts; cosine matches the normalised
-- gemini-embedding-001 output the code stores.
CREATE INDEX IF NOT EXISTS idx_course_chunks_embedding
    ON course_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Retrieval RPC. Parameter names are part of the contract — rag_service.py
-- calls this by keyword (query_embedding / match_count / filter_course_id) and
-- reads back id, course_id, chunk_text, category, similarity.
--
-- CREATE OR REPLACE rather than IF NOT EXISTS: functions have no IF NOT EXISTS
-- form, and replacing with the identical body is the no-op we want on the
-- environments that already have it.
CREATE OR REPLACE FUNCTION match_course_chunks(
    query_embedding  VECTOR(768),
    match_count      INTEGER DEFAULT 5,
    filter_course_id TEXT DEFAULT NULL
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
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
