-- Account purge (owner decision 2026-11-14): 30 days after a student deletes
-- their own account, a daily job hard-deletes its personal data
-- (services/account_purge.py, driven by services/account_purge_sweeper.py
-- behind the `account_purge` flag, default off).
--
-- What this adds
-- --------------
-- users.purged_at: when the purge finished. The account is then an
--   anonymised stub (no email, no google_id, no profile or settings): the row
--   itself stays because shared rows still point at it — rooms.created_by
--   (NOT NULL, no ON DELETE), the tombstoned room_messages it wrote, a former
--   admin's admin_audit_log rows (ON DELETE RESTRICT) — and llm_usage keeps
--   its id as the billing key. NULL = not purged.
-- users.purge_claimed_at: the lease of the pass purging it now. A pass that
--   dies part-way leaves it set; the account is claimable again once the
--   lease has run out, and the purge re-runs from the start (it converges).
--
-- public.claim_accounts_for_purge(grace_days, lease_seconds, batch_size)
--   -> TABLE (id text)
--   One atomic UPDATE ... RETURNING over FOR UPDATE SKIP LOCKED (the
--   claim_documents_for_indexing pattern), so two replicas never take the same
--   account. Claims accounts deleted more than grace_days ago, never purged,
--   whose lease is free. The grace is floored at 30 days IN SQL: no caller
--   value can purge an account earlier than the policy allows.
--
-- SECURITY INVOKER, search_path pinned, EXECUTE for service_role only.
-- Additive and idempotent (IF NOT EXISTS / OR REPLACE / guarded DO); touches
-- no existing row.
--
-- Reverse (by hand, as the migration role; turn `account_purge` off first):
--   DROP FUNCTION IF EXISTS public.claim_accounts_for_purge(integer, integer, integer);
--   DROP INDEX IF EXISTS public.idx_users_purge_due;
--   ALTER TABLE public.users DROP COLUMN IF EXISTS purge_claimed_at;
--   ALTER TABLE public.users DROP COLUMN IF EXISTS purged_at;
-- (Dropping purged_at forgets which stubs were purged; they stay stubs.)

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS purged_at TIMESTAMPTZ;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS purge_claimed_at TIMESTAMPTZ;

-- The claim's scan: soft-deleted accounts not yet purged (a handful of rows).
CREATE INDEX IF NOT EXISTS idx_users_purge_due
    ON public.users (deleted_at)
    WHERE deleted_at IS NOT NULL AND purged_at IS NULL;

CREATE OR REPLACE FUNCTION public.claim_accounts_for_purge(
    grace_days    INT,
    lease_seconds INT,
    batch_size    INT
)
RETURNS TABLE (id TEXT)
LANGUAGE sql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
    UPDATE public.users u
       SET purge_claimed_at = now()
     WHERE u.id IN (
         SELECT c.id
           FROM public.users c
          WHERE c.deleted_at IS NOT NULL
            AND c.purged_at IS NULL
            AND c.deleted_at < now() - make_interval(days => GREATEST(grace_days, 30))
            AND (c.purge_claimed_at IS NULL
                 OR c.purge_claimed_at
                    < now() - make_interval(secs => GREATEST(lease_seconds, 60)))
          ORDER BY c.deleted_at
          LIMIT GREATEST(batch_size, 0)
          FOR UPDATE SKIP LOCKED
     )
 RETURNING u.id;
$$;

REVOKE ALL ON FUNCTION public.claim_accounts_for_purge(INT, INT, INT) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION public.claim_accounts_for_purge(INT, INT, INT) FROM %I',
                r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.claim_accounts_for_purge(INT, INT, INT)
            TO service_role;
    END IF;
END $$;
