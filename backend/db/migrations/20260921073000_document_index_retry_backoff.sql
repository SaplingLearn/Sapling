-- #482 review round 2: a failed or partial document waits before its retry.
--
-- 20260921063714_document_index_status.sql made 'partial' and 'failed' rows
-- claimable immediately, and the application cleared index_leased_at when an
-- attempt finished. With the sweeper claiming one document per turn, the
-- claim's `ORDER BY index_leased_at NULLS FIRST` then handed a just-failed
-- document straight back in the same pass: three attempts inside a few
-- seconds, so a brief Gemini or PostgREST outage spent a document's whole
-- budget and left it out of retrieval until an operator forced it.
--
-- index_leased_at now outlives the attempt: on a finished row it records when
-- the LAST attempt started (services/document_indexing.py keeps it), and a
-- failed or partial row is claimable again only `lease_seconds` after that.
-- The parameter is reused rather than a new one added: the signature must not
-- change, because PostgREST resolves a function by its argument names and a
-- second overload would sit beside this one (the shape #629's migration had to
-- DROP to close). With the default 300s sweep and 600s lease, a failing
-- document's three attempts spread over roughly half an hour.
--
-- A NEW migration rather than an edit: the first is already recorded in a
-- ledger (local stacks), and an edited file would never re-run there.

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
          -- Never-attempted work first, then whatever was attempted longest ago.
          ORDER BY c.index_leased_at NULLS FIRST, c.created_at
          LIMIT batch_size
          FOR UPDATE SKIP LOCKED
     )
 RETURNING d.id;
$$;

-- CREATE OR REPLACE keeps the function's existing privileges; restated so this
-- file is correct on its own, with the same guarded idiom as the first.
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
