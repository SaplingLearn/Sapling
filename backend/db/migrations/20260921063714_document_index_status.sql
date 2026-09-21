-- #482: documents.index_status is the indexing work queue.
--
-- Durability deliberately does NOT come from DBOS. ADR 0011 keeps DBOS_ENABLED
-- off in every deployed environment pending a real production incident, so a
-- DBOS workflow would buy nothing in production. A status column drained by a
-- sweeper (services/index_sweeper.py) works with DBOS off, which is where every
-- environment actually is.
--
-- Deploy order: this migration BEFORE the code. The code writes these columns
-- at insert; routes/documents.py::_persist_document tolerates their absence
-- (it drops each column PostgREST names as missing), but a sweeper against a
-- schema without claim_documents_for_indexing() would fail every sweep.

ALTER TABLE documents
    -- 'skipped' is the inert default ON PURPOSE: between this migration landing
    -- and scripts/backfill_document_index_status.py telling the truth about
    -- each historical row, the sweeper must not claim any of them. New uploads
    -- set 'pending' explicitly at insert.
    ADD COLUMN IF NOT EXISTS index_status      TEXT NOT NULL DEFAULT 'skipped',
    ADD COLUMN IF NOT EXISTS index_attempts    INT  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS index_leased_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS index_chunk_count INT,
    -- The error CLASS only (e.g. 'TypeError', 'no_extracted_text'). Never an
    -- exception message: those can quote document text, and this column is
    -- plaintext and shown on an admin list.
    ADD COLUMN IF NOT EXISTS index_error       TEXT,
    -- #630 stored `shareability` but not the confidence it was judged at, and
    -- chunk_visibility.decide_visibility() reads a missing confidence as
    -- PRIVATE. Without this column a re-drive would silently privatise a
    -- correctly shared document -- the same silent corpus loss as #628,
    -- arriving through the very recovery path this migration exists for.
    ADD COLUMN IF NOT EXISTS shareability_confidence REAL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_index_status_check'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_index_status_check
            CHECK (index_status IN
                ('pending', 'indexing', 'indexed', 'partial', 'failed', 'skipped'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'documents_shareability_confidence_check'
    ) THEN
        ALTER TABLE documents ADD CONSTRAINT documents_shareability_confidence_check
            CHECK (shareability_confidence IS NULL
                   OR (shareability_confidence >= 0.0
                       AND shareability_confidence <= 1.0));
    END IF;
END $$;

-- The sweeper only ever reads rows that are not finished.
CREATE INDEX IF NOT EXISTS idx_documents_index_queue
    ON documents (index_status, index_attempts)
    WHERE index_status NOT IN ('indexed', 'skipped');

-- Atomic batch claim for the sweeper.
--
-- UPDATE ... RETURNING over a SKIP LOCKED subselect, so two instances can never
-- drive the same document. It increments index_attempts AT CLAIM TIME, so a
-- document that crashes the worker mid-index still spends an attempt and is
-- bounded to max_attempts rather than retried forever. A row stranded in
-- 'indexing' by a hard crash becomes reclaimable once its lease expires.
--
-- `id` is TEXT because documents.id is TEXT (0025), not uuid.
CREATE OR REPLACE FUNCTION claim_documents_for_indexing(
    max_attempts  INT,
    lease_seconds INT,
    batch_size    INT
)
RETURNS TABLE (id TEXT)
LANGUAGE sql
VOLATILE
AS $$
    UPDATE documents d
       SET index_status    = 'indexing',
           index_leased_at = now(),
           index_attempts  = d.index_attempts + 1
     WHERE d.id IN (
         SELECT c.id
           FROM documents c
          WHERE c.deleted_at IS NULL
            AND c.index_attempts < max_attempts
            AND (
                    -- A fresh 'pending' row belongs to the upload's own inline
                    -- attempt for its first two minutes. Correctness does not
                    -- depend on this grace -- the inline path's conditional
                    -- claim does -- it only avoids contending with it.
                    (c.index_status = 'pending'
                     AND c.created_at < now() - interval '2 minutes')
                 OR c.index_status IN ('partial', 'failed')
                 OR (c.index_status = 'indexing'
                     AND c.index_leased_at
                         < now() - make_interval(secs => lease_seconds))
                )
          ORDER BY c.index_leased_at NULLS FIRST, c.created_at
          LIMIT batch_size
          FOR UPDATE SKIP LOCKED
     )
 RETURNING d.id;
$$;

-- Backend-only. Postgres grants EXECUTE on a new function to PUBLIC, Supabase's
-- default privileges add anon and authenticated, and PostgREST exposes every
-- public-schema function at /rest/v1/rpc/<name>. The frontend ships the anon
-- key -- so without this, anyone holding it could drive the indexing queue.
-- Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration. Same idiom as 20260921041555_canopy_active_users.sql.
REVOKE ALL ON FUNCTION claim_documents_for_indexing(INT, INT, INT) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION claim_documents_for_indexing(INT, INT, INT) FROM %I',
                r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION claim_documents_for_indexing(INT, INT, INT)
            TO service_role;
    END IF;
END $$;
