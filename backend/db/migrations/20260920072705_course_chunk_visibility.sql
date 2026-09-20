-- Enforce the Class Intel opt-out on RAG rows (#629).
--
-- `user_settings.share_class_context` (0037) is the persisted opt-out. It was
-- enforced at exactly ONE write chokepoint — the class-aggregate rollup in
-- services/course_context_service.py — and nowhere in RAG, so an opted-out
-- student's upload still landed in the shared `course_chunks` pool (0039) and
-- still surfaced in a classmate's tutor and quizzes. The default is opted IN,
-- and a missing settings row counts as opted in too, so this was the quiet
-- case rather than the loud one.
--
-- Three objects close it: a `visibility` column the retrieval RPC can filter
-- on, a contributor ledger that makes "withdraw my chunks" answerable at all,
-- and a replacement RPC that takes the reader.
--
-- APPLY THIS BEFORE DEPLOYING THE CODE. The application always sends
-- `filter_user_id` now, and PostgREST resolves functions by argument name, so
-- code running ahead of this migration gets a 404 on every match_course_chunks
-- call — swallowed into `Retrieval(failed=True)`, i.e. the tutor and quiz lose
-- ALL grounding with no user-visible error. `visibility` in the index payload
-- would 400 for the same reason. The reverse order is safe (every new parameter
-- has a default, so the old 3-key body still resolves), which is why
-- `make promote` migrates before it merges. Note that migrate-staging.yml is
-- currently a silent skip for want of a secret (#619) — check its log rather
-- than assuming staging is migrated.

-- ── 1. visibility ──────────────────────────────────────────────────────────
--
-- Existing rows become 'shared', which is exactly today's behaviour: every row
-- in the table right now is readable by every enrolled student. NOT NULL with
-- a constant default does not rewrite the table on PG11+, so this is cheap on
-- production's ~8.7k catalog rows.
ALTER TABLE course_chunks
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'shared';

-- ADD CONSTRAINT has no IF NOT EXISTS form, so guard on the catalog: this file
-- must be a no-op on an environment that already ran it.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'course_chunks_visibility_check'
    ) THEN
        ALTER TABLE course_chunks
            ADD CONSTRAINT course_chunks_visibility_check
            CHECK (visibility IN ('shared', 'private'));
    END IF;
END $$;

-- Retrieval filters course THEN visibility, in that order.
CREATE INDEX IF NOT EXISTS idx_course_chunks_course_visibility
    ON course_chunks (course_id, visibility);

-- ── 2. the contributor ledger ──────────────────────────────────────────────
--
-- The load-bearing piece, and the answer to the open question on #629. Chunk
-- ids are content-addressed per course (rag_service.chunk_id), so identical
-- text from two uploaders is ONE row and `uploader_id` names only whoever
-- uploaded LAST. Without a ledger, "make my chunks private" is unanswerable:
-- nothing records that a student fed a row they are not the last writer of, so
-- an opt-out would either miss their own content or withdraw a classmate's.
--
-- A shared row stays shared while at least one contributor is still opted in.
--
-- Private rows deliberately get NO entry here: an opted-out upload is hashed
-- into a per-uploader id namespace, so exactly one user can ever own it and
-- `uploader_id` is exact. That omission is also what keeps the resync safe —
-- it walks this table, so it only ever reconsiders shared-namespace ids, and
-- can never flip a private row 'shared' under an id that could not merge with
-- the shared row for the same text.
CREATE TABLE IF NOT EXISTS course_chunk_contributors (
    chunk_id   TEXT NOT NULL REFERENCES course_chunks(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, user_id)
);

-- The resync reads every chunk one user fed; #635 will read attribution the
-- other way. The PK covers (chunk_id, …) already.
CREATE INDEX IF NOT EXISTS idx_course_chunk_contributors_user
    ON course_chunk_contributors (user_id);

-- Seed the ledger from what the table already knows. `uploader_id` is the
-- last writer, not the full set, so this under-records co-uploaders of a
-- deduped row — that is the best available attribution for rows written before
-- the ledger existed, and it is strictly better than none: without it, every
-- student who has already uploaded would find their opt-out unable to withdraw
-- anything. Catalog rows are public BU course text with no uploader.
INSERT INTO course_chunk_contributors (chunk_id, user_id)
SELECT c.id, c.uploader_id
  FROM course_chunks c
  JOIN users u ON u.id = c.uploader_id
 WHERE c.category IS DISTINCT FROM 'catalog'
   AND c.uploader_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- ── 3. the retrieval RPC ───────────────────────────────────────────────────
--
-- DROP then CREATE, not CREATE OR REPLACE: adding a parameter changes the
-- signature, and Postgres would keep the previous function as a live OVERLOAD.
-- That stale copy has no visibility filter at all, so anything that resolved to
-- it — a rollback, a hand-written call, PostgREST picking it from a 3-key body —
-- would read straight past the opt-out. An unfiltered overload is the bug this
-- migration exists to remove, so it must not survive the fix.
--
-- Dropping EVERY overload by name rather than `DROP FUNCTION IF EXISTS
-- match_course_chunks(VECTOR(768), INTEGER, TEXT)`: that names one exact
-- signature, and `course_chunks` plus this RPC existed as hand-written
-- dashboard DDL on staging and production long before 0039 codified them (see
-- the header of 0039). If either environment's live function differs by even a
-- parameter type, the targeted DROP is a silent no-op and the unfiltered copy
-- survives the migration that was supposed to remove it. This loop cannot miss.
-- db/migrate.py runs every pending file inside ONE transaction and commits at
-- the end, so there is no window in which retrieval has no function to call.
DO $$
DECLARE
    fn record;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure AS sig
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE p.proname = 'match_course_chunks'
           AND n.nspname = 'public'
    LOOP
        EXECUTE 'DROP FUNCTION ' || fn.sig;
    END LOOP;
END $$;

CREATE FUNCTION match_course_chunks(
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
      -- `filter_user_id IS NULL` means "shared only". That is deliberately
      -- fail-closed: a caller that has not been threaded through (an offline
      -- script, a future route) under-retrieves instead of publishing every
      -- student's private uploads to whoever asked.
      AND (
        c.visibility = 'shared'
        OR (
          filter_user_id IS NOT NULL
          AND (
            -- Exact for private rows: their id encodes this uploader.
            c.uploader_id = filter_user_id
            -- And for a shared row an opt-out has since flipped private, where
            -- `uploader_id` may name a different contributor entirely.
            OR EXISTS (
              SELECT 1 FROM course_chunk_contributors k
               WHERE k.chunk_id = c.id AND k.user_id = filter_user_id
            )
          )
        )
      )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
