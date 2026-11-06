-- #758 review: the reaper must also take an over-budget `pending` row.
--
-- 20261106043300 made `claim_documents_for_indexing` reap rows whose budget is
-- spent and that nothing is running, but only 'partial', 'failed' and
-- lease-expired 'indexing'. A 'pending' row can carry index_attempts > 0:
-- services/document_indexing.py::_restore refunds a sweeper claim that could
-- not embed back to 'pending' with attempts - 1. If an operator then lowers
-- INDEX_MAX_ATTEMPTS to or below that count, the row is neither claimable (the
-- claim requires attempts < max) nor reaped, so it stays 'pending' for good:
-- out of retrieval, absent from the "exhausted" view, retried by nothing.
-- Now it is reaped to 'exhausted' with error 'attempts_exhausted'.
--
-- A NEW migration rather than an edit to 20261106043300: that file can already
-- be recorded in a ledger (a local stack replayed from the umbrella branch, a
-- manual workflow_dispatch), and an edited file would never re-run there.

-- Identical to 20261106043300's definition except the reap's `pending` arm
-- and its error code. Same signature (PostgREST resolves by argument names; a
-- changed one would leave the old body as a live overload).
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
           index_error  = CASE r.index_status
                              WHEN 'indexing' THEN 'lease_expired'
                              WHEN 'pending'  THEN 'attempts_exhausted'
                              ELSE r.index_error END
     WHERE r.deleted_at IS NULL
       AND r.index_attempts >= max_attempts
       AND (
               r.index_status IN ('partial', 'failed')
               -- A `pending` row over the budget: the claim's
               -- `index_attempts < max_attempts` excludes it, so without this
               -- it waited forever, out of retrieval and never reported.
            OR r.index_status = 'pending'
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
