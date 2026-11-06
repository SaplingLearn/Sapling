-- #758: the indexing queue's terminal state is stored, not inferred.
--
-- Three defects in the #482 state machine (20260921063714 + 20260921073000):
--
-- 1. "Terminal" was `index_attempts >= max_attempts`, and max_attempts is the
--    INDEX_MAX_ATTEMPTS env var. Raising it silently re-queued every row the
--    sweeper had given up on; lowering it stranded `failed` rows that nothing
--    would ever retry or report. The admin list could only DERIVE "exhausted".
--    Now: an explicit 'exhausted' status, written by the application when an
--    attempt spends the last of the budget (or fails in a way no retry can
--    fix), and by the reaper below.
--
-- 2. A crash on the LAST attempt left the row 'indexing' with attempts = max.
--    The claim requires attempts < max, so neither it nor the inline claim
--    could ever retake it: 'indexing' forever, invisible as a failure, until an
--    admin happened to force it. The claim now reaps such a row to 'exhausted'
--    (error 'lease_expired') once its lease has run out — and, for the same
--    reason, any 'failed'/'partial' row already at the budget.
--
-- 3. 'skipped' was both the column DEFAULT (the migration's "do not touch"
--    marker for historical rows) and a real outcome. Any insert path that
--    omitted index_status landed silently in a terminal state nothing would
--    ever index. New rows now default to 'pending' — the queue the sweeper
--    drains — so an omission is indexed, or visibly fails, instead of
--    vanishing. Existing rows keep their value: the historical 'skipped' rows
--    are still scripts/backfill_document_index_status.py's to label.
--
-- The claim also clears index_error, as the application's own claim
-- (_claim_one) always has, so an 'indexing' row never carries the previous
-- attempt's error class.
--
-- Deploy order: this migration BEFORE the code (as `make promote` does). Code
-- ahead of it writes 'exhausted' into a CHECK that does not admit it; that
-- write fails, is logged, and leaves the row 'indexing' until its lease
-- expires and the old claim re-drives it — the pre-#758 behaviour, not a loss.

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_index_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_index_status_check
    CHECK (index_status IN
        ('pending', 'indexing', 'indexed', 'partial', 'failed', 'skipped', 'exhausted'));

ALTER TABLE documents ALTER COLUMN index_status SET DEFAULT 'pending';

-- The queue index skipped finished rows; a given-up row is finished too.
DROP INDEX IF EXISTS idx_documents_index_queue;
CREATE INDEX IF NOT EXISTS idx_documents_index_queue
    ON documents (index_status, index_attempts)
    WHERE index_status NOT IN ('indexed', 'skipped', 'exhausted');

-- Same signature as 20260921073000 (PostgREST resolves by argument names; a
-- changed signature would leave the old body as a live overload). Two
-- statements: the reap, then the claim. A VOLATILE SQL function runs each
-- statement under a fresh snapshot, so the claim sees the reap's writes.
CREATE OR REPLACE FUNCTION claim_documents_for_indexing(
    max_attempts  INT,
    lease_seconds INT,
    batch_size    INT
)
RETURNS TABLE (id TEXT)
LANGUAGE sql
VOLATILE
AS $$
    -- Reap: a row whose budget is spent and that nothing is running is
    -- terminal. index_leased_at is left as it was, so an attempt that merely
    -- outlived its lease and then finishes still holds the row (its write is
    -- conditional on that lease) and records its real outcome over this one.
    UPDATE documents r
       SET index_status = 'exhausted',
           index_error  = CASE WHEN r.index_status = 'indexing'
                               THEN 'lease_expired'
                               ELSE r.index_error END
     WHERE r.deleted_at IS NULL
       AND r.index_attempts >= max_attempts
       AND (
               r.index_status IN ('partial', 'failed')
            OR (r.index_status = 'indexing'
                AND r.index_leased_at < now() - make_interval(secs => lease_seconds))
           );

    UPDATE documents d
       SET index_status    = 'indexing',
           index_leased_at = now(),
           index_attempts  = d.index_attempts + 1,
           index_error     = NULL
     WHERE d.id IN (
         SELECT c.id
           FROM documents c
          WHERE c.deleted_at IS NULL
            AND c.index_attempts < max_attempts
            AND (
                    -- A fresh upload belongs to its own inline attempt for
                    -- its first two minutes (unchanged).
                    (c.index_status = 'pending'
                     AND c.created_at < now() - interval '2 minutes')
                    -- A retry waits lease_seconds after the last attempt began.
                 OR (c.index_status IN ('partial', 'failed')
                     AND (c.index_leased_at IS NULL
                          OR c.index_leased_at < now() - make_interval(secs => lease_seconds)))
                    -- A crash-stranded attempt, once its lease has run out.
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

-- CREATE OR REPLACE keeps the function's privileges; restated so this file is
-- correct on its own (same guarded idiom as the two before it).
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
