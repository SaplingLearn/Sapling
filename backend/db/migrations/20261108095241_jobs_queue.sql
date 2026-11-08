-- Postgres job queue, part 1: the `jobs` table and its four functions
-- (Trov #116, docs/architecture-hardening-plan.md phase 2).
--
-- What this adds
-- --------------
-- public.jobs: one row per unit of background work. Service-only (RLS bucket
-- E in docs/security/rls-step2-plan.md): RLS on, no policies, nothing granted
-- to anon or authenticated, so only the backend (service_role, which bypasses
-- RLS) and the migration role can see it.
--
-- status:
--   queued    waiting; claimable once run_after has passed
--   running   claimed; locked_by holds it until locked_at + the claim's lease
--   succeeded done (terminal)
--   failed    an attempt failed; claimable again once run_after (now +
--             backoff) has passed. Kept apart from `queued` so a retry never
--             collides with a newer queued row's dedupe_key.
--   dead      dead letter (terminal): attempts ran out, the attempt in hand
--             outlived its lease on the last attempt, or the handler said the
--             job can never succeed
--
-- dedupe_key: optional. At most one QUEUED row per key (a partial unique
-- index), so enqueueing the same key again while the first is still waiting
-- returns that row instead of adding one. Once a job is running, a new enqueue
-- makes a new row: the running one may already have read the state the caller
-- just changed. That is the right shape for "recompute X" work, where a burst
-- of triggers should collapse into one run but a trigger after the run starts
-- must not be lost.
--
-- Functions (all SECURITY INVOKER, search_path pinned to '', service_role only;
-- PostgREST serves them at /rest/v1/rpc/<name>, called from services/jobs.py):
--   enqueue_job(p_type, p_payload, p_dedupe_key, p_run_after, p_max_attempts)
--       -> (id uuid, inserted boolean)
--   claim_jobs(p_worker, p_types, p_limit, p_lease_seconds) -> SETOF jobs
--       First moves spent rows to `dead` (a running row whose lease ran out
--       on its last attempt), then claims up to p_limit claimable rows with
--       FOR UPDATE SKIP LOCKED: queued/failed rows past run_after, plus running
--       rows whose lease has expired (a crashed worker). Each claim adds one
--       to `attempts`. p_types NULL means every type.
--   complete_job(p_id, p_worker, p_attempt) -> boolean
--   fail_job(p_id, p_worker, p_attempt, p_error, p_backoff_seconds,
--            p_permanent) -> text (the new status, NULL if refused)
--       Both are fenced on (locked_by, attempts): a worker whose lease ran out
--       and whose job was re-claimed by another cannot overwrite that claim.
--       They also accept a `dead` row with the same fence, so an attempt that
--       outlived its lease on the last try still records how it really ended.
--       The backoff is computed by the caller (services/jobs.py) and only
--       applied here.
--
-- Why functions and not table() updates: each transition is one atomic
-- statement whose fence and status rule live next to the claim's, and the
-- whole state machine is exercised against real SQL by
-- tests/integration/test_jobs_queue_db.py. enqueue_job is a function because
-- PostgREST's upsert cannot name a partial unique index as its conflict
-- target (42P10, the #529 failure).
--
-- Default privileges: 20261108092633_rls_app_auth_helpers.sql already makes
-- new public functions service_role-only and #807 stops new tables granting
-- anon/authenticated anything. Both are restated explicitly below so this file
-- is correct on its own (and on a database where those defaults are missing).
--
-- Idempotent (IF NOT EXISTS / OR REPLACE / guarded DO blocks), additive, and
-- touches no existing data. Nothing reads or writes the table until the
-- `jobs_queue` flag is turned on (services/feature_flags.py).
--
-- Reverse (by hand, as the migration role). Check the queue is drained first:
--   SELECT status, count(*) FROM public.jobs GROUP BY 1;
-- and turn the `jobs_queue` flag off before, so nothing enqueues meanwhile.
-- Then:
--   DROP FUNCTION IF EXISTS public.fail_job(uuid, text, integer, text, integer, boolean);
--   DROP FUNCTION IF EXISTS public.complete_job(uuid, text, integer);
--   DROP FUNCTION IF EXISTS public.claim_jobs(text, text[], integer, integer);
--   DROP FUNCTION IF EXISTS public.enqueue_job(text, jsonb, text, timestamptz, integer);
--   DROP TABLE IF EXISTS public.jobs;   -- only once it is empty / drained
-- (The table is brand new; dropping it loses nothing but queued work.)

-- ── table ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type         TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status       TEXT NOT NULL DEFAULT 'queued',
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_after    TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at    TIMESTAMPTZ,
    locked_by    TEXT,
    last_error   TEXT,
    dedupe_key   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT jobs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'dead')),
    CONSTRAINT jobs_type_check CHECK (type ~ '^[a-z][a-z0-9_.]{0,62}$'),
    CONSTRAINT jobs_attempts_check CHECK (attempts >= 0),
    CONSTRAINT jobs_max_attempts_check CHECK (max_attempts BETWEEN 1 AND 100)
);

COMMENT ON TABLE public.jobs IS
    'Background job queue (#116). Claimed by claim_jobs() with SKIP LOCKED; drained by `python -m worker`. Service-only.';
COMMENT ON COLUMN public.jobs.payload IS
    'Plaintext JSON: ids only, never student content (it is not column-encrypted).';

-- Claimable rows, oldest run_after first.
CREATE INDEX IF NOT EXISTS jobs_claimable_idx
    ON public.jobs (run_after)
    WHERE status IN ('queued', 'failed');

-- Running rows by lease start, for the re-offer and the reap.
CREATE INDEX IF NOT EXISTS jobs_running_lease_idx
    ON public.jobs (locked_at)
    WHERE status = 'running';

-- At most one waiting row per dedupe key (see the header).
CREATE UNIQUE INDEX IF NOT EXISTS jobs_dedupe_key_queued_key
    ON public.jobs (dedupe_key)
    WHERE status = 'queued' AND dedupe_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_jobs_updated_at'
           AND tgrelid = 'public.jobs'::regclass
    ) THEN
        CREATE TRIGGER trg_jobs_updated_at BEFORE UPDATE ON public.jobs
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.jobs FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.jobs TO service_role;
    END IF;
END $$;

-- ── enqueue_job ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.enqueue_job(
    p_type         TEXT,
    p_payload      JSONB DEFAULT '{}'::jsonb,
    p_dedupe_key   TEXT DEFAULT NULL,
    p_run_after    TIMESTAMPTZ DEFAULT NULL,
    p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE (id UUID, inserted BOOLEAN)
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    -- A second enqueue of a waiting key keeps the existing row and only pulls
    -- its run_after earlier if the new one asks for sooner. DO UPDATE (not DO
    -- NOTHING) so RETURNING always yields the row, even when it already
    -- existed; xmax = 0 tells a fresh insert from that update.
    INSERT INTO public.jobs AS j (type, payload, dedupe_key, run_after, max_attempts)
    VALUES (p_type,
            coalesce(p_payload, '{}'::jsonb),
            p_dedupe_key,
            coalesce(p_run_after, now()),
            coalesce(p_max_attempts, 5))
    ON CONFLICT (dedupe_key) WHERE status = 'queued' AND dedupe_key IS NOT NULL
    DO UPDATE SET run_after = least(j.run_after, excluded.run_after)
    RETURNING j.id, (j.xmax::text = '0');
$$;

-- ── claim_jobs ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.claim_jobs(
    p_worker        TEXT,
    p_types         TEXT[],
    p_limit         INTEGER,
    p_lease_seconds INTEGER
)
RETURNS SETOF public.jobs
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    -- Reap: a row with no attempts left that nothing is running is terminal.
    -- In practice that is a running row whose lease ran out on its last
    -- attempt (fail_job already dead-letters a failure on the last attempt).
    -- locked_by/attempts are left as they were, so an attempt that merely
    -- outlived its lease and then finishes can still record its outcome.
    UPDATE public.jobs r
       SET status     = 'dead',
           last_error = CASE WHEN r.status = 'running' THEN 'lease_expired'
                             ELSE coalesce(r.last_error, 'attempts_exhausted') END
     WHERE r.attempts >= r.max_attempts
       AND (p_types IS NULL OR r.type = ANY (p_types))
       AND (r.status IN ('queued', 'failed')
            OR (r.status = 'running'
                AND r.locked_at < now() - make_interval(secs => p_lease_seconds)));

    -- Claim. A VOLATILE SQL function runs each statement under a fresh
    -- snapshot, so this sees the reap above. SKIP LOCKED: concurrent claimers
    -- each take different rows and never wait on each other.
    WITH picked AS (
        SELECT c.id
          FROM public.jobs c
         WHERE c.attempts < c.max_attempts
           AND (p_types IS NULL OR c.type = ANY (p_types))
           AND (
                   (c.status IN ('queued', 'failed') AND c.run_after <= now())
                   -- A crashed worker's job, once its lease has run out.
                OR (c.status = 'running'
                    AND c.locked_at < now() - make_interval(secs => p_lease_seconds))
               )
         ORDER BY c.run_after, c.created_at
         LIMIT greatest(coalesce(p_limit, 1), 0)
         FOR UPDATE SKIP LOCKED
    )
    UPDATE public.jobs j
       SET status    = 'running',
           attempts  = j.attempts + 1,
           locked_at = now(),
           locked_by = p_worker
      FROM picked
     WHERE j.id = picked.id
 RETURNING j.*;
$$;

-- ── complete_job / fail_job ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.complete_job(
    p_id      UUID,
    p_worker  TEXT,
    p_attempt INTEGER
)
RETURNS BOOLEAN
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    WITH done AS (
        UPDATE public.jobs j
           SET status = 'succeeded'
         WHERE j.id = p_id
           AND j.locked_by = p_worker
           AND j.attempts = p_attempt
           AND j.status IN ('running', 'dead')
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM done);
$$;

CREATE OR REPLACE FUNCTION public.fail_job(
    p_id              UUID,
    p_worker          TEXT,
    p_attempt         INTEGER,
    p_error           TEXT,
    p_backoff_seconds INTEGER,
    p_permanent       BOOLEAN DEFAULT false
)
RETURNS TEXT
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    UPDATE public.jobs j
       SET status     = CASE WHEN coalesce(p_permanent, false) OR j.attempts >= j.max_attempts
                             THEN 'dead' ELSE 'failed' END,
           last_error = left(coalesce(p_error, ''), 2000),
           run_after  = CASE WHEN coalesce(p_permanent, false) OR j.attempts >= j.max_attempts
                             THEN j.run_after
                             ELSE now() + make_interval(
                                      secs => greatest(coalesce(p_backoff_seconds, 0), 0))
                        END
     WHERE j.id = p_id
       AND j.locked_by = p_worker
       AND j.attempts = p_attempt
       AND j.status IN ('running', 'dead')
 RETURNING j.status;
$$;

-- ── function privileges: service_role only ──────────────────────────────────

DO $$
DECLARE
    fn TEXT;
    r  TEXT;
BEGIN
    FOREACH fn IN ARRAY ARRAY[
        'public.enqueue_job(text, jsonb, text, timestamptz, integer)',
        'public.claim_jobs(text, text[], integer, integer)',
        'public.complete_job(uuid, text, integer)',
        'public.fail_job(uuid, text, integer, text, integer, boolean)'
    ] LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;
